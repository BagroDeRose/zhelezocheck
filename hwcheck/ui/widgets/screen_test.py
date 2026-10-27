"""Окно теста экрана: заливка цветом на весь экран, переход по щелчку/клавише, Esc — выход."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QLinearGradient, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from hwcheck.laptop.screen import ScreenTest


class ScreenTestWindow(QWidget):
    finished = Signal()
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.test = ScreenTest()
        self.setWindowTitle("Тест экрана")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def next_color(self) -> None:
        self.test.advance()
        if self.test.finished:
            self.close()
            self.finished.emit()
        else:
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя метода Qt
        painter = QPainter(self)
        color = self.test.current.color
        if color is None:
            gradient = QLinearGradient(0, 0, self.width(), 0)
            gradient.setColorAt(0.0, QColor("#000000"))
            gradient.setColorAt(1.0, QColor("#ffffff"))
            painter.fillRect(self.rect(), gradient)
        else:
            painter.fillRect(self.rect(), QColor(color))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — имя метода Qt
        self.next_color()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя метода Qt
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()
        else:
            self.next_color()
