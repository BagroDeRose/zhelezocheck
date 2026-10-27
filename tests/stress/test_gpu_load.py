"""Тесты анализа поведения видеокарты под нагрузкой и запуска нагрузки (без реального GPU)."""

import sys
import threading
import time
import types
from typing import Any

import pytest

from hwcheck.models import TestStatus
from hwcheck.stress import gpu_load
from tests.stress.series import gpu_samples, ramp

N = 60


def test_normal_warmup() -> None:
    samples = gpu_samples(
        N,
        temp_c=ramp(40, 72, N),
        clock_mhz=ramp(1890, 1845, N),
        fan_pct=ramp(30, 58, N),
        power_w=[168.0] * N,
        throttle_mask=[4.0] * N,  # упор в лимит мощности — нормально
    )
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["max_temp_c"] == 72
    assert metrics["overheating"] is False
    assert metrics["clock_drop_pct"] < 5
    assert metrics["clock_stable"] is True
    assert metrics["power_throttle"] is True and metrics["thermal_throttle"] is False
    assert metrics["fan_not_spinning"] is False
    assert gpu_load.status_from_metrics(metrics) is TestStatus.PASSED


def test_overheating_with_thermal_throttle() -> None:
    samples = gpu_samples(
        N,
        temp_c=ramp(45, 88, N),
        clock_mhz=ramp(1900, 1500, N, plateau_from=0.8),
        fan_pct=ramp(40, 100, N),
        throttle_mask=[0.0] * 30 + [0x20 | 0x40] * 30,
    )
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["overheating"] is True
    assert metrics["thermal_throttle"] is True
    assert set(metrics["throttle_reasons"]) == {"sw_thermal_slowdown", "hw_thermal_slowdown"}
    assert metrics["clock_drop_pct"] > 15
    assert gpu_load.status_from_metrics(metrics) is TestStatus.WARNING


def test_power_throttling_only() -> None:
    samples = gpu_samples(
        N,
        temp_c=ramp(40, 66, N),
        clock_mhz=[1700.0 + (25 if i % 2 else -25) for i in range(N)],
        fan_pct=ramp(30, 50, N),
        throttle_mask=[0x4] * N,
    )
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["power_throttle"] is True
    assert metrics["thermal_throttle"] is False
    assert gpu_load.status_from_metrics(metrics) is TestStatus.PASSED


def test_fan_not_spinning_up() -> None:
    samples = gpu_samples(N, temp_c=ramp(40, 80, N), clock_mhz=[1800.0] * N, fan_pct=[0.0] * N)
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["fan_not_spinning"] is True
    assert gpu_load.status_from_metrics(metrics) is TestStatus.WARNING


def test_fan_maxed_at_moderate_temp() -> None:
    samples = gpu_samples(N, temp_c=ramp(45, 66, N), clock_mhz=[1500.0] * N, fan_pct=[100.0] * N)
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["fan_high_at_moderate_temp"] is True
    assert gpu_load.status_from_metrics(metrics) is TestStatus.WARNING


def test_no_fan_sensor_laptop() -> None:
    samples = gpu_samples(N, temp_c=ramp(45, 75, N), clock_mhz=[1500.0] * N, fan_pct=[None] * N)
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["max_fan_pct"] is None
    assert "fan_not_spinning" not in metrics


def test_pick_loaded_gpu() -> None:
    idle = gpu_samples(10, component="gpu0", util_pct=[1.0] * 10)
    busy = gpu_samples(10, component="gpu1", util_pct=[99.0] * 10)
    assert gpu_load.pick_loaded_gpu(idle + busy) == "gpu1"
    assert gpu_load.pick_loaded_gpu([]) is None


class FakeWorker:
    def __init__(self, messages: list[dict[str, Any]], alive: bool = True) -> None:
        self._messages = messages
        self._alive = alive
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def messages(self) -> list[dict[str, Any]]:
        return self._messages


def test_run_ok_without_sensors() -> None:
    worker = FakeWorker([{"adapter": "Fake GPU"}])
    result = gpu_load.run_gpu_load(
        0.5, threading.Event(), worker_factory=lambda s: worker, use_sensors=False
    )
    assert worker.started and worker.stopped
    assert result.status is TestStatus.PASSED
    assert result.metrics["adapter"] == "Fake GPU"
    assert any("Датчики видеокарты недоступны" in n for n in result.notes)


def test_run_wgpu_unavailable_is_skipped() -> None:
    worker = FakeWorker([{"error": "RuntimeError: no adapter"}], alive=False)
    result = gpu_load.run_gpu_load(
        5, threading.Event(), worker_factory=lambda s: worker, use_sensors=False
    )
    assert result.status is TestStatus.SKIPPED
    assert gpu_load.UNAVAILABLE_NOTE in result.notes


def test_run_cancel() -> None:
    worker = FakeWorker([{"adapter": "Fake GPU"}])
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = gpu_load.run_gpu_load(60, cancel, worker_factory=lambda s: worker, use_sensors=False)
    assert time.monotonic() - start < 3
    assert result.status is TestStatus.SKIPPED and worker.stopped


def test_idle_warmup_samples_ignored_for_clocks() -> None:
    util = [10.0] * 5 + [99.0] * 25
    clocks = [870.0] * 5 + [1920.0] * 25
    samples = gpu_samples(30, util_pct=util, clock_mhz=clocks, temp_c=ramp(48, 60, 30))
    metrics = gpu_load.analyze_gpu_series(samples)
    assert metrics["start_clock_mhz"] == 1920.0
    assert metrics["clock_drop_pct"] == 0.0


# ---------------------------------------------------------------- 22.7 встроенная графика


def test_run_integrated_gpu_is_skipped_quickly() -> None:
    worker = FakeWorker([{"integrated": "AMD Radeon(TM) Graphics"}], alive=False)
    started = time.monotonic()
    result = gpu_load.run_gpu_load(
        60, threading.Event(), worker_factory=lambda s: worker, use_sensors=False
    )
    assert result.status is TestStatus.SKIPPED
    assert result.notes == [gpu_load.INTEGRATED_NOTE]
    assert result.metrics["integrated"] == "AMD Radeon(TM) Graphics"
    assert time.monotonic() - started < 2


class _ListQueue:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def put(self, item: dict[str, Any]) -> None:
        self.items.append(item)


def _fake_wgpu(adapter_type: str) -> types.SimpleNamespace:
    def request_device_sync() -> None:
        raise AssertionError("на встроенной графике устройство не создаётся")

    adapter = types.SimpleNamespace(
        info={"adapter_type": adapter_type, "device": "AMD Radeon(TM) Graphics"},
        request_device_sync=request_device_sync,
    )
    gpu = types.SimpleNamespace(request_adapter_sync=lambda **_kw: adapter)
    return types.SimpleNamespace(gpu=gpu)


def test_worker_refuses_integrated_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "wgpu", _fake_wgpu("IntegratedGPU"))
    queue = _ListQueue()
    gpu_load.gpu_worker(threading.Event(), queue, 5)
    assert queue.items == [{"integrated": "AMD Radeon(TM) Graphics"}]
