"""Тесты реального бэкенда без реальных системных вызовов (сборщики подменены)."""

import json
import threading
from pathlib import Path

from hwcheck.backends.windows import WindowsBackend
from hwcheck.models import BoardInfo, CpuInfo, GpuInfo, HardwareSnapshot, TestStatus

REAL_SNAPSHOT = Path(__file__).parent.parent / "fixtures" / "real" / "dev_machine.json"


def _ok_collectors() -> dict:
    return {
        "cpu": lambda: CpuInfo(name="Test CPU", cores=4, threads=8),
        "board": lambda: BoardInfo(manufacturer="ASUS"),
        "gpus": lambda: [GpuInfo(vendor="NVIDIA", name="RTX")],
    }


def test_collect_all_ok() -> None:
    snap = WindowsBackend(collectors=_ok_collectors(), admin_check=lambda: True).collect()
    assert snap.cpu is not None and snap.cpu.name == "Test CPU"
    assert snap.board is not None and snap.board.manufacturer == "ASUS"
    assert snap.gpus[0].name == "RTX"
    assert snap.is_admin is True
    assert snap.errors == {}
    assert snap.collected_at


def test_one_collector_fails_others_survive() -> None:
    collectors = _ok_collectors()

    def broken() -> CpuInfo:
        raise RuntimeError("WMI сломан")

    collectors["cpu"] = broken
    snap = WindowsBackend(collectors=collectors, admin_check=lambda: False).collect()
    assert snap.cpu is None
    assert "cpu" in snap.errors and "WMI сломан" in snap.errors["cpu"]
    assert snap.board is not None and snap.gpus
    assert snap.is_admin is False


def test_default_collectors_cover_everything() -> None:
    names = set(WindowsBackend().collectors)
    assert names == {"system", "cpu", "memory", "board", "gpus", "disks", "battery", "events"}


def test_unknown_stress_is_skipped() -> None:
    result = WindowsBackend(collectors={}).run_stress("nope", 1, threading.Event())
    assert result.status is TestStatus.SKIPPED


def test_real_dev_snapshot_is_valid() -> None:
    data = json.loads(REAL_SNAPSHOT.read_text(encoding="utf-8"))
    snap = HardwareSnapshot.from_dict(data)
    assert snap.cpu is not None and snap.cpu.cores > 0
    assert snap.memory is not None and snap.memory.total_mb > 0
    assert snap.gpus and snap.gpus[0].pci_device_id
    assert snap.disks
    assert HardwareSnapshot.from_json(snap.to_json()) == snap


def test_default_stress_runners_cover_all_tests() -> None:
    from hwcheck.backends.base import ALL_STRESS_TESTS

    assert WindowsBackend(collectors={}).available_stress_tests() == ALL_STRESS_TESTS


def test_main_gpu_prefers_discrete_with_most_memory() -> None:
    from hwcheck.backends.windows import main_gpu_device_id

    snap = HardwareSnapshot(
        gpus=[
            GpuInfo(vendor="Intel", pci_device_id="4680", vram_mb=2048),
            GpuInfo(vendor="NVIDIA", pci_device_id="2206", vram_mb=10240),
            GpuInfo(vendor="NVIDIA", pci_device_id="1287", vram_mb=2048),
        ]
    )
    assert main_gpu_device_id(snap) == "2206"
    assert main_gpu_device_id(HardwareSnapshot()) is None
    assert main_gpu_device_id(None) is None


# ---------------------------------------------------------------- 15.6 зависший сборщик


def test_hung_collector_does_not_hold_snapshot() -> None:
    import time

    collectors = _ok_collectors()
    release = threading.Event()

    def hung() -> CpuInfo:
        release.wait(30)
        raise RuntimeError("не дождались")

    collectors["cpu"] = hung
    started = time.monotonic()
    snap = WindowsBackend(collectors=collectors, collect_timeout=0.5).collect()
    release.set()
    assert time.monotonic() - started < 3
    assert snap.cpu is None
    assert "не ответил" in snap.errors["cpu"]
    assert snap.board is not None and snap.gpus  # остальные данные на месте


def test_collect_timeout_comes_from_thresholds() -> None:
    from hwcheck.thresholds import load_thresholds

    backend = WindowsBackend(collectors={})
    assert backend.collect_timeout == load_thresholds().get("collect.timeout_s")


def test_vram_test_skipped_without_discrete_gpu() -> None:
    """15.9: у встроенной графики нет своей видеопамяти — тест пропускается с причиной."""
    from hwcheck.backends.base import STRESS_VRAM
    from hwcheck.stress import vram

    collectors = {"gpus": lambda: [GpuInfo(vendor="AMD", name="AMD Radeon(TM) Graphics")]}
    backend = WindowsBackend(collectors=collectors, admin_check=lambda: False)
    backend.collect()
    result = backend.run_stress(STRESS_VRAM, 5, threading.Event())
    assert result.status is TestStatus.SKIPPED
    assert result.notes == [vram.NO_DISCRETE_GPU_NOTE]
