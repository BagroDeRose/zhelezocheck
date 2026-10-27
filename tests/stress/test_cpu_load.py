"""Тесты нагрузки CPU: детектор падения частот, проверка контрольной суммы, отмена."""

import threading
import time
from typing import Any

import pytest

from hwcheck.models import SensorSample, TestStatus
from hwcheck.stress import cpu_load


def _cpu(clocks: list[float]) -> list[SensorSample]:
    return [
        SensorSample(t=float(i), component="cpu", values={"clock_mhz": c})
        for i, c in enumerate(clocks)
    ]


def test_stable_clocks() -> None:
    series = cpu_load.analyze_cpu_series(_cpu([4400, 4310, 4300, 4290] * 15))
    assert series["clock_drop_pct"] < 5
    assert series["clock_drop_high"] is False


def test_clock_drop_detected() -> None:
    clocks = [4700.0] * 12 + [4700 - 60.0 * i for i in range(30)] + [3000.0] * 18
    series = cpu_load.analyze_cpu_series(_cpu(clocks))
    assert series["clock_drop_pct"] > 30
    assert series["clock_drop_high"] is True


def test_too_few_samples() -> None:
    assert cpu_load.analyze_cpu_series(_cpu([4000, 4000])) == {"clock_samples": 2}


def test_wrong_checksum_is_failed() -> None:
    summary = {"workers": 12, "iterations": 5000, "mismatches": 2, "worker_errors": []}
    result = cpu_load.evaluate(summary, {"clock_drop_pct": 1.0}, 30.0, [])
    assert result.status is TestStatus.FAILED
    assert result.metrics["checksum_ok"] is False
    assert cpu_load.INSTABILITY_NOTE in result.notes


def test_clock_drop_is_warning() -> None:
    summary = {"workers": 12, "iterations": 5000, "mismatches": 0, "worker_errors": []}
    series = {"clock_drop_pct": 36.0, "clock_drop_high": True, "start_clock_mhz": 4700}
    result = cpu_load.evaluate(summary, series, 30.0, [])
    assert result.status is TestStatus.WARNING
    assert result.metrics["checksum_ok"] is True


def test_compute_block_is_deterministic() -> None:
    assert cpu_load.compute_block(7, size=48) == cpu_load.compute_block(7, size=48)
    assert cpu_load.compute_block(7, size=48) != cpu_load.compute_block(8, size=48)


def test_summarize_takes_latest_per_worker() -> None:
    messages = [
        {"seed": 1, "iterations": 10, "mismatches": 0},
        {"seed": 1, "iterations": 25, "mismatches": 1},
        {"seed": 2, "iterations": 30, "mismatches": 0, "done": True},
        {"seed": 3, "error": "MemoryError: "},
    ]
    summary = cpu_load.summarize_workers(messages)
    assert summary == {
        "workers": 2,
        "iterations": 55,
        "mismatches": 1,
        "worker_errors": ["MemoryError: "],
    }


class FakeWorkers:
    def __init__(self, count: int, max_seconds: float) -> None:
        self.count = count
        self.stopped = False

    def start(self) -> None: ...

    def stop(self) -> None:
        self.stopped = True

    def is_alive(self) -> bool:
        return not self.stopped

    def messages(self) -> list[dict[str, Any]]:
        return [{"seed": i, "iterations": 100, "mismatches": 0} for i in range(self.count)]


def test_run_with_fake_workers() -> None:
    result = cpu_load.run_cpu_load(
        0.4, threading.Event(), workers_factory=FakeWorkers, worker_count=4, use_sensors=False
    )
    assert result.status is TestStatus.PASSED
    assert result.metrics["workers"] == 4 and result.metrics["iterations"] == 400


def test_run_cancel() -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = cpu_load.run_cpu_load(
        60, cancel, workers_factory=FakeWorkers, worker_count=2, use_sensors=False
    )
    assert time.monotonic() - start < 3
    assert result.status is TestStatus.SKIPPED


def test_real_workers_no_messages_lost() -> None:
    # Регрессия ревью 12.2: очередь читалась только после остановки, дочерние процессы
    # не могли завершиться (канал переполнен), их убивали — и последние счётчики терялись.
    from tests.stress.flood_worker import MESSAGES, flood_worker

    def factory(count: int, max_seconds: float) -> cpu_load.CpuWorkers:
        return cpu_load.CpuWorkers(count, max_seconds, target=flood_worker)

    result = cpu_load.run_cpu_load(
        1.5, threading.Event(), workers_factory=factory, worker_count=2, use_sensors=False
    )
    assert result.metrics["workers"] == 2
    assert result.metrics["iterations"] == 2 * MESSAGES


# ---------------------------------------------------------------- 22.7 подвисания AMD


def test_default_leaves_one_core_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cpu_load.os, "cpu_count", lambda: 16)
    created: list[int] = []

    def factory(count: int, max_seconds: float) -> FakeWorkers:
        created.append(count)
        return FakeWorkers(count, max_seconds)

    result = cpu_load.run_cpu_load(
        0.3, threading.Event(), workers_factory=factory, use_sensors=False
    )
    assert created == [15]
    assert result.metrics["workers"] == 15


def test_worker_lowers_its_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(cpu_load, "lower_own_priority", lambda: calls.append(True) or True)
    stop = threading.Event()
    stop.set()  # сразу «остановиться»: проверяем только начало работы процесса

    class ListQueue:
        def __init__(self) -> None:
            self.items: list[dict[str, Any]] = []

        def put(self, item: dict[str, Any]) -> None:
            self.items.append(item)

    queue = ListQueue()
    cpu_load.cpu_worker(stop, queue, 1, 0, 1)
    assert calls == [True]
    assert queue.items[-1]["done"]


def _zone(values: list[float]) -> list[SensorSample]:
    return [
        SensorSample(t=float(i), component="cpu", values={"clock_mhz": 4000.0, "zone_temp_c": v})
        for i, v in enumerate(values)
    ]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([45.0, 58.0, 66.5, 71.0], {"zone_temp_max_c": 71.0, "zone_temp_start_c": 45.0}),
        ([27.8, 27.8, 27.8, 27.8], {"zone_temp_frozen": True}),  # заглушка платы
        ([5.0, -273.1, 3.0, 2.0], {}),  # ниже 10 °C — мусор
        ([150.0, 160.0, 170.0], {}),  # выше 120 °C — мусор
        ([50.0, 400.0, 60.0, 70.0], {"zone_temp_max_c": 70.0, "zone_temp_start_c": 50.0}),
    ],
)
def test_zone_temperature_filters_implausible(values: list[float], expected: dict) -> None:
    assert cpu_load.zone_temperature(_zone(values)) == expected


def test_evaluate_keeps_zone_metrics() -> None:
    summary = {"workers": 2, "iterations": 10, "mismatches": 0, "worker_errors": []}
    result = cpu_load.evaluate(summary, {}, 10.0, _zone([45.0, 58.0, 66.5, 71.0]))
    assert result.metrics["zone_temp_max_c"] == 71.0
