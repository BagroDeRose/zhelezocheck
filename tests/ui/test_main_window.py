"""Каркас окна: открывается, страницы переключаются, тема меняется, строки из strings.py."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.ui import strings
from hwcheck.ui.app import create_window
from tests.ui.helpers import make_window


def test_window_opens_on_start_page(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.show()
    assert window.windowTitle() == strings.WINDOW_TITLE
    assert window.current_page_name() == "start"
    assert window.nav.count() >= 3


def test_navigation_switches_pages(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.nav.setCurrentRow(window.nav_targets.index("settings"))
    assert window.current_page_name() == "settings"
    window.nav.setCurrentRow(window.nav_targets.index("history"))
    assert window.current_page_name() == "history"
    window.nav.setCurrentRow(window.nav_targets.index("check"))
    assert window.current_page_name() == "start"
    window.start_page.next_button.click()
    assert window.current_page_name() == "mode"
    window.go_to("settings")
    window.nav.setCurrentRow(window.nav_targets.index("check"))
    assert window.current_page_name() == "mode"  # возврат на текущий шаг проверки


def test_theme_switch_saved(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path)
    window.settings_page.theme.setCurrentIndex(1)
    assert ctx.settings.theme == "dark"
    assert '"dark"' in ctx.paths.settings_file.read_text(encoding="utf-8")


def test_demo_badge_shown(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, scenario="mining_gpu")
    texts = [label.text() for label in window.findChildren(type(window.start_page.admin_label))]
    assert any("ДЕМО-РЕЖИМ" in text for text in texts)


def test_create_window_demo(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWCHECK_ROOT", str(tmp_path))
    window = create_window("worn_ssd", time_scale=0.0)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    assert "KINGSTON SA400S37480G" in window.start_page.summary_grid.plain_text()


def test_navigation_has_all_sections(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    assert window.nav_targets == ["check", "listing", "laptop", "history", "settings"]
    for target in ("listing", "laptop"):
        window.nav.setCurrentRow(window.nav_targets.index(target))
        assert window.current_page_name() == target
