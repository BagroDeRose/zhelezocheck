"""Движок нагрузочных тестов: запускает шаги по очереди и следит за безопасностью.

Что делает движок:
- запускает тесты (шаги) по очереди через бэкенд, каждый — в отдельном потоке;
- считает общий прогресс с учётом «веса» шагов (долгий шаг весит больше);
- передаёт наружу замеры датчиков (для живых графиков);
- останавливает всё по кнопке «Остановить» не дольше чем за 3 секунды;
- аварийно останавливает шаг, если температура дошла до опасного порога
  (`thresholds.json`), и помечает его «остановлено ради безопасности железа»;
- прерывает зависший шаг по таймауту;
- ошибка в одном шаге не роняет остальные.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from hwcheck.backends.base import HardwareBackend
from hwcheck.models import SensorSample, TestResult, TestStatus
from hwcheck.thresholds import Thresholds, load_thresholds

log = logging.getLogger(__name__)

CANCEL_GRACE_S = 3.0  # сколько ждём завершения шага после отмены
_POLL_S = 0.05

EMERGENCY_NOTE = "Тест остановлен ради безопасности железа"
CANCELLED_NOTE = "Не запускался: проверка остановлена пользователем."


@dataclass
class StressStep:
    """Один шаг проверки: какой тест и сколько секунд."""

    name: str
    duration: float
    weight: float | None = None  # по умолчанию вес = длительность

    @property
    def effective_weight(self) -> float:
        return self.weight if self.weight is not None else max(self.duration, 1.0)


ProgressFn = Callable[[float, str], None]  # (общая доля 0..1, имя текущего шага)
SampleFn = Callable[[str, SensorSample], None]  # (имя шага, замер)
StepDoneFn = Callable[[TestResult], None]


class StressEngine:
    """Выполняет последовательность шагов через бэкенд."""

    def __init__(
        self,
        backend: HardwareBackend,
        thresholds: Thresholds | None = None,
        on_progress: ProgressFn | None = None,
        on_sample: SampleFn | None = None,
        on_step_done: StepDoneFn | None = None,
        timeout_margin_s: float = 120.0,
    ) -> None:
        self.backend = backend
        self.thresholds = thresholds or load_thresholds()
        self.on_progress = on_progress
        self.on_sample = on_sample
        self.on_step_done = on_step_done
        self.timeout_margin_s = timeout_margin_s
        self._progress = 0.0

    # -- общий прогресс ---------------------------------------------------

    def _report_progress(self, value: float, step: str) -> None:
        value = min(max(value, self._progress), 1.0)  # прогресс никогда не идёт назад
        self._progress = value
        if self.on_progress:
            self.on_progress(value, step)

    # -- аварийные пороги -------------------------------------------------

    def emergency_reason(self, sample: SensorSample) -> str | None:
        """Если замер опасен для железа — текст причины, иначе None."""
        temp = sample.values.get("temp_c")
        if temp is None:
            return None
        if sample.component.startswith("gpu"):
            limit = self.thresholds.get("gpu.emergency_stop_c")
        elif sample.component == "cpu":
            limit = self.thresholds.get("cpu.emergency_stop_c")
        else:
            return None
        if temp >= limit:
            return f"{EMERGENCY_NOTE}: температура {temp:.0f} °C (предел {limit:.0f} °C)."
        return None

    # -- запуск -------------------------------------------------------------

    def run(self, steps: list[StressStep], cancel_event: threading.Event) -> list[TestResult]:
        """Выполняет шаги по очереди. Возвращает результат для КАЖДОГО шага."""
        self._progress = 0.0
        total = sum(step.effective_weight for step in steps) or 1.0
        done_weight = 0.0
        results: list[TestResult] = []
        for step in steps:
            if cancel_event.is_set():
                result = TestResult(
                    name=step.name, status=TestStatus.SKIPPED, notes=[CANCELLED_NOTE]
                )
            else:
                start_fraction = done_weight / total
                share = step.effective_weight / total
                result = self._run_step(step, cancel_event, start_fraction, share)
            done_weight += step.effective_weight
            self._report_progress(done_weight / total, step.name)
            results.append(result)
            if self.on_step_done:
                self.on_step_done(result)
        return results

    def _run_step(
        self, step: StressStep, cancel_event: threading.Event, start: float, share: float
    ) -> TestResult:
        step_cancel = threading.Event()
        box: dict[str, object] = {}
        emergency: list[str] = []

        def progress(fraction: float) -> None:
            self._report_progress(start + share * min(max(fraction, 0.0), 1.0), step.name)

        def sample(item: SensorSample) -> None:
            reason = self.emergency_reason(item)
            if reason and not emergency:
                log.warning("Аварийная остановка шага %s: %s", step.name, reason)
                emergency.append(reason)
                step_cancel.set()
            if self.on_sample:
                self.on_sample(step.name, item)

        def worker() -> None:
            try:
                box["result"] = self.backend.run_stress(
                    step.name, step.duration, step_cancel, progress, sample
                )
            except Exception as error:  # ошибка шага не должна ронять движок
                log.exception("Ошибка в шаге %s", step.name)
                box["error"] = error

        thread = threading.Thread(target=worker, name=f"stress-{step.name}", daemon=True)
        started = time.monotonic()
        thread.start()
        deadline = step.duration + self.timeout_margin_s
        timed_out = False
        stop_requested_at: float | None = None
        while thread.is_alive():
            thread.join(_POLL_S)
            now = time.monotonic()
            if stop_requested_at is None:
                if cancel_event.is_set() or step_cancel.is_set():
                    step_cancel.set()
                    stop_requested_at = now
                elif now - started > deadline:
                    timed_out = True
                    step_cancel.set()
                    stop_requested_at = now
            elif now - stop_requested_at > CANCEL_GRACE_S - 0.2:
                log.warning("Шаг %s не остановился вовремя — продолжаем без него", step.name)
                break

        elapsed = time.monotonic() - started
        result = box.get("result")
        if not isinstance(result, TestResult):
            result = TestResult(name=step.name, status=TestStatus.ERROR, duration_s=elapsed)
            if "error" in box:
                result.notes.append(f"Ошибка теста: {box['error']}")
            elif cancel_event.is_set():
                result.status = TestStatus.SKIPPED
                result.notes.append("Тест остановлен пользователем.")
        if emergency:
            result.status = TestStatus.FAILED
            result.metrics["emergency_stop"] = True
            result.metrics.pop("cancelled", None)
            result.notes.append(emergency[0])
        elif timed_out:
            result.status = TestStatus.ERROR
            result.notes.append(f"Тест не уложился в отведённое время ({deadline:.0f} с).")
        elif stop_requested_at is not None and result.status is not TestStatus.SKIPPED:
            result.status = TestStatus.SKIPPED
            result.notes.append("Тест остановлен пользователем.")
        result.name = result.name or step.name
        return result
