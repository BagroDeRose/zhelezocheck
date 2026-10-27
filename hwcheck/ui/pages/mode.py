"""Страница «Выбор режима»: быстрая или полная (Pro) проверка и предупреждение о нагрузке."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from hwcheck.models import ListingClaims
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, text_label, title_label


class ModePage(QWidget):
    start_requested = Signal(str)  # quick / full
    back_requested = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        layout.addWidget(title_label(strings.MODE_TITLE))

        self.quick = QRadioButton(strings.MODE_QUICK)
        self.quick.setChecked(True)
        self.full = QRadioButton(strings.MODE_FULL)
        layout.addWidget(card(self.quick, text_label(strings.MODE_QUICK_DESC, muted=True)))
        self.full_note = text_label(strings.MODE_FULL_DESC, muted=True)
        layout.addWidget(card(self.full, self.full_note))
        # Какое объявление будет учтено — чтобы данные прошлой покупки не попали сюда незаметно.
        self.use_listing = QCheckBox()
        self.listing_card = card(self.use_listing)
        layout.addWidget(self.listing_card)
        layout.addWidget(card(text_label("⚠ " + strings.MODE_WARNING)))
        layout.addStretch(1)

        buttons = QHBoxLayout()
        back = QPushButton(strings.BACK)
        back.clicked.connect(self.back_requested.emit)
        buttons.addWidget(back)
        buttons.addStretch(1)
        self.start_button = QPushButton(strings.MODE_START)
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        """Полная проверка доступна всем; показываем сохранённое объявление, если есть."""
        self.full.setEnabled(True)
        self.full.setText(strings.MODE_FULL)
        self.full_note.setText(strings.MODE_FULL_DESC)
        listing = self.ctx.listings.load()
        self.listing_card.setVisible(listing is not None)
        if listing is not None:
            fresh = is_fresh(listing)
            self.use_listing.setText(
                strings.MODE_USE_LISTING.format(title=listing.title or listing.url)
                + ("" if fresh else strings.MODE_LISTING_OLD)
            )
            self.use_listing.setChecked(fresh)

    def listing_to_use(self) -> ListingClaims | None:
        """Объявление для сверки, если пользователь его не отключил."""
        if not self.use_listing.isChecked():
            return None
        return self.ctx.listings.load()

    def selected_mode(self) -> str:
        return "full" if self.full.isChecked() and self.full.isEnabled() else "quick"

    def _start(self) -> None:
        self.start_requested.emit(self.selected_mode())


LISTING_FRESH_HOURS = 24


def is_fresh(listing: ListingClaims, now: datetime | None = None) -> bool:
    """Объявление проанализировано недавно (по умолчанию — за последние сутки)."""
    try:
        analyzed = datetime.fromisoformat(listing.analyzed_at)
    except ValueError:
        return False
    return (now or datetime.now()) - analyzed <= timedelta(hours=LISTING_FRESH_HOURS)
