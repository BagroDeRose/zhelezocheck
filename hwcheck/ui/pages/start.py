"""Страница «Старт»: приветствие, права администратора, сводка найденного железа карточками.

Сведения о железе собираются в фоне сразу при открытии — окно при этом не зависает.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwcheck.models import HardwareSnapshot
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label
from hwcheck.ui.summary_cards import SummaryCard, build_cards
from hwcheck.ui.widgets.summary_grid import SummaryGrid
from hwcheck.ui.workers import CollectWorker

log = logging.getLogger(__name__)


def summary_cards(snapshot: HardwareSnapshot) -> list[SummaryCard]:
    """Карточки сводки о железе для показа на старте (задача 22.5)."""
    return build_cards(snapshot)


class StartPage(QWidget):
    """Первая страница проверки."""

    next_requested = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.snapshot: HardwareSnapshot | None = None
        self.worker: CollectWorker | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(title_label(strings.START_TITLE))
        layout.addWidget(text_label(strings.START_INTRO))

        admin = ctx.admin_check()
        self.admin_label = text_label(strings.ADMIN_YES if admin else strings.ADMIN_NO, muted=True)
        self.relaunch_button = QPushButton(strings.ADMIN_RELAUNCH)
        self.relaunch_button.setVisible(not admin and not ctx.is_demo)
        self.relaunch_button.clicked.connect(self._relaunch)
        layout.addWidget(card(self.admin_label, self.relaunch_button))

        # Сводка: строка состояния (идёт сбор / ошибка) и сетка карточек с прокруткой.
        self.summary_label = text_label(strings.COLLECTING, muted=True)
        self.summary_grid = SummaryGrid()
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_scroll.setWidget(self.summary_grid)
        summary = card(title_label(strings.SUMMARY_TITLE), self.summary_label, self.summary_scroll)
        layout.addWidget(summary, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.next_button = QPushButton(strings.NEXT)
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.next_requested.emit)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    def start_collect(self) -> None:
        """Запускает сбор сведений в фоне."""
        self.next_button.setEnabled(False)
        self.summary_label.setText(strings.COLLECTING)
        self.summary_grid.set_cards([])
        self.worker = CollectWorker(self.ctx.backend)
        self.worker.collected.connect(self._on_collected)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_collected(self, snapshot: HardwareSnapshot) -> None:
        self.snapshot = snapshot
        self.next_button.setEnabled(True)
        try:
            self.summary_grid.set_cards(summary_cards(snapshot))
            self.summary_label.setText(strings.SUMMARY_HINT)
        except Exception:  # неполные данные не должны ронять окно (задача 15.6)
            log.exception("Не удалось показать сводку")
            self.summary_label.setText(strings.SUMMARY_FAILED)

    def _on_failed(self, error: str) -> None:
        self.summary_label.setText(strings.COLLECT_FAILED.format(error=escape(error)))
        self.next_button.setEnabled(True)  # проверку можно провести и без сводки

    def _relaunch(self) -> None:
        if self.ctx.relaunch():
            QApplication.quit()
        else:
            self.admin_label.setText(strings.ADMIN_RELAUNCH_FAILED)
