"""Страница «Ноутбук» (Pro): тест экрана и тест клавиатуры.

Ответы пользователя превращаются в находки и запоминаются в контексте программы —
они войдут в вердикт следующей проверки.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwcheck.laptop.screen import screen_finding
from hwcheck.laptop.texts import ManualResult
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label
from hwcheck.ui.widgets.keyboard_view import KeyboardView
from hwcheck.ui.widgets.screen_test import ScreenTestWindow

RESULT_MAX_HEIGHT = 110  # px: итог теста клавиатуры не выталкивает схему


class LaptopPage(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.screen_window: ScreenTestWindow | None = None
        # Страница прокручивается: на окне 1280×720 схема клавиатуры не сжимается (25.2).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll_area)
        body = QWidget()
        self.scroll_area.setWidget(body)
        layout = QVBoxLayout(body)
        layout.addWidget(title_label(strings.LAPTOP_TITLE))
        layout.addWidget(text_label(strings.LAPTOP_INTRO, muted=True))

        self.screen_button = QPushButton(strings.SCREEN_START)
        self.screen_button.clicked.connect(lambda: self.start_screen_test())
        self.screen_yes = QPushButton(strings.SCREEN_YES)
        self.screen_no = QPushButton(strings.SCREEN_NO)
        self.screen_yes.clicked.connect(lambda: self._screen_answer(True))
        self.screen_no.clicked.connect(lambda: self._screen_answer(False))
        self.screen_question = QWidget()
        question = QHBoxLayout(self.screen_question)
        question.addWidget(text_label(strings.SCREEN_QUESTION))
        question.addWidget(self.screen_yes)
        question.addWidget(self.screen_no)
        self.screen_question.setVisible(False)
        self.screen_result = text_label("")
        layout.addWidget(
            card(
                title_label(strings.SCREEN_TITLE),
                text_label(strings.SCREEN_HINT, muted=True),
                self.screen_button,
                self.screen_question,
                self.screen_result,
            )
        )

        self.keyboard_button = QPushButton(strings.KEYBOARD_START)
        self.keyboard_button.clicked.connect(lambda: self.start_keyboard_test())
        self.keyboard = KeyboardView()
        self.keyboard_done = QPushButton(strings.KEYBOARD_DONE)
        self.keyboard_done.clicked.connect(lambda: self._keyboard_finished())
        self.keyboard_result = text_label("")
        # Итог («не нажимались: …») — в своей прокручиваемой области ограниченной высоты:
        # длинный список не выталкивает схему (25.2).
        self.keyboard_result_area = QScrollArea()
        self.keyboard_result_area.setWidgetResizable(True)
        self.keyboard_result_area.setFrameShape(QFrame.Shape.NoFrame)
        self.keyboard_result_area.setMaximumHeight(RESULT_MAX_HEIGHT)
        self.keyboard_result_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.keyboard_result_area.setWidget(self.keyboard_result)
        buttons = QHBoxLayout()
        buttons.addWidget(self.keyboard_button)
        buttons.addWidget(self.keyboard_done)
        buttons.addStretch(1)
        buttons_row = QWidget()
        buttons_row.setLayout(buttons)
        self.keyboard_card = card(
            title_label(strings.KEYBOARD_TITLE),
            text_label(strings.KEYBOARD_HINT, muted=True),
            text_label(strings.KEYBOARD_SEPARATE, muted=True),
            buttons_row,
            self.keyboard,
            self.keyboard_result_area,
        )
        layout.addWidget(self.keyboard_card)
        layout.addStretch(1)
        self.status = text_label("", muted=True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        for widget in (self.screen_button, self.keyboard_button, self.keyboard_done):
            widget.setEnabled(True)
        self.keyboard.setEnabled(True)
        self.status.setText("")

    def clear_results(self) -> None:
        self.screen_result.setText("")
        self.keyboard_result.setText("")
        self.screen_question.setVisible(False)
        self.keyboard.reset()

    # -- экран -----------------------------------------------------------------

    def start_screen_test(self, fullscreen: bool = True) -> ScreenTestWindow:
        window = ScreenTestWindow()
        window.finished.connect(lambda: self.screen_question.setVisible(True))
        self.screen_window = window
        if fullscreen:
            window.showFullScreen()
            window.activateWindow()
        return window

    def _screen_answer(self, defects: bool) -> None:
        self.screen_question.setVisible(False)
        self._remember("screen", self.screen_result, screen_finding(defects))

    # -- клавиатура ----------------------------------------------------------

    def start_keyboard_test(self) -> None:
        self.keyboard_result.setText("")
        self.keyboard.start()
        # Схема — сразу перед глазами, даже на небольшом экране (25.2).
        self.scroll_area.verticalScrollBar().setValue(self.keyboard_card.y())

    def _keyboard_finished(self) -> None:
        self.keyboard.stop()
        self._remember("keyboard", self.keyboard_result, self.keyboard.test.finding())

    def _remember(self, key: str, label: QLabel, result: ManualResult) -> None:
        self.ctx.manual_findings[key] = result
        finding = result[0]
        text = strings.LAPTOP_RESULT.format(title=escape(finding.title))
        if finding.explanation:
            text += "<br>" + escape(finding.explanation)
        label.setText(text)
