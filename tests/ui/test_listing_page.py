"""Страница «Проверка объявления» (SPEC 1.3, 25.4): вставка текста, файл, цена, сверка.

Встроенного браузера больше нет: всё разбирается на Python, результаты — карточками."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.ui import strings
from hwcheck.ui.pages.listing import ListingPage
from tests.helpers import fixture_text
from tests.ui.helpers import make_window

ITEM = "https://www.avito.ru/kazan/rtx_3070_1"
MINING_TEXT = """Видеокарта RTX 3070 8GB, после майнинга
32 000 ₽
Состояние: Б/у
Работала в майнинге полгода, потом в играх.
"""
SEARCH_TEXT = "RTX 3070 8GB\n30 000 ₽\nRTX 3070 Gaming\n32 000 ₽\nRTX 3070 Ti\n40 000 ₽\n"


def _check_text(qtbot: QtBot, page: ListingPage, text: str) -> None:
    page.text_edit.setPlainText(text)
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        assert page.analyze()


def test_paste_saves_listing_and_next_check_uses_it(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="mining_gpu", pro=True)
    window.go_to("listing")
    page = window.listing_page
    _check_text(qtbot, page, MINING_TEXT)
    assert page.status.text() == strings.LISTING_SAVED
    saved = ctx.listings.load()
    assert saved is not None and saved.gpu_model == "GeForce RTX 3070"
    assert page.results.isVisibleTo(page) and not page.empty_label.isVisibleTo(page)
    assert "GeForce RTX 3070" in page.claimed_label.text()
    assert "майнинг" in page.flags_label.text().lower()

    window.go_to("mode")  # как пользователь: через страницу выбора режима
    assert window.mode_page.use_listing.isChecked()
    window.mode_page.start_button.click()
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.last_session is not None and window.last_session.listing == saved


def test_match_card_with_real_hardware(qtbot: QtBot, tmp_path: Path) -> None:
    """После сбора сведений — зелёные и красные отметки сверки."""
    window, _, _ = make_window(qtbot, tmp_path, scenario="mining_gpu", pro=True)
    window.go_to("listing")
    page = window.listing_page
    _check_text(qtbot, page, "Ryzen 9 7950X, RTX 3070 8GB, 64 ГБ ОЗУ\n90 000 ₽\nИгровой ПК")
    text = page.match_label.text()
    assert "✓" in text and "✗" in text  # видеокарта совпала, процессор и память — нет
    assert "заявлено 64 ГБ" in text


def test_match_card_waits_for_hardware(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    page.snapshot_provider = lambda: None
    _check_text(qtbot, page, MINING_TEXT)
    assert page.match_label.text() == strings.LISTING_MATCH_WAIT


def test_market_price_from_pasted_search(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    _check_text(qtbot, page, MINING_TEXT)
    assert strings.LISTING_PRICE_NO_MARKET in page.price_label.text()  # цен не выдумываем
    page.market_edit.setPlainText(SEARCH_TEXT)
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        assert page.collect_prices()
    saved = ctx.listings.load()
    assert saved is not None and saved.market_median_rub == 31000 and saved.market_count == 2
    assert "31 000" in page.price_label.text() and "выше рынка" in page.price_label.text()


def test_market_price_from_saved_search_page(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    _check_text(qtbot, page, "RTX 3060 12GB\n25 000 ₽\n")
    search = tmp_path / "поиск.html"
    # Браузер при сохранении пишет в файл адрес страницы — по нему узнаётся сайт.
    mark = "<!-- saved from url=(0043)https://www.avito.ru/rossiya?q=rtx+3060 -->\n"
    search.write_text(mark + fixture_text("avito", "search_rtx3060.html"), encoding="utf-8")
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        assert page.open_saved_search(search)
    saved = ctx.listings.load()
    assert saved is not None and saved.market_median_rub == 23500 and saved.market_count == 6


def test_prices_need_listing_with_model(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    page.market_edit.setPlainText(SEARCH_TEXT)
    assert not page.collect_prices()
    assert page.status.text() == strings.LISTING_PRICES_NEED_ITEM


def test_empty_state_and_empty_text(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    assert page.empty_label.isVisibleTo(page) and not page.results.isVisibleTo(page)
    assert not page.analyze()
    assert page.status.text() == strings.LISTING_EMPTY_TEXT


def test_text_without_listing_data_explains_why(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    page.text_edit.setPlainText("!!!\n---\n")
    page.analyze()
    qtbot.waitUntil(lambda: page.status.text() == strings.LISTING_NO_DATA, timeout=5000)
    assert ctx.listings.load() is None


def test_forget_listing(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    _check_text(qtbot, page, MINING_TEXT)
    page.clear_button.click()
    assert ctx.listings.load() is None
    assert page.empty_label.isVisibleTo(page) and not page.clear_button.isVisibleTo(page)


def test_forget_button_explains_itself(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    button = window.listing_page.clear_button
    assert button.text() == "Не учитывать это объявление в проверке"
    assert "проверьте объявление ещё раз" in button.toolTip()


def test_save_error_is_shown_not_stuck(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hwcheck.storage.listings import ListingStore

    def broken_save(self: ListingStore, claims: object) -> Path:
        raise OSError("флешка защищена от записи")

    monkeypatch.setattr(ListingStore, "save", broken_save)
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    page.text_edit.setPlainText(MINING_TEXT)
    page.analyze()
    qtbot.waitUntil(lambda: "защищена от записи" in page.status.text(), timeout=5000)
    assert page.pending_id is None and page.analyze_button.isEnabled()


def test_switching_pages_does_not_stop_analysis(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    window.go_to("listing")
    page = window.listing_page
    page.text_edit.setPlainText(MINING_TEXT)
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        page.analyze()
        window.go_to("settings")
    assert ctx.listings.load() is not None


def test_open_saved_page_file(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    saved_file = tmp_path / "объявление.html"
    html = fixture_text("avito", "item_gpu_mining.html")
    saved_file.write_text(f"<!-- saved from url=(0036){ITEM} -->\n{html}", encoding="utf-8")
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        assert page.open_saved_file(saved_file)
    saved = ctx.listings.load()
    assert saved is not None and saved.gpu_model == "GeForce RTX 3070"
    assert saved.url == ITEM


def test_open_saved_real_page_with_cyrillic_path(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    folder = tmp_path / "Сохранённые страницы"
    folder.mkdir()
    target = folder / "Видеокарта RTX 4080 _ Авито.html"
    target.write_bytes(fixture_text("avito", "real_gpu_rtx4080.html").encode("utf-8"))
    with qtbot.waitSignal(page.listing_saved, timeout=15000):
        assert page.open_saved_file(target)
    saved = ctx.listings.load()
    assert saved is not None and saved.gpu_model == "GeForce RTX 4080" and saved.price_rub == 120000


def test_not_a_listing_file_explains_why(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.listing_page
    other = tmp_path / "просто.html"
    other.write_text("<html><body></body></html>", encoding="utf-8")
    page.open_saved_file(other)
    qtbot.waitUntil(lambda: page.status.text() == strings.LISTING_NO_DATA, timeout=5000)


def test_saved_page_url_detection() -> None:
    from hwcheck.listing.saved import saved_page_url

    assert saved_page_url(f"<!-- saved from url=(0036){ITEM} -->", "f") == ITEM
    canonical = f'<link rel="canonical" href="{ITEM}">'
    assert saved_page_url(canonical, "f") == ITEM
    assert saved_page_url("<html></html>", "file:///x.html") == "file:///x.html"


def test_listing_page_available_for_everyone(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=False)
    page = window.listing_page
    # Версия 2.0: разбор объявления доступен всем, без ключа.
    assert page.analyze_button.isEnabled() and page.text_edit.isEnabled()
    page.text_edit.setPlainText(MINING_TEXT)
    assert page.analyze()
