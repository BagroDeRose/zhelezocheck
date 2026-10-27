"""Схема клавиатуры, на которой подсвечиваются нажатые клавиши (задачи 15.11, 25.1, 25.2).

Схема рисуется сама, в фиксированных пропорциях: клавиши раскладываются по «единицам»
ширины (обычная клавиша — 1, пробел — 6), масштаб подбирается под ширину виджета, высота
следует за шириной. Поэтому клавиши не наезжают друг на друга ни при каком размере окна и
масштабе Windows; список ненажатых клавиш живёт отдельно и схему не сдвигает.

Особенности Windows:
- правые Ctrl и Alt приходят с тем же скан-кодом, что и левые; отличить их можно по флагу
  «расширенной клавиши», который Qt передаёт в `nativeModifiers()`;
- Alt+F4 Qt отдаёт системе без события клавиши, и окно закрылось бы. Во время теста его
  перехватывает `ui/keyboard_guard.py` и засчитывает F4 через `press_native()`; любое другое
  закрытие окна во время теста требует подтверждения (`MainWindow.closeEvent`);
- клавиша Win открывает меню «Пуск» — заблокировать это без системного перехватчика
  клавиатуры нельзя (решение — в docs/DECISIONS.md). Win помечена «проверяется отдельно»,
  а после неё программа возвращает себе фокус, как только окно снова станет активным.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from hwcheck.laptop.keyboard import LAYOUT, KeyboardTest, KeyDef

# Qt под Windows: флаг «расширенной» клавиши в nativeModifiers (правые Ctrl/Alt, стрелки…).
EXTENDED_KEY_FLAG = 0x01000000
ALT_F4_WINDOW_S = 1.0  # сколько секунд после Alt+F4 окно отказывается закрываться
GAP = 0.1  # зазор между клавишами, в долях обычной клавиши
ROW_UNITS = max(sum(key.width for key in row) for row in LAYOUT)  # ширина схемы, в клавишах
ROWS = len(LAYOUT)
MIN_KEY_PX = 22  # меньше клавиша нечитаема
MAX_KEY_PX = 46  # больше — схема не помещается на экран 1280×720 вместе с итогом
LIT_COLOR = QColor("#2e9d52")
SEPARATE_COLOR = QColor("#8a8f98")


def key_rects(width: float, height: float) -> dict[str, QRectF]:
    """Прямоугольники клавиш для области `width` × `height` (пропорции сохраняются).

    Схема вписывается целиком и центрируется; между клавишами — зазор, поэтому
    прямоугольники соседних клавиш не пересекаются.
    """
    unit = max(1.0, min(width / ROW_UNITS, height / ROWS))
    left = (width - unit * ROW_UNITS) / 2
    top = (height - unit * ROWS) / 2
    gap = unit * GAP
    rects: dict[str, QRectF] = {}
    for row_index, row in enumerate(LAYOUT):
        x = left
        for key in row:
            rects[key.label] = QRectF(
                x + gap / 2, top + row_index * unit + gap / 2, key.width * unit - gap, unit - gap
            )
            x += key.width * unit
    return rects


def overlapping_keys(rects: dict[str, QRectF]) -> list[tuple[str, str]]:
    """Пары клавиш, которые наезжают друг на друга (должен быть пустой список)."""
    items = list(rects.items())
    return [
        (a_name, b_name)
        for index, (a_name, a) in enumerate(items)
        for b_name, b in items[index + 1 :]
        if a.intersects(b)
    ]


class KeyboardView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.test = KeyboardTest()
        self.running = False  # идёт тест: закрытие окна требует подтверждения (25.1)
        self.alt_f4_at = float("-inf")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumSize(int(ROW_UNITS * MIN_KEY_PX), int(ROWS * MIN_KEY_PX))
        # Схема и итог помещаются в окно 1280×720 целиком; на большом мониторе не раздуваются.
        self.setMaximumHeight(int(ROWS * MAX_KEY_PX))
        self.keys: dict[str, KeyDef] = {key.label: key for row in LAYOUT for key in row}

    # -- размеры: высота следует за шириной ------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — имя метода Qt
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — имя метода Qt
        return min(self.maximumHeight(), max(self.minimumHeight(), round(width * ROWS / ROW_UNITS)))

    def sizeHint(self) -> QSize:  # noqa: N802 — имя метода Qt
        return QSize(int(ROW_UNITS * 48), int(ROWS * 48))

    def key_rects(self) -> dict[str, QRectF]:
        return key_rects(self.width(), self.height())

    # -- состояние теста ---------------------------------------------------------

    def start(self) -> None:
        self.reset()
        self.running = True
        self.setFocus()

    def stop(self) -> None:
        self.running = False

    def reset(self) -> None:
        self.test = KeyboardTest()
        self.running = False
        self.update()

    def is_lit(self, label: str) -> bool:
        return self.keys[label].scan in self.test.pressed

    def press_native(self, scan: int, qt_key: int) -> None:
        """Нажатие, которое Windows не передала в Qt (Alt+F4) — засчитать вручную."""
        if qt_key == int(Qt.Key.Key_F4):
            self.alt_f4_at = time.monotonic()
        if self.test.press(scan, qt_key) is not None:
            self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя метода Qt
        scan = event.nativeScanCode()
        if scan and scan < 0x100 and event.nativeModifiers() & EXTENDED_KEY_FLAG:
            scan |= 0x100  # правые Ctrl/Alt — «расширенные» варианты левых
        if event.key() == Qt.Key.Key_F4 and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.alt_f4_at = time.monotonic()
        if self.test.press(scan, event.key()) is not None:
            self.update()
        event.accept()

    def alt_f4_recent(self) -> bool:
        """Только что нажимали Alt+F4 в тесте — окно закрывать не нужно."""
        return time.monotonic() - self.alt_f4_at < ALT_F4_WINDOW_S

    def event(self, event: QEvent) -> bool:
        # Нажатие Win уводит фокус в меню «Пуск»; когда окно снова активно — забираем фокус.
        if event.type() == QEvent.Type.WindowActivate and self.isEnabled() and self.running:
            self.setFocus()
        return super().event(event)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: N802, A002 — имя метода Qt
        return False  # Tab — тоже клавиша теста, фокус не должен уходить

    # -- рисование ---------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя метода Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().windowText().color()
        rects = self.key_rects()
        unit = min(rect.height() for rect in rects.values()) if rects else 20.0
        font = QFont(self.font())
        font.setPixelSize(max(9, round(unit * 0.36)))
        painter.setFont(font)
        for label, rect in rects.items():
            key = self.keys[label]
            radius = unit * 0.15
            if self.is_lit(label):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(LIT_COLOR)
                painter.drawRoundedRect(rect, radius, radius)
                painter.setPen(QColor("white"))
            elif key.separate:
                pen = QPen(SEPARATE_COLOR, 1, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, radius, radius)
                painter.setPen(SEPARATE_COLOR)
            else:
                painter.setPen(QPen(QColor("#888888"), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, radius, radius)
                painter.setPen(text_color)
            text = painter.fontMetrics().elidedText(
                label.strip(), Qt.TextElideMode.ElideRight, int(rect.width() - 4)
            )
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
