"""Ревью 12.2: все разделы доступны в демо; данные прошлой проверки не попадают в следующую
незаметно. С 2.1 объявление вставляется на странице режима только для текущей проверки —
его очистку проверяет `tests/ui/test_listing_field.py`."""

from pathlib import Path

from pytestqt.qtbot import QtBot

from hwcheck.laptop.screen import screen_finding
from tests.ui.helpers import make_window


def test_all_features_available_in_demo(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=True)
    # Версия 2.0: все разделы доступны всем (и в демо, и на реальном железе), без ключа.
    window.go_to("mode")
    assert window.mode_page.listing_edit.isEnabled()
    window.go_to("laptop")
    assert window.laptop_page.screen_button.isEnabled()
    window.go_to("mode")
    assert window.mode_page.full.isEnabled()
    # В меню больше нет пометок «(Pro)».
    labels = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert all("(Pro)" not in label for label in labels)


def test_new_check_clears_laptop_results(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    ctx.manual_findings["screen"] = screen_finding(True)
    window.laptop_page.screen_result.setText("старый результат")
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    window.verdict_page.new_button.click()
    assert ctx.manual_findings == {}
    assert window.laptop_page.screen_result.text() == ""
