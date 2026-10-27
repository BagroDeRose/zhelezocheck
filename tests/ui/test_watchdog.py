"""«Сторож» потока окна (задача 22.7)."""

import logging
import time

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.ui.watchdog import UiWatchdog, thread_stack


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_default_threshold_is_two_seconds(qtbot: QtBot) -> None:
    assert UiWatchdog().threshold_s == 2


def test_check_reports_once_per_stall(qtbot: QtBot, caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    watchdog = UiWatchdog(threshold_s=2, clock=clock)
    watchdog.beat()
    clock.now += 1.5
    assert not watchdog.check()  # меньше порога — не подвисание
    clock.now += 1.0
    with caplog.at_level(logging.WARNING, logger="hwcheck.ui.watchdog"):
        assert watchdog.check()
        assert not watchdog.check()  # о том же подвисании — один раз
        watchdog.beat()
    assert watchdog.stalls == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("не отвечает уже 2.5 с" in m for m in messages)
    assert any("снова отвечает (пауза 2.5 с)" in m for m in messages)


def test_stack_of_current_thread_names_function() -> None:
    import threading

    def marker_function_for_stack() -> str:
        return thread_stack(threading.get_ident())

    assert "marker_function_for_stack" in marker_function_for_stack()
    assert thread_stack(None) == ""


def slow_ui_handler() -> None:
    time.sleep(0.8)  # имитация долгого вызова в потоке окна


def test_real_stall_logs_what_ui_was_doing(qtbot: QtBot, caplog: pytest.LogCaptureFixture) -> None:
    watchdog = UiWatchdog(threshold_s=0.3, beat_ms=50, check_s=0.05)
    with caplog.at_level(logging.WARNING, logger="hwcheck.ui.watchdog"):
        watchdog.start()
        qtbot.wait(200)
        slow_ui_handler()
        qtbot.wait(200)
        watchdog.stop()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Интерфейс не отвечает" in text
    assert "slow_ui_handler" in text
    assert "снова отвечает" in text
    assert watchdog.stalls == 1
