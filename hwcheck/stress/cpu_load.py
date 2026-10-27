"""Нагрузка всех ядер процессора с проверкой правильности вычислений.

Как работает:
- запускаем столько процессов, сколько у процессора логических ядер;
- каждый процесс снова и снова считает один и тот же блок вычислений (целочисленное умножение
  матриц и поэлементная математика numpy) и сравнивает контрольную сумму с эталоном,
  посчитанным заранее. Исправный процессор всегда получает одно и то же число;
  расхождение означает нестабильность (перегрев, разгон, слабое питание) — это серьёзно;
- параллельно опрашивается частота процессора. Если к концу нагрузки она сильно упала
  относительно начала — процессор перегревается (высохла термопаста, забит кулер).

numpy импортируется внутри функций: дочерний процесс должен успеть запретить numpy
многопоточность до импорта (иначе один «процесс на ядро» займёт все ядра сам).
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import statistics
import threading
import time
from collections.abc import Callable
from typing import Any

from hwcheck.backends.base import STRESS_CPU_LOAD, ProgressCallback, SampleCallback
from hwcheck.models import SensorSample, TestResult, TestStatus
from hwcheck.platform.priority import load_worker_count, lower_own_priority
from hwcheck.stress.gpu_load import LoadWorker
from hwcheck.stress.sensors import SensorRecording
from hwcheck.thresholds import Thresholds, load_thresholds

log = logging.getLogger(__name__)

BLOCK_SIZE = 160
INSTABILITY_NOTE = (
    "Процессор ошибся в вычислениях под нагрузкой — он работает нестабильно "
    "(перегрев, неудачный разгон или проблемы с питанием)."
)


def compute_block(seed: int, size: int = BLOCK_SIZE) -> int:
    """Один блок вычислений. Возвращает контрольную сумму (одинаковую на исправном CPU)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    a = rng.integers(0, 1000, size=(size, size), dtype=np.int64)
    b = rng.integers(0, 1000, size=(size, size), dtype=np.int64)
    product = (a @ b) % 1_000_003
    x = a.astype(np.float64) / 997.0
    wave = np.sin(x) * np.cos(x * 1.5) + np.sqrt(x + 1.0)
    # Округляем, чтобы сумма не зависела от порядка сложения, но ловила ошибки в битах.
    return int(product.sum()) ^ int(np.round(wave * 1e6).astype(np.int64).sum())


def cpu_worker(stop: Any, queue: Any, seed: int, reference: int, max_seconds: float) -> None:
    """Код дочернего процесса: считает блоки и сообщает, сколько раз сумма не сошлась."""
    lower_own_priority()  # окно и система получают процессор первыми (задача 22.7)
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    iterations = 0
    mismatches = 0
    started = time.monotonic()
    last_report = started
    try:
        while not stop.is_set() and time.monotonic() - started < max_seconds:
            if compute_block(seed) != reference:
                mismatches += 1
            iterations += 1
            if time.monotonic() - last_report > 1.0:
                queue.put({"seed": seed, "iterations": iterations, "mismatches": mismatches})
                last_report = time.monotonic()
        queue.put({"seed": seed, "iterations": iterations, "mismatches": mismatches, "done": True})
    except Exception as error:
        queue.put({"seed": seed, "error": f"{type(error).__name__}: {error}"})


class CpuWorkers:
    """Группа процессов нагрузки CPU (по одному на логическое ядро, кроме одного)."""

    def __init__(
        self, count: int, max_seconds: float, target: Callable[..., None] = cpu_worker
    ) -> None:
        ctx = mp.get_context("spawn")
        self._stop = ctx.Event()
        self._queue = ctx.Queue()
        self._processes = []
        for index in range(count):
            seed = 1000 + index
            reference = compute_block(seed)
            self._processes.append(
                ctx.Process(
                    target=target,
                    args=(self._stop, self._queue, seed, reference, max_seconds),
                    daemon=True,
                )
            )
        self._messages: list[dict[str, Any]] = []

    def start(self) -> None:
        for process in self._processes:
            process.start()

    def stop(self) -> None:
        """Останавливает процессы, продолжая читать очередь: процесс на Windows не может
        завершиться, пока его непрочитанные сообщения не забраны из канала."""
        self._stop.set()
        deadline = time.monotonic() + 2.0
        while self.is_alive() and time.monotonic() < deadline:
            self.messages()
            for process in self._processes:
                process.join(timeout=0.05)
        self.messages()
        for process in self._processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)

    def is_alive(self) -> bool:
        return any(process.is_alive() for process in self._processes)

    def messages(self) -> list[dict[str, Any]]:
        while True:
            try:
                self._messages.append(self._queue.get_nowait())
            except Exception:  # очередь пуста
                break
        return self._messages


def summarize_workers(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Итог по всем процессам: последние счётчики каждого, ошибки."""
    latest: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for message in messages:
        if "error" in message:
            errors.append(message["error"])
        elif "seed" in message:
            latest[message["seed"]] = message
    return {
        "workers": len(latest),
        "iterations": sum(m.get("iterations", 0) for m in latest.values()),
        "mismatches": sum(m.get("mismatches", 0) for m in latest.values()),
        "worker_errors": errors,
    }


ZONE_MIN_C = 10.0  # ниже — датчик выдаёт мусор (или это не температура)
ZONE_MAX_C = 120.0  # выше — тоже мусор: процессор отключился бы раньше


def zone_temperature(samples: list[SensorSample]) -> dict[str, Any]:
    """Температура тепловой зоны ACPI под нагрузкой (25.3): только правдоподобные значения.

    Отбрасываются значения ниже 10 °C и выше 120 °C, а также «застывший» датчик — одно и то же
    число всю нагрузку (многие платы отдают заглушку). Это датчик материнской платы, а не
    процессора, поэтому в отчёте — «примерно».
    """
    values = [
        float(v)
        for s in samples
        if s.component == "cpu" and (v := s.values.get("zone_temp_c")) is not None
    ]
    plausible = [v for v in values if ZONE_MIN_C <= v <= ZONE_MAX_C]
    if len(plausible) < 3:
        return {}
    if max(plausible) - min(plausible) < 0.5:
        return {"zone_temp_frozen": True}
    return {"zone_temp_max_c": round(max(plausible), 1), "zone_temp_start_c": plausible[0]}


def analyze_cpu_series(
    samples: list[SensorSample], thresholds: Thresholds | None = None
) -> dict[str, Any]:
    """Падение частоты процессора от начала к концу нагрузки."""
    clocks = [v for s in samples if s.component == "cpu" and (v := s.values.get("clock_mhz"))]
    if len(clocks) < 4:
        return {"clock_samples": len(clocks)}
    skip = len(clocks) // 10  # первые секунды — разгон нагрузки
    working = clocks[skip:] or clocks
    head = working[: max(1, len(working) // 5)]
    tail = working[-max(1, len(working) * 3 // 10) :]
    start, end = statistics.median(head), statistics.median(tail)
    drop = round(max(0.0, (start - end) / start * 100), 1) if start else 0.0
    th = thresholds or load_thresholds()
    return {
        "clock_samples": len(clocks),
        "start_clock_mhz": start,
        "end_clock_mhz": end,
        "avg_clock_mhz": round(statistics.fmean(working)),
        "clock_drop_pct": drop,
        "clock_drop_high": drop > th.get("cpu.clock_drop_pct"),
    }


def evaluate(
    summary: dict[str, Any], series: dict[str, Any], duration: float, samples: list[SensorSample]
) -> TestResult:
    """Собирает итог теста из счётчиков процессов и анализа частот."""
    metrics = {
        **summary,
        **series,
        **zone_temperature(samples),
        "checksum_ok": summary["mismatches"] == 0,
    }
    result = TestResult(
        name=STRESS_CPU_LOAD, component="cpu", duration_s=duration, metrics=metrics, samples=samples
    )
    if summary["mismatches"] > 0:
        result.status = TestStatus.FAILED
        result.notes.append(INSTABILITY_NOTE)
    elif summary["worker_errors"] and summary["iterations"] == 0:
        result.status = TestStatus.ERROR
        result.notes.append(
            "Нагрузку на процессор создать не удалось: " + summary["worker_errors"][0]
        )
    elif series.get("clock_drop_high"):
        result.status = TestStatus.WARNING
        result.notes.append(
            f"Частота процессора под нагрузкой упала на {series['clock_drop_pct']:.0f}%."
        )
    else:
        result.status = TestStatus.PASSED
    if "start_clock_mhz" not in series:
        result.notes.append("Частота процессора под нагрузкой неизвестна (датчик недоступен).")
    return result


def run_cpu_load(
    duration: float,
    cancel_event: threading.Event,
    on_progress: ProgressCallback | None = None,
    on_sample: SampleCallback | None = None,
    workers_factory: Callable[[int, float], LoadWorker] | None = None,
    worker_count: int | None = None,
    use_sensors: bool = True,
    thresholds: Thresholds | None = None,
) -> TestResult:
    """Нагружает процессор `duration` секунд: все логические ядра, кроме одного (22.7)."""
    count = worker_count or load_worker_count(os.cpu_count())
    factory = workers_factory or CpuWorkers
    workers = factory(count, duration + 10)
    cancelled = False
    with SensorRecording(on_sample, enabled=use_sensors, gpu=False) as sensors:
        start = time.monotonic()
        workers.start()
        while True:
            if cancel_event.wait(0.2):
                cancelled = True
                break
            elapsed = time.monotonic() - start
            if on_progress:
                on_progress(min(elapsed / duration, 1.0) if duration > 0 else 1.0)
            workers.messages()  # забираем сообщения сразу, чтобы канал не переполнялся
            if elapsed >= duration or not workers.is_alive():
                break
        workers.stop()
        elapsed = time.monotonic() - start
    if cancelled:
        return TestResult(
            name=STRESS_CPU_LOAD,
            status=TestStatus.SKIPPED,
            component="cpu",
            duration_s=elapsed,
            metrics={"cancelled": True},
            samples=sensors.samples,
            notes=["Тест остановлен пользователем."],
        )
    summary = summarize_workers(workers.messages())
    result = evaluate(
        summary, analyze_cpu_series(sensors.samples, thresholds), elapsed, sensors.samples
    )
    result.notes.extend(sensors.notes())
    return result
