"""Флешка только для чтения и испорченные файлы данных: программа не падает и не прячет вердикт."""

import sqlite3
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import AppPaths, get_paths
from hwcheck.logging_setup import setup_logging
from hwcheck.storage.history import History
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow
from tests.report.helpers import demo_session


def readonly_paths(tmp_path: Path) -> AppPaths:
    """Корень программы, внутри которого нельзя создать папку data/ (там лежит файл)."""
    root = tmp_path / "stick"
    root.mkdir()
    (root / "data").write_text("это файл, а не папка", encoding="utf-8")
    return get_paths(root)


def test_ensure_reports_readonly(tmp_path: Path) -> None:
    assert get_paths(tmp_path).ensure() is True
    assert readonly_paths(tmp_path).ensure() is False


def test_logging_on_readonly_stick_does_not_crash(tmp_path: Path) -> None:
    import logging

    handler = setup_logging(readonly_paths(tmp_path))
    logging.getLogger("hwcheck.test").warning("проверка")
    logging.getLogger().removeHandler(handler)


def test_check_on_readonly_stick_reaches_verdict(qtbot: QtBot, tmp_path: Path) -> None:
    ctx = AppContext.create(
        FakeBackend("healthy_gaming_pc", time_scale=0.002), readonly_paths(tmp_path), "demo"
    )
    assert ctx.read_only
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    assert window.readonly_banner.isVisibleTo(window)
    assert window.readonly_banner.text() == strings.READONLY_STICK
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.verdict_page.save_report() is None
    assert "Не удалось сохранить отчёт" in window.verdict_page.status_label.text()
    window.go_to("history")  # на защищённой от записи флешке страница не падает


def test_corrupted_history_is_moved_aside(tmp_path: Path) -> None:
    db = tmp_path / "history.sqlite"
    db.write_bytes(b"\x00\x01 not a database " * 100)
    history = History(db)
    history.save(demo_session("worn_ssd"))
    assert len(history.list()) == 1
    assert list(tmp_path.glob("history.sqlite.broken-*"))


class BrokenHistory:
    def save(self, *args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    def list(self, limit: int = 200) -> list[object]:
        raise sqlite3.OperationalError("database is locked")


def test_history_errors_do_not_hide_verdict(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext.create(
        FakeBackend("healthy_gaming_pc", time_scale=0.002), get_paths(tmp_path), "demo"
    )
    monkeypatch.setattr(AppContext, "history", property(lambda self: BrokenHistory()))
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.verdict_page.save_report() is None
    window.go_to("history")
    assert window.history_page.note.text() == strings.HISTORY_UNAVAILABLE
