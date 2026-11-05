"""Страница «Выбор режима»: быстрая или полная проверка, необязательная сверка с объявлением
и предупреждение о нагрузке.

Сверка с объявлением (с 2.1 вместо отдельного раздела «Проверка объявления»): можно вставить
текст объявления — программа распознает заявленные видеокарту, процессор и объём памяти и
после проверки сверит их с найденным железом. Поле необязательное; распознанное видно сразу
под полем. Текст относится только к этой проверке: «Новая проверка» его очищает, на флешку он
отдельно не сохраняется (только в составе отчёта).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from hwcheck.listing.text import claims_summary, listing_from_text
from hwcheck.models import ListingClaims
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label

RECOGNIZE_DELAY_MS = 300  # распознаём, когда пользователь перестал печатать


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
        # Кнопки лежат в разных карточках (разные родители), поэтому сами по себе Qt их не
        # связывает — без общей группы можно было отметить оба режима сразу.
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.quick)
        self.mode_group.addButton(self.full)
        layout.addWidget(card(self.quick, text_label(strings.MODE_QUICK_DESC, muted=True)))
        self.full_note = text_label(strings.MODE_FULL_DESC, muted=True)
        layout.addWidget(card(self.full, self.full_note))

        # Необязательная сверка с объявлением.
        self.listing_edit = QPlainTextEdit()
        self.listing_edit.setPlaceholderText(strings.MODE_LISTING_PLACEHOLDER)
        self.listing_edit.setMaximumHeight(110)
        self.listing_result = text_label("", muted=True)
        self.listing_clear = QPushButton(strings.MODE_LISTING_CLEAR)
        self.listing_clear.clicked.connect(self.clear_listing)
        clear_row = QHBoxLayout()
        clear_row.addWidget(self.listing_result, 1)
        clear_row.addWidget(self.listing_clear)
        clear_box = QWidget()
        clear_box.setObjectName("plainRow")  # без своего фона — на фоне карточки (theme.py)
        clear_row.setContentsMargins(0, 0, 0, 0)
        clear_box.setLayout(clear_row)
        layout.addWidget(
            card(
                title_label(strings.MODE_LISTING_TITLE),
                text_label(strings.MODE_LISTING_HINT, muted=True),
                self.listing_edit,
                clear_box,
            )
        )
        self._recognize_timer = QTimer(self)
        self._recognize_timer.setSingleShot(True)
        self._recognize_timer.setInterval(RECOGNIZE_DELAY_MS)
        self._recognize_timer.timeout.connect(self._show_recognized)
        self.listing_edit.textChanged.connect(self._recognize_timer.start)

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
        """Полная проверка доступна всем."""
        self.full.setEnabled(True)
        self.full.setText(strings.MODE_FULL)
        self.full_note.setText(strings.MODE_FULL_DESC)
        self._show_recognized()

    def _show_recognized(self) -> None:
        """Строка под полем: что распознано или почему сверять нечего."""
        text = self.listing_edit.toPlainText()
        self.listing_clear.setVisible(bool(text.strip()))
        if not text.strip():
            self.listing_result.setText("")
            return
        summary = claims_summary(listing_from_text(text))
        self.listing_result.setText(
            strings.MODE_LISTING_FOUND.format(summary=escape(summary))
            if summary
            else strings.MODE_LISTING_NOTHING
        )

    def clear_listing(self) -> None:
        """Убирает текст объявления (кнопка «Очистить» и «Новая проверка»)."""
        self.listing_edit.clear()
        self._show_recognized()

    def listing_to_use(self) -> ListingClaims | None:
        """Объявление для сверки: распознанное из вставленного текста или None."""
        return listing_from_text(self.listing_edit.toPlainText())

    def selected_mode(self) -> str:
        return "full" if self.full.isChecked() and self.full.isEnabled() else "quick"

    def _start(self) -> None:
        self.start_requested.emit(self.selected_mode())
