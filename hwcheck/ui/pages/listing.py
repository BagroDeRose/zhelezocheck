"""Страница «Проверка объявления» (Pro), SPEC 1.3 — задача 25.4.

Назначение: раздел не заменяет проверку железа, а дополняет её **до встречи** — помогает
не ехать к сомнительному продавцу и проверить, что продают именно то, что заявлено.

Как пользоваться:
1. Основной способ — вставить текст объявления (скопированный в любом браузере) и нажать
   «Проверить». Второй — открыть сохранённую страницу (.html). Разбор — обычный Python,
   встроенного браузера в программе больше нет: он весил больше 100 МБ и падал на Авито.
2. По желанию — вставить текст страницы поиска той же модели: программа посчитает среднюю
   цену таких же объявлений. Цен она не выдумывает.
3. На встрече, когда собраны сведения о железе, появляется карточка «Сверка с реальным
   железом» с зелёными и красными отметками; сохранённое объявление учитывается в вердикте.

Разбор идёт в фоновом потоке: длинный текст или большой файл не подвешивают окно.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwcheck.knowledge.gpu_db import load_cards
from hwcheck.listing.analyze import analyze_page, analyze_text, apply_market, apply_market_text
from hwcheck.listing.extract import has_data
from hwcheck.listing.match import match_listing
from hwcheck.listing.saved import saved_page_url
from hwcheck.models import HardwareSnapshot, ListingClaims, Severity
from hwcheck.report.builder import rub
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label
from hwcheck.ui.theme import SEVERITY_COLORS

log = logging.getLogger(__name__)

MAX_SAVED_PAGE_BYTES = 30 * 1024 * 1024  # сохранённая страница объявления много меньше
OK_COLOR = SEVERITY_COLORS["ok"]
BAD_COLOR = SEVERITY_COLORS["critical"]


def _mark(ok: bool, text: str) -> str:
    color, sign = (OK_COLOR, "✓") if ok else (BAD_COLOR, "✗")
    return f'<span style="color:{color}"><b>{sign}</b></span> {text}'


def claimed_html(claims: ListingClaims) -> str:
    """Карточка «Что заявлено»."""
    rows = [f"<b>{escape(claims.title) or '—'}</b>", f"Цена: {rub(claims.price_rub)}"]
    if claims.gpu_model:
        vram = f", {claims.gpu_vram_gb:g} ГБ" if claims.gpu_vram_gb else ""
        rows.append(f"Видеокарта: {escape(claims.gpu_model)}{vram}")
    if claims.cpu_model:
        rows.append(f"Процессор: {escape(claims.cpu_model)}")
    if claims.ram_gb:
        rows.append(f"Оперативная память: {claims.ram_gb:g} ГБ")
    if not (claims.gpu_model or claims.cpu_model or claims.ram_gb):
        rows.append("Модель железа в тексте не распознана.")
    if claims.seller_since:
        rows.append(f"Продавец на сайте с {escape(claims.seller_since)}")
    return "<br>".join(rows)


def flags_html(claims: ListingClaims) -> str:
    """Карточка «Тревожные признаки»: каждый с пояснением."""
    if not claims.flags:
        return _mark(True, strings.LISTING_NO_FLAGS)
    blocks = []
    for finding in claims.flags:
        color = SEVERITY_COLORS[finding.severity.value]
        blocks.append(
            f'<span style="color:{color}"><b>{escape(finding.title)}</b></span><br>'
            f"{escape(finding.explanation)}"
        )
    return "<br><br>".join(blocks)


def price_html(claims: ListingClaims) -> str | None:
    """Карточка «Цена»: рынок по поиску пользователя или справка из справочника (без цен).

    None — сказать нечего (нет ни цены, ни модели): карточка скрывается."""
    if claims.market_median_rub and claims.price_rub:
        diff = (claims.price_rub - claims.market_median_rub) / claims.market_median_rub * 100
        where = "ниже" if diff < 0 else "выше"
        return (
            f"В объявлении: <b>{rub(claims.price_rub)}</b><br>"
            f"Средняя на рынке: {rub(claims.market_median_rub)} "
            f"(объявлений: {claims.market_count})<br>"
            f"Цена {where} рынка на {abs(diff):.0f}%."
        )
    card_info = next((c for c in load_cards() if c.model == claims.gpu_model), None)
    price = f"В объявлении: <b>{rub(claims.price_rub)}</b><br>" if claims.price_rub else ""
    if card_info is not None:
        vram = "/".join(f"{v:g}" for v in card_info.vram_gb) + " ГБ"
        tdp = f"потребление до {card_info.tdp_w:g} Вт" if card_info.tdp_w else "потребление —"
        reference = strings.LISTING_PRICE_REFERENCE.format(
            model=escape(card_info.model), vram=vram, tdp=tdp
        )
        return f"{price}{reference}<br>{strings.LISTING_PRICE_NO_MARKET}"
    if claims.price_rub:
        return f"{price}{strings.LISTING_PRICE_NO_MARKET}"
    return None


def match_html(claims: ListingClaims, snapshot: HardwareSnapshot | None) -> str:
    """Карточка «Сверка с реальным железом»: зелёные и красные отметки."""
    if snapshot is None:
        return strings.LISTING_MATCH_WAIT
    rows = [
        _mark(finding.severity is Severity.OK, escape(finding.title))
        for finding, _bargain in match_listing(claims, snapshot)
    ]
    if claims.ram_gb and snapshot.memory is not None and snapshot.memory.total_mb:
        actual = snapshot.memory.total_mb / 1024
        ok = actual >= claims.ram_gb * 0.95
        rows.append(
            _mark(ok, f"Оперативная память: заявлено {claims.ram_gb:g} ГБ, на деле {actual:.0f} ГБ")
        )
    return "<br>".join(rows) or strings.LISTING_MATCH_NOTHING


class ListingPage(QWidget):
    listing_saved = Signal()
    # Итог фонового разбора: номер запроса, вид («listing»/«prices»), результат или ошибка
    _parsed = Signal(int, str, object)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.request_id = 0
        self.pending_id: int | None = None
        # Сведения о железе для сверки (передаёт главное окно после сбора на встрече).
        self.snapshot_provider: Callable[[], HardwareSnapshot | None] = lambda: None
        self._parsed.connect(self._on_parsed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll_area)
        body = QWidget()
        self.scroll_area.setWidget(body)
        layout = QVBoxLayout(body)

        layout.addWidget(title_label(strings.LISTING_TITLE))
        self.intro = text_label(strings.LISTING_INTRO, muted=True)
        layout.addWidget(self.intro)
        layout.addWidget(text_label(strings.LISTING_STEPS))

        # -- ввод объявления -----------------------------------------------------
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(strings.LISTING_INPUT_HINT)
        self.text_edit.setMinimumHeight(110)
        self.analyze_button = QPushButton(strings.LISTING_ANALYZE)
        self.analyze_button.setObjectName("primary")
        self.analyze_button.clicked.connect(lambda: self.analyze())
        self.open_file_button = QPushButton(strings.LISTING_OPEN_FILE)
        self.open_file_button.setToolTip(strings.LISTING_OPEN_FILE_HINT)
        self.open_file_button.clicked.connect(lambda: self.open_saved_file())
        self.clear_text_button = QPushButton(strings.LISTING_CLEAR_TEXT)
        self.clear_text_button.clicked.connect(self.text_edit.clear)
        buttons = QHBoxLayout()
        buttons.addWidget(self.analyze_button)
        buttons.addWidget(self.open_file_button)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_text_button)
        row = QWidget()
        row.setLayout(buttons)
        layout.addWidget(card(title_label(strings.LISTING_INPUT_TITLE), self.text_edit, row))

        # -- цена на рынке -----------------------------------------------------
        self.market_edit = QPlainTextEdit()
        self.market_edit.setPlaceholderText(strings.LISTING_MARKET_PLACEHOLDER)
        self.market_edit.setMaximumHeight(80)
        self.prices_button = QPushButton(strings.LISTING_PRICES)
        self.prices_button.clicked.connect(lambda: self.collect_prices())
        self.open_search_button = QPushButton(strings.LISTING_OPEN_SEARCH)
        self.open_search_button.clicked.connect(lambda: self.open_saved_search())
        market_buttons = QHBoxLayout()
        market_buttons.addWidget(self.prices_button)
        market_buttons.addWidget(self.open_search_button)
        market_buttons.addStretch(1)
        market_row = QWidget()
        market_row.setLayout(market_buttons)
        layout.addWidget(
            card(
                title_label(strings.LISTING_MARKET_TITLE),
                text_label(strings.LISTING_MARKET_HINT, muted=True),
                self.market_edit,
                market_row,
            )
        )

        self.status = text_label("", muted=True)
        layout.addWidget(self.status)

        # -- результаты карточками ----------------------------------------------
        self.empty_label = text_label(strings.LISTING_EMPTY, muted=True)
        layout.addWidget(self.empty_label)
        self.claimed_label = text_label("")
        self.flags_label = text_label("")
        self.price_label = text_label("")
        self.match_label = text_label("")
        self.claimed_card = card(title_label(strings.CARD_CLAIMED), self.claimed_label)
        self.flags_card = card(title_label(strings.CARD_FLAGS), self.flags_label)
        self.price_card = card(title_label(strings.CARD_PRICE), self.price_label)
        self.match_card = card(title_label(strings.CARD_MATCH), self.match_label)
        for result_card in (self.claimed_card, self.flags_card, self.price_card, self.match_card):
            card_layout = result_card.layout()
            if isinstance(card_layout, QVBoxLayout):
                card_layout.addStretch(1)  # содержимое — у верхнего края, как у соседей
        self.results = QWidget()
        grid = QGridLayout(self.results)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.claimed_card, 0, 0)
        grid.addWidget(self.flags_card, 0, 1)
        grid.addWidget(self.price_card, 1, 0)
        grid.addWidget(self.match_card, 1, 1)
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        layout.addWidget(self.results)

        self.clear_button = QPushButton(strings.LISTING_CLEAR)
        self.clear_button.setToolTip(strings.LISTING_CLEAR_HINT)
        self.clear_button.clicked.connect(lambda: self.clear_listing())
        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        clear_row.addWidget(self.clear_button)
        layout.addLayout(clear_row)
        layout.addStretch(1)
        self.refresh()

    # -- состояние -----------------------------------------------------------------

    def refresh(self) -> None:
        for widget in (
            self.text_edit,
            self.analyze_button,
            self.open_file_button,
            self.clear_text_button,
            self.market_edit,
            self.prices_button,
            self.open_search_button,
        ):
            widget.setEnabled(True)
        self.status.setText("")
        self.show_listing(self.ctx.listings.load())

    def show_listing(self, claims: ListingClaims | None) -> None:
        """Показывает сохранённое объявление карточками (или пустое состояние)."""
        self.empty_label.setVisible(claims is None)
        self.results.setVisible(claims is not None)
        self.clear_button.setVisible(claims is not None)
        if claims is None:
            return
        self.claimed_label.setText(claimed_html(claims))
        self.flags_label.setText(flags_html(claims))
        price = price_html(claims)
        self.price_card.setVisible(price is not None)
        self.price_label.setText(price or "")
        self.match_label.setText(match_html(claims, self.snapshot_provider()))

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 — имя метода Qt
        # Сведения о железе могли появиться — обновляем карточку сверки.
        super().showEvent(event)
        if self.pending_id is None:
            self.show_listing(self.ctx.listings.load())

    # -- разбор ------------------------------------------------------------------

    def _begin(self) -> int | None:
        if self.pending_id is not None:
            return None
        self.request_id += 1
        self.pending_id = self.request_id
        self._set_busy(True)
        self.status.setText(strings.LISTING_ANALYZING)
        return self.request_id

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        for widget in (
            self.analyze_button,
            self.open_file_button,
            self.prices_button,
            self.open_search_button,
        ):
            widget.setEnabled(enabled)

    def _run(self, request: int, kind: str, work: Callable[[], object]) -> None:
        """Разбор в фоновом потоке; итог приходит сигналом в главный поток."""

        def target() -> None:
            result: object
            try:
                result = work()
            except Exception as error:  # ошибка разбора — сообщение, а не «вечное ожидание»
                log.exception("Разбор объявления не удался")
                result = error
            try:
                self._parsed.emit(request, kind, result)
            except RuntimeError:  # окно уже закрыто
                log.info("Разбор объявления закончился после закрытия окна")

        threading.Thread(target=target, name="listing-parse", daemon=True).start()

    def analyze(self) -> bool:
        """Кнопка «Проверить»: разбор вставленного текста."""
        text = self.text_edit.toPlainText()
        if not text.strip():
            self.status.setText(strings.LISTING_EMPTY_TEXT)
            return False
        request = self._begin()
        if request is None:
            return False
        self._run(request, "listing", lambda: analyze_text(text))
        return True

    def _read_page(self, path: Path | None, title: str) -> tuple[str, str] | None:
        """Файл сохранённой страницы: (HTML, адрес страницы) или None."""
        if path is None:
            name, _ = QFileDialog.getOpenFileName(self, title, "", strings.LISTING_OPEN_FILE_FILTER)
            if not name:
                return None
            path = Path(name)
        try:
            if path.stat().st_size > MAX_SAVED_PAGE_BYTES:
                self.status.setText(strings.LISTING_FILE_TOO_BIG)
                return None
            html = path.read_bytes().decode("utf-8", errors="replace")
        except OSError as error:
            self.status.setText(strings.LISTING_FAILED.format(error=escape(str(error))))
            return None
        return html, saved_page_url(html, path.resolve().as_uri())

    def open_saved_file(self, path: Path | None = None) -> bool:
        """Кнопка «Открыть сохранённую страницу»: разбор файла .html (без браузера)."""
        if self.pending_id is not None:
            return False
        page = self._read_page(path, strings.LISTING_OPEN_FILE)
        if page is None:
            return False
        html, url = page
        request = self._begin()
        if request is None:
            return False
        self._run(request, "listing", lambda: analyze_page(html, url))
        return True

    def _saved_with_model(self) -> ListingClaims | None:
        saved = self.ctx.listings.load()
        if saved is None or not saved.gpu_model:
            self.status.setText(strings.LISTING_PRICES_NEED_ITEM)
            return None
        return saved

    def collect_prices(self) -> bool:
        """Кнопка «Посчитать цену»: средняя цена по вставленному тексту страницы поиска."""
        saved = self._saved_with_model()
        if saved is None:
            return False
        text = self.market_edit.toPlainText()
        if not text.strip():
            self.status.setText(strings.LISTING_MARKET_HINT)
            return False
        request = self._begin()
        if request is None:
            return False
        self._run(request, "prices", lambda: (saved, apply_market_text(saved, text)))
        return True

    def open_saved_search(self, path: Path | None = None) -> bool:
        """Кнопка «Открыть сохранённую страницу поиска»: средняя цена по файлу .html."""
        saved = self._saved_with_model()
        if saved is None or self.pending_id is not None:
            return False
        page = self._read_page(path, strings.LISTING_OPEN_SEARCH)
        if page is None:
            return False
        html, url = page
        request = self._begin()
        if request is None:
            return False
        self._run(request, "prices", lambda: (saved, apply_market(saved, html, url)))
        return True

    def _on_parsed(self, request: int, kind: str, result: object) -> None:
        if request != self.pending_id:
            return
        self.pending_id = None
        self._set_busy(False)
        if isinstance(result, Exception):
            self.status.setText(strings.LISTING_FAILED.format(error=escape(str(result))))
            return
        try:
            if kind == "listing" and isinstance(result, ListingClaims):
                self._save_listing(result)
            elif isinstance(result, tuple):
                self._save_market(result)
        except Exception as error:  # например, флешка защищена от записи
            log.exception("Сохранение объявления не удалось")
            self.status.setText(strings.LISTING_FAILED.format(error=escape(str(error))))

    def _save_listing(self, claims: ListingClaims) -> None:
        if not has_data(claims):
            self.status.setText(strings.LISTING_NO_DATA)
            return
        self.ctx.listings.save(claims)
        self.show_listing(claims)
        self.status.setText(strings.LISTING_SAVED)
        self.listing_saved.emit()

    def _save_market(self, result: tuple[Any, ...]) -> None:
        claims, market = result
        self.ctx.listings.save(claims)
        self.show_listing(claims)
        if market.median is None:
            self.status.setText(strings.LISTING_PRICES_NONE)
        else:
            self.status.setText(
                strings.LISTING_PRICES_DONE.format(
                    model=escape(claims.gpu_model), median=rub(market.median), count=market.count
                )
            )
        self.listing_saved.emit()

    def clear_listing(self) -> None:
        try:
            self.ctx.listings.clear()
        except OSError as error:
            self.status.setText(strings.LISTING_FAILED.format(error=escape(str(error))))
            return
        self.show_listing(None)
