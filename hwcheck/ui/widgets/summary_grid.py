"""Сетка карточек сводки «Что найдено» (задача 22.5).

Карточки берутся из `ui/summary_cards.py`. Число колонок зависит от ширины: узкое окно —
одна колонка, широкое — до четырёх. Тексты из системы показываются как обычный текст
(без HTML), чтобы странное имя устройства не могло испортить разметку.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from hwcheck.ui.summary_cards import SummaryCard
from hwcheck.ui.theme import SEVERITY_COLORS

CARD_MIN_WIDTH = 260  # px: уже карточка становится тесной
MAX_COLUMNS = 4


def columns_for(width: int) -> int:
    """Сколько колонок карточек помещается в ширину `width`."""
    return max(1, min(MAX_COLUMNS, width // CARD_MIN_WIDTH))


def _plain(text: str, object_name: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if object_name:
        label.setObjectName(object_name)
    return label


class SummaryCardWidget(QFrame):
    """Одна карточка: иконка и заголовок, параметры, цветной статус."""

    def __init__(self, card: SummaryCard) -> None:
        super().__init__()
        self.card = card
        self.setObjectName("summaryCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        icon = _plain(card.icon, "cardIcon")
        icon.setWordWrap(False)
        header.addWidget(icon)
        self.title_label = _plain(card.title, "cardTitle")
        header.addWidget(self.title_label, 1)
        layout.addLayout(header)

        self.param_labels: list[QLabel] = []
        for name, value in card.params:
            label = _plain(f"{name}: {value}")
            self.param_labels.append(label)
            layout.addWidget(label)
        layout.addStretch(1)

        color = SEVERITY_COLORS.get(card.status, SEVERITY_COLORS["info"])
        self.status_label = _plain(f"● {card.status_text}", "cardStatus")
        self.status_label.setStyleSheet(f"color: {color};")
        layout.addWidget(self.status_label)


class SummaryGrid(QWidget):
    """Адаптивная сетка карточек."""

    def __init__(self) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.cards: list[SummaryCardWidget] = []
        self.columns = 1

    def set_cards(self, cards: list[SummaryCard]) -> None:
        """Заменяет карточки."""
        for widget in self.cards:
            self.grid.removeWidget(widget)
            widget.deleteLater()
        self.cards = [SummaryCardWidget(card) for card in cards]
        self.columns = columns_for(self.width())
        self._place()

    def plain_text(self) -> str:
        """Текст всех карточек (для тестов и журнала)."""
        return "\n".join(widget.card.plain_text() for widget in self.cards)

    def _place(self) -> None:
        for widget in self.cards:
            self.grid.removeWidget(widget)
        for column in range(MAX_COLUMNS):
            self.grid.setColumnStretch(column, 1 if column < self.columns else 0)
        for index, widget in enumerate(self.cards):
            self.grid.addWidget(widget, index // self.columns, index % self.columns)
        # Лишняя высота уходит под карточки, а не растягивает их.
        rows = -(-len(self.cards) // self.columns)
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 1 if row == rows else 0)
        self.grid.setRowStretch(rows, 1)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 — имя метода Qt
        super().resizeEvent(event)
        columns = columns_for(event.size().width())
        if columns != self.columns:
            self.columns = columns
            self._place()
