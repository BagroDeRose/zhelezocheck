"""Фоновые потоки интерфейса: сбор сведений и проверка не замораживают окно.

Работа идёт в отдельном потоке, а результаты приходят в окно через сигналы Qt —
они автоматически доставляются в главный поток.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal, SignalInstance

from hwcheck.backends.base import HardwareBackend
from hwcheck.models import Finding, HardwareSnapshot, ListingClaims, SensorSample, TestResult
from hwcheck.session import run_check

log = logging.getLogger(__name__)


class CollectWorker(QObject):
    """Собирает сведения о железе (только чтение) в фоновом потоке.

    Это обычный «фоновый» поток Python, а не QThread: сбор нельзя прервать (команды Windows
    сами ограничены таймаутами), и если окно закрыли раньше, поток не должен задерживать
    выход из программы или ронять её.
    """

    collected = Signal(object)  # HardwareSnapshot
    failed = Signal(str)

    def __init__(self, backend: HardwareBackend) -> None:
        super().__init__()
        self.backend = backend
        self._thread = threading.Thread(target=self._run, name="collect", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def isRunning(self) -> bool:  # noqa: N802 — как у QThread, чтобы код окна не менялся
        return self._thread.is_alive()

    def isFinished(self) -> bool:  # noqa: N802
        return self._thread.ident is not None and not self._thread.is_alive()

    def _run(self) -> None:
        try:
            snapshot = self.backend.collect()
        except Exception as error:  # показываем ошибку в окне, а не роняем программу
            log.exception("Сбор сведений не удался")
            self._emit(self.failed, str(error))
            return
        self._emit(self.collected, snapshot)

    def _emit(self, signal: SignalInstance, value: object) -> None:
        try:
            signal.emit(value)
        except RuntimeError:  # окно уже закрыто и удалено — результат никому не нужен
            log.info("Сведения собраны после закрытия окна")


class CheckWorker(QThread):
    """Выполняет проверку целиком (нагрузочные тесты + вердикт)."""

    progress = Signal(float, str)  # общая доля, имя шага
    sample = Signal(str, object)  # имя шага, SensorSample
    step_done = Signal(object)  # TestResult
    finished_check = Signal(object)  # CheckSession
    failed = Signal(str)

    def __init__(
        self,
        backend: HardwareBackend,
        mode: str,
        snapshot: HardwareSnapshot | None = None,
        demo_scenario: str = "",
        listing: ListingClaims | None = None,
        manual_findings: list[tuple[Finding, str | None]] | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.listing = listing
        self.manual_findings = manual_findings or []
        self.mode = mode
        self.snapshot = snapshot
        self.demo_scenario = demo_scenario
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Попросить остановиться (движок укладывается в 3 секунды)."""
        self.cancel_event.set()

    def run(self) -> None:
        try:
            session = run_check(
                self.backend,
                self.mode,
                self.cancel_event,
                on_progress=lambda value, step: self.progress.emit(value, step),
                on_sample=self._emit_sample,
                on_step_done=self._emit_step,
                demo_scenario=self.demo_scenario,
                snapshot=self.snapshot,
                listing=self.listing,
                manual_findings=self.manual_findings,
            )
            self.finished_check.emit(session)
        except Exception as error:
            log.exception("Проверка завершилась с ошибкой")
            self.failed.emit(str(error))

    def _emit_sample(self, step: str, sample: SensorSample) -> None:
        self.sample.emit(step, sample)

    def _emit_step(self, result: TestResult) -> None:
        self.step_done.emit(result)
