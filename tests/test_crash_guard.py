"""Тесты перехвата необработанных ошибок (задача 15.6)."""

import logging
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from hwcheck import crash_guard
from hwcheck.config import get_paths


@pytest.fixture
def restore_hooks() -> Iterator[None]:
    saved = (sys.excepthook, threading.excepthook)
    yield
    sys.excepthook, threading.excepthook = saved
    crash_guard.close()


def _raise() -> BaseException:
    try:
        raise ValueError("сломалось")
    except ValueError as error:
        return error


def test_unhandled_error_is_logged_and_reported(
    restore_hooks: None, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    shown: list[str] = []
    crash_guard.install(get_paths(tmp_path), notify=shown.append, enable_faulthandler=False)
    error = _raise()
    with caplog.at_level(logging.ERROR):
        sys.excepthook(type(error), error, error.__traceback__)
    assert "сломалось" in caplog.text
    assert len(shown) == 1 and "hwcheck.log" in shown[0]


def test_error_in_thread_is_logged(
    restore_hooks: None, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    crash_guard.install(get_paths(tmp_path), notify=None, enable_faulthandler=False)

    def boom() -> None:
        raise RuntimeError("поток упал")

    with caplog.at_level(logging.ERROR):
        thread = threading.Thread(target=boom)
        thread.start()
        thread.join()
    assert "поток упал" in caplog.text


def test_notify_failure_does_not_raise(restore_hooks: None, tmp_path: Path) -> None:
    def bad_notify(_text: str) -> None:
        raise RuntimeError("окно недоступно")

    crash_guard.install(get_paths(tmp_path), notify=bad_notify, enable_faulthandler=False)
    error = _raise()
    sys.excepthook(type(error), error, error.__traceback__)  # не должно бросить


def test_faulthandler_writes_into_program_logs(restore_hooks: None, tmp_path: Path) -> None:
    import faulthandler

    was_enabled = faulthandler.is_enabled()
    paths = get_paths(tmp_path)
    crash_guard.install(paths, notify=None, enable_faulthandler=True)
    try:
        assert faulthandler.is_enabled()
        assert (paths.logs / crash_guard.CRASH_FILE_NAME).exists()
    finally:
        crash_guard.close()
        if was_enabled:
            faulthandler.enable()
