"""Простой живой график (линия) на QPainter — для температуры и частоты во время проверки."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


class LiveChart(QWidget):
    """Линейный график, точки добавляются по мере поступления замеров."""

    def __init__(self, title: str, color: str = "#d93025", max_points: int = 600) -> None:
        super().__init__()
        self.title = title
        self.color = QColor(color)
        self.max_points = max_points
        self.points: list[tuple[float, float]] = []
        self.setMinimumHeight(140)

    def clear(self) -> None:
        self.points.clear()
        self.update()

    def add_point(self, t: float, value: float) -> None:
        self.points.append((t, value))
        if len(self.points) > self.max_points:
            self.points = self.points[-self.max_points :]
        self.update()

    def last_value(self) -> float | None:
        return self.points[-1][1] if self.points else None

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — имя метода Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(44, 22, -10, -10)
        text_color = self.palette().windowText().color()
        painter.setPen(text_color)
        last = self.last_value()
        caption = self.title + (f": {last:.0f}" if last is not None else "")
        painter.drawText(8, 16, caption)
        painter.setPen(QPen(QColor("#999999"), 1))
        painter.drawRect(rect)
        if len(self.points) < 2:
            painter.end()
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if y_max - y_min < 1:
            y_min, y_max = y_min - 1, y_max + 1
        painter.setPen(text_color)
        painter.drawText(4, rect.top() + 10, f"{y_max:.0f}")
        painter.drawText(4, rect.bottom(), f"{y_min:.0f}")

        def point(x: float, y: float) -> QPointF:
            px = rect.left() + (x - x_min) / ((x_max - x_min) or 1) * rect.width()
            py = rect.bottom() - (y - y_min) / (y_max - y_min) * rect.height()
            return QPointF(px, py)

        painter.setPen(QPen(self.color, 2, Qt.PenStyle.SolidLine))
        for (x1, y1), (x2, y2) in zip(self.points, self.points[1:], strict=False):
            painter.drawLine(point(x1, y1), point(x2, y2))
        painter.end()
