"""Захват временных рядов под нагрузкой (этап 42 v2.1): время начала, отметки начала/конца,
прерываний и ошибок, сохранение рядов в истории, отсутствующий датчик — без точек."""

import threading
from datetime import datetime
from pathlib import Path

from hwcheck import schema
from hwcheck.backends import base
from hwcheck.backends.fake import FakeBackend
from hwcheck.models import TestResult
from hwcheck.session import run_check
from hwcheck.storage.history import History
from hwcheck.stress.engine import StressEngine, StressStep
from hwcheck.thresholds import load_thresholds
from tests.stress.test_engine import BrokenBackend


def kinds(result: TestResult) -> list[str]:
    return [marker.kind for marker in result.markers]


def test_finished_steps_have_start_time_and_start_end_markers() -> None:
    engine = StressEngine(FakeBackend("healthy_gaming_pc", time_scale=0.0))
    results = engine.run(
        [StressStep(base.STRESS_GPU_LOAD, 20), StressStep(base.STRESS_RAM_QUICK, 5)],
        threading.Event(),
    )
    for result in results:
        assert datetime.fromisoformat(result.started_at)  # настоящее местное время начала
        assert kinds(result) == ["start", "end"]
        assert result.markers[0].elapsed_seconds == 0.0
    gpu = results[0]
    assert gpu.samples
    assert gpu.markers[-1].elapsed_seconds == gpu.samples[-1].t  # конец — по последнему замеру


def test_emergency_stop_is_marked_where_it_happened() -> None:
    backend = FakeBackend("mining_gpu", time_scale=0.0)
    backend.scenario.stress[base.STRESS_GPU_LOAD].series_points["temp_c"] = [60, 80, 96, 99]
    (gpu,) = StressEngine(backend).run([StressStep(base.STRESS_GPU_LOAD, 40)], threading.Event())
    assert kinds(gpu) == ["start", "emergency"]
    limit = load_thresholds().get("gpu.emergency_stop_c")
    hot = next(s for s in gpu.samples if (s.values["temp_c"] or 0) >= limit)
    assert gpu.markers[-1].elapsed_seconds == hot.t
    assert "°C" in gpu.markers[-1].text


def test_user_stop_marks_interrupt_and_not_started_steps_have_no_markers() -> None:
    engine = StressEngine(FakeBackend("healthy_gaming_pc", time_scale=1.0))
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    first, second = engine.run(
        [StressStep(base.STRESS_GPU_LOAD, 30), StressStep(base.STRESS_CPU_LOAD, 30)], cancel
    )
    assert kinds(first) == ["start", "interrupt"]
    assert second.markers == [] and second.started_at == ""  # не запускался — не придумываем


def test_crashed_step_is_marked_as_error() -> None:
    (vram,) = StressEngine(BrokenBackend("healthy_gaming_pc", time_scale=0.0)).run(
        [StressStep(base.STRESS_VRAM, 5)], threading.Event()
    )
    assert kinds(vram) == ["start", "error"]


def test_series_survive_history_round_trip(tmp_path: Path) -> None:
    """Ряды хранятся вместе с проверкой (не картинкой) и восстанавливаются из истории."""
    session = run_check(
        FakeBackend("healthy_gaming_pc", time_scale=0.0), "quick", threading.Event()
    )
    before = {r.name: schema.series_points(r) for r in session.results}
    assert any(before.values())
    history = History(tmp_path / "history.sqlite")
    history.save(session)
    loaded = history.load_session(session.id)
    assert loaded is not None
    after = {r.name: schema.series_points(r) for r in loaded.results}
    assert after == before
    assert [r.markers for r in loaded.results] == [r.markers for r in session.results]


def test_missing_sensor_gives_no_points() -> None:
    """Нет датчика вентилятора — нет и точек вентилятора; остальные датчики на месте."""
    backend = FakeBackend("healthy_gaming_pc", time_scale=0.0)
    series = backend.scenario.stress[base.STRESS_GPU_LOAD].series_points
    assert "fan_pct" in series
    del series["fan_pct"]
    (gpu,) = StressEngine(backend).run([StressStep(base.STRESS_GPU_LOAD, 20)], threading.Event())
    ids = {point.sensor_id for point in schema.series_points(gpu)}
    assert "gpu0.fan" not in ids and "gpu0.temperature" in ids
