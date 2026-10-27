"""Тесты движка нагрузочных тестов на фейковом бэкенде."""

import threading
import time

from hwcheck.backends import base
from hwcheck.backends.fake import FakeBackend
from hwcheck.models import SensorSample, TestResult, TestStatus
from hwcheck.stress.engine import EMERGENCY_NOTE, StressEngine, StressStep

STEPS = [
    StressStep(base.STRESS_VRAM, 30),
    StressStep(base.STRESS_GPU_LOAD, 20),
    StressStep(base.STRESS_CPU_LOAD, 20),
    StressStep(base.STRESS_RAM_QUICK, 10),
    StressStep(base.STRESS_DISK_READ, 10),
]


def test_full_run_progress_monotonic_and_results() -> None:
    progress: list[float] = []
    samples: list[tuple[str, SensorSample]] = []
    done: list[TestResult] = []
    engine = StressEngine(
        FakeBackend("healthy_gaming_pc"),
        on_progress=lambda value, step: progress.append(value),
        on_sample=lambda step, sample: samples.append((step, sample)),
        on_step_done=done.append,
    )
    results = engine.run(STEPS, threading.Event())
    assert [r.name for r in results] == [s.name for s in STEPS]
    assert all(r.status is TestStatus.PASSED for r in results)
    assert progress == sorted(progress)
    assert progress[-1] == 1.0
    assert samples and samples[0][0] == base.STRESS_VRAM
    assert done == results


def test_cancel_stops_within_3_seconds() -> None:
    engine = StressEngine(FakeBackend("healthy_gaming_pc", time_scale=1.0))
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    start = time.monotonic()
    results = engine.run(STEPS, cancel)
    assert time.monotonic() - start < 3.5
    assert len(results) == len(STEPS)
    assert all(r.status is TestStatus.SKIPPED for r in results)


def test_emergency_threshold_stops_step() -> None:
    backend = FakeBackend("mining_gpu", time_scale=0.0)
    backend.scenario.stress[base.STRESS_GPU_LOAD].series_points["temp_c"] = [60, 80, 96, 99]
    engine = StressEngine(backend)
    results = engine.run(
        [StressStep(base.STRESS_GPU_LOAD, 40), StressStep("cpu_load", 5)], threading.Event()
    )
    gpu, cpu = results
    assert gpu.status is TestStatus.FAILED
    assert gpu.metrics["emergency_stop"] is True
    assert any(EMERGENCY_NOTE in note for note in gpu.notes)
    # Последний замер — не выше порога + один шаг, тест действительно прервался.
    assert max(s.values["temp_c"] or 0 for s in gpu.samples) < 96
    assert cpu.status is TestStatus.PASSED  # остальные шаги продолжаются


class BrokenBackend(FakeBackend):
    def run_stress(self, name, duration, cancel_event, on_progress=None, on_sample=None):
        if name == base.STRESS_VRAM:
            raise RuntimeError("драйвер упал")
        return super().run_stress(name, duration, cancel_event, on_progress, on_sample)


def test_exception_in_step_does_not_crash_engine() -> None:
    engine = StressEngine(BrokenBackend("healthy_gaming_pc"))
    results = engine.run(STEPS[:2], threading.Event())
    assert results[0].status is TestStatus.ERROR
    assert "драйвер упал" in results[0].notes[0]
    assert results[1].status is TestStatus.PASSED


class HangingBackend(FakeBackend):
    """Шаг, который игнорирует отмену (имитация зависшей программы)."""

    def run_stress(self, name, duration, cancel_event, on_progress=None, on_sample=None):
        time.sleep(10)
        return TestResult(name=name, status=TestStatus.PASSED)


def test_step_timeout() -> None:
    engine = StressEngine(HangingBackend("healthy_gaming_pc"), timeout_margin_s=0.3)
    start = time.monotonic()
    (result,) = engine.run([StressStep(base.STRESS_VRAM, 0.2)], threading.Event())
    assert result.status is TestStatus.ERROR
    assert time.monotonic() - start < 4.5


def test_hanging_step_cancel_returns_in_time() -> None:
    engine = StressEngine(HangingBackend("healthy_gaming_pc"))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    start = time.monotonic()
    (result,) = engine.run([StressStep(base.STRESS_VRAM, 60)], cancel)
    assert time.monotonic() - start < 3.5
    assert result.status is TestStatus.SKIPPED


def test_weights() -> None:
    assert StressStep("x", 120).effective_weight == 120
    assert StressStep("x", 10, weight=5).effective_weight == 5
