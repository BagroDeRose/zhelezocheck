"""Тесты фейкового бэкенда: сценарии загружаются, данные согласованы, «стресс» отменяется."""

import threading
import time

import pytest

from hwcheck.backends import base
from hwcheck.backends.fake import FakeBackend, list_scenarios, load_scenario
from hwcheck.models import HardwareSnapshot, SensorSample, TestStatus

EXPECTED_SCENARIOS = {
    "healthy_gaming_pc",
    "mining_gpu",
    "fake_gpu_relabel",
    "overheating_cpu",
    "dying_hdd",
    "worn_ssd",
    "laptop_worn_battery",
    "ram_errors",
}


def test_all_scenarios_present() -> None:
    assert EXPECTED_SCENARIOS <= set(list_scenarios())


@pytest.mark.parametrize("name", sorted(EXPECTED_SCENARIOS))
def test_scenario_consistent(name: str) -> None:
    scenario = load_scenario(name)
    snap = scenario.snapshot
    assert isinstance(snap, HardwareSnapshot)
    assert scenario.title
    # Модель проходит путь туда-обратно без потерь.
    assert HardwareSnapshot.from_json(snap.to_json()) == snap
    # Память: общий объём равен сумме планок.
    assert snap.memory is not None
    assert snap.memory.total_mb == sum(m.capacity_mb for m in snap.memory.modules)
    # Ноутбук ↔ батарея.
    assert snap.system is not None
    assert snap.system.is_laptop == (snap.battery is not None)
    # У каждой видеокарты есть коды устройства.
    for gpu in snap.gpus:
        assert len(gpu.pci_vendor_id) == 4 and len(gpu.pci_device_id) == 4
        assert f"DEV_{gpu.pci_device_id.upper()}" in gpu.pnp_device_id
    # Для всех тестов есть описание, и максимум температуры в метриках совпадает с графиком.
    assert set(scenario.stress) == set(base.ALL_STRESS_TESTS)
    for test_name, spec in scenario.stress.items():
        temps = [v for v in spec.series_points.get("temp_c", []) if v is not None]
        if "max_temp_c" in spec.metrics and temps:
            assert spec.metrics["max_temp_c"] == max(temps), (name, test_name)


def test_unknown_scenario() -> None:
    with pytest.raises(KeyError):
        load_scenario("no_such_scenario")


def test_collect_returns_snapshot_copy() -> None:
    backend = FakeBackend("healthy_gaming_pc")
    first = backend.collect()
    first.gpus.clear()
    assert backend.collect().gpus, "collect должен отдавать независимую копию"


def test_available_stress_tests() -> None:
    assert FakeBackend("healthy_gaming_pc").available_stress_tests() == base.ALL_STRESS_TESTS


def test_run_stress_full() -> None:
    backend = FakeBackend("mining_gpu", time_scale=0.0)
    progress: list[float] = []
    samples: list[SensorSample] = []
    result = backend.run_stress(
        base.STRESS_GPU_LOAD, 20, threading.Event(), progress.append, samples.append
    )
    assert result.status is TestStatus.PASSED
    assert result.metrics["max_fan_pct"] == 100.0
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert len(samples) == 20
    assert samples[0].values["temp_c"] == 45 and samples[-1].values["temp_c"] == 66
    assert result.samples == samples


def test_run_stress_without_series() -> None:
    backend = FakeBackend("ram_errors", time_scale=0.0)
    result = backend.run_stress(base.STRESS_RAM_QUICK, 5, threading.Event())
    assert result.status is TestStatus.FAILED
    assert result.metrics["errors"] == 3
    assert result.samples == []


def test_run_stress_cancel_fast() -> None:
    backend = FakeBackend("healthy_gaming_pc", time_scale=1.0)  # «реальное» время
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = backend.run_stress(base.STRESS_GPU_LOAD, 60, cancel)
    assert time.monotonic() - start < 3
    assert result.status is TestStatus.SKIPPED
    assert result.metrics.get("cancelled") is True


def test_run_unknown_stress() -> None:
    backend = FakeBackend("healthy_gaming_pc", time_scale=0.0)
    result = backend.run_stress("no_such_test", 5, threading.Event())
    assert result.status is TestStatus.SKIPPED
