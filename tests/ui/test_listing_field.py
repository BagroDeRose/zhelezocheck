"""Поле «Сверить с объявлением» на странице режима (2.1, вместо раздела «Проверка
объявления»): распознанное видно сразу, сверка попадает в вердикт, «Новая проверка» очищает
поле, отдельного пункта меню больше нет."""

from pathlib import Path

from pytestqt.qtbot import QtBot

from hwcheck.ui import strings
from tests.ui.helpers import make_window

LISTING = "Игровой ПК: RTX 3070 8GB, Ryzen 5 5600, 32 ГБ ОЗУ\n65 000 ₽\n"


def test_no_listing_section_in_menu(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    labels = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert "Проверка объявления" not in labels
    assert "listing" not in window.pages


def test_recognized_claims_are_shown(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.go_to("mode")
    page = window.mode_page
    assert page.listing_result.text() == "" and not page.listing_clear.isVisibleTo(page)
    page.listing_edit.setPlainText(LISTING)
    qtbot.waitUntil(lambda: "RTX 3070" in page.listing_result.text(), timeout=3000)
    assert "Ryzen 5 5600" in page.listing_result.text()
    assert "ОЗУ 32 ГБ" in page.listing_result.text()
    page.listing_edit.setPlainText("Продаю компьютер, звоните.")
    qtbot.waitUntil(lambda: page.listing_result.text() == strings.MODE_LISTING_NOTHING)


def test_listing_is_compared_and_cleared_by_new_check(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, scenario="mining_gpu")
    window.go_to("mode")
    window.mode_page.listing_edit.setPlainText(LISTING)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    session = window.last_session
    assert session is not None and session.listing is not None and session.verdict is not None
    assert "listing.gpu_match" in {f.id for f in session.verdict.findings}
    window.verdict_page.new_button.click()
    assert window.mode_page.listing_edit.toPlainText() == ""
    assert window.mode_page.listing_to_use() is None


def test_empty_field_means_no_listing(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.last_session is not None and window.last_session.listing is None


def test_clear_button(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    page = window.mode_page
    page.listing_edit.setPlainText(LISTING)
    page.listing_clear.click()
    assert page.listing_edit.toPlainText() == "" and page.listing_result.text() == ""
