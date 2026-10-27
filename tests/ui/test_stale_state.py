"""Ревью 12.2: демо без ключа не открывает «настоящие» Pro-функции; данные прошлой проверки
не попадают в следующую незаметно."""

from datetime import datetime, timedelta
from pathlib import Path

from pytestqt.qtbot import QtBot

from hwcheck.laptop.screen import screen_finding
from hwcheck.listing.analyze import analyze_page
from tests.helpers import fixture_text
from tests.ui.helpers import make_window

ITEM = "https://www.avito.ru/kazan/rtx_3070_1"


def test_all_features_available_in_demo(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=True)
    # Версия 2.0: все разделы доступны всем (и в демо, и на реальном железе), без ключа.
    window.go_to("listing")
    assert window.listing_page.analyze_button.isEnabled()
    assert window.listing_page.text_edit.isEnabled()
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


def _save_listing(ctx, analyzed_at: datetime) -> None:  # noqa: ANN001
    claims = analyze_page(fixture_text("avito", "item_gpu_mining.html"), ITEM)
    claims.analyzed_at = analyzed_at.isoformat(timespec="seconds")
    ctx.listings.save(claims)


def test_mode_page_shows_fresh_listing_and_can_skip_it(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="mining_gpu", pro=True)
    _save_listing(ctx, datetime.now())
    window.go_to("mode")
    page = window.mode_page
    assert page.use_listing.isVisibleTo(page) and page.use_listing.isChecked()
    assert "RTX 3070 8gb после майнинга" in page.use_listing.text()
    page.use_listing.setChecked(False)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.last_session is not None and window.last_session.listing is None


def test_old_listing_not_used_by_default(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    _save_listing(ctx, datetime.now() - timedelta(days=3))
    window.go_to("mode")
    assert window.mode_page.use_listing.isVisibleTo(window.mode_page)
    assert not window.mode_page.use_listing.isChecked()


def test_no_listing_no_checkbox(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    window.go_to("mode")
    assert not window.mode_page.use_listing.isVisibleTo(window.mode_page)
