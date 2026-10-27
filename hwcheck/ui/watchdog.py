"""«Сторож» потока окна: находит подвисания интерфейса по журналу (задача 22.7).

Таймер в потоке окна раз в четверть секунды отмечается «я жив». Отдельный фоновый поток
проверяет отметки: если окно молчит дольше порога (`ui.watchdog_s` в thresholds.json,
2 секунды), в журнал пишется, сколько оно не отвечает и какой код сейчас выполняет поток
окна (стек вызовов). Когда окно оживает — ещё одна запись с длительностью паузы.
Так по журналу пользователя видно, что именно подвешивало программу.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from hwcheck.thresholds import load_thresholds

log = logging.getLogger(__name__)

BEAT_MS = 250  # как часто поток окна отмечается
CHECK_S = 0.5  # как часто сторож смотрит на отметки
STACK_LINES = 25  # сколько последних строк стека писать в журнал


def thread_stack(ident: int | None) -> str:
    """Текущий стек вызовов потока `ident` (последние строки) или пустая строка."""
    frame = sys._current_frames().get(ident) if ident is not None else None
    if frame is None:
        return ""
    lines = traceback.format_stack(frame)
    return "".join(lines[-STACK_LINES:]).rstrip()


class UiWatchdog(QObject):
    """Следит, чтобы поток окна не замирал дольше порога."""

    def __init__(
        self,
        threshold_s: float | None = None,
        beat_ms: int = BEAT_MS,
        check_s: float = CHECK_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self.threshold_s = threshold_s or load_thresholds().get("ui.watchdog_s")
        self.check_s = check_s
        self.clock = clock
        self.ui_ident = threading.get_ident()  # создаётся в потоке окна
        self.stalls = 0
        self._last_beat = clock()
        self._reported = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(beat_ms)
        self._timer.timeout.connect(self.beat)

    def start(self) -> None:
        self._last_beat = self.clock()
        self._timer.start()
        self._thread = threading.Thread(target=self._run, name="ui-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()

    def beat(self) -> None:
        """Отметка «окно живо» (вызывается таймером в потоке окна)."""
        now = self.clock()
        with self._lock:
            if self._reported:
                log.warning("Интерфейс снова отвечает (пауза %.1f с)", now - self._last_beat)
                self._reported = False
            self._last_beat = now

    def check(self) -> bool:
        """Проверка из фонового потока. True — если сейчас записано новое подвисание."""
        with self._lock:
            silent = self.clock() - self._last_beat
            if silent <= self.threshold_s or self._reported:
                return False
            self._reported = True
            self.stalls += 1
        stack = thread_stack(self.ui_ident) or "(стек недоступен)"
        log.warning("Интерфейс не отвечает уже %.1f с. Чем занят поток окна:\n%s", silent, stack)
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.check_s):
            self.check()
