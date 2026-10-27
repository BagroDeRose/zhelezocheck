"""Страница «История и отчёты» (Pro): прошлые проверки и их отчёты."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hwcheck.report.builder import MODE_TITLES, save_html
from hwcheck.storage.history import HistoryEntry
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import escape, text_label, title_label


class HistoryPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.entries: list[HistoryEntry] = []
        layout = QVBoxLayout(self)
        layout.addWidget(title_label(strings.HISTORY_TITLE))
        self.note = text_label("", muted=True)
        layout.addWidget(self.note)
        self.table = QTableWidget(0, len(strings.HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(strings.HISTORY_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.open_selected())
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_button = QPushButton(strings.HISTORY_OPEN)
        self.open_button.clicked.connect(self.open_selected)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        self.table.setEnabled(True)
        self.open_button.setEnabled(True)
        self.note.setVisible(True)
        try:
            self.entries = self.ctx.history.list()
        except (OSError, sqlite3.Error) as error:
            logging.getLogger(__name__).warning("История недоступна: %s", error)
            self.entries = []
            self.table.setRowCount(0)
            self.note.setText(strings.HISTORY_UNAVAILABLE)
            return
        self.note.setText("" if self.entries else strings.HISTORY_EMPTY)
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            values = [
                entry.created_at.replace("T", " "),
                MODE_TITLES.get(entry.mode, entry.mode),
                strings.DECISION_TITLES.get(entry.decision, entry.decision),
                entry.computer,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def open_selected(self) -> Path | None:
        """Открывает отчёт выбранной проверки (если файла нет — пересоздаёт HTML)."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self.entries):
            return None
        entry = self.entries[row]
        path = Path(entry.report_path) if entry.report_path else None
        if path is not None and not path.is_file():
            # Флешка могла получить другую букву диска — ищем отчёт в папке отчётов по имени.
            moved = self.ctx.paths.reports / path.name
            path = moved if moved.is_file() else None
        if path is None:
            try:
                session = self.ctx.history.load_session(entry.id)
                if session is None:
                    return None
                path = save_html(session, self.ctx.paths.reports)
                self.ctx.history.set_report_path(entry.id, path)
            except (OSError, sqlite3.Error) as error:
                self.note.setText(strings.REPORT_FAILED.format(error=escape(str(error))))
                return None
        self.ctx.open_path(path)
        return path
