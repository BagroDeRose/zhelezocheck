"""Страница «Прогресс»: общий прогресс, текущий шаг, живые графики, кнопка «Остановить»."""

from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hwcheck.models import SensorSample, TestResult
from hwcheck.ui import strings
from hwcheck.ui.pages.common import card, text_label, title_label
from hwcheck.ui.widgets.chart import LiveChart

PROGRESS_STEPS = 1000


def remaining_seconds(
    elapsed: float, fraction: float, planned_total_s: float = 0.0
) -> float | None:
    """Сколько секунд осталось. None — пока оценить нельзя.

    Если известна плановая длительность проверки, считаем по плану: доля прогресса уже
    взвешена по длительностям шагов, поэтому остаток = план × (1 − доля). Пересчёт по
    прошедшему времени в начале проверки сильно ошибается (замечание 15.10) и остаётся
    только запасным вариантом.
    """
    if planned_total_s > 0:
        return max(0.0, planned_total_s * (1 - fraction))
    if fraction < 0.02 or elapsed < 1:
        return None
    return max(0.0, elapsed * (1 - fraction) / fraction)


def format_remaining(seconds: float | None) -> str:
    if seconds is None:
        return strings.PROGRESS_REMAINING_UNKNOWN
    whole = int(seconds)
    return strings.PROGRESS_REMAINING.format(minutes=whole // 60, seconds=whole % 60)


def remaining_text(elapsed: float, fraction: float, planned_total_s: float = 0.0) -> str:
    """Оценка оставшегося времени текстом."""
    return format_remaining(remaining_seconds(elapsed, fraction, planned_total_s))


class ProgressPage(QWidget):
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.started_at = time.monotonic()
        self.planned_total_s = 0.0
        self.shown_remaining: float | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(title_label(strings.PROGRESS_TITLE))
        self.bar = QProgressBar()
        self.bar.setRange(0, PROGRESS_STEPS)
        layout.addWidget(self.bar)
        self.step_label = text_label("")
        self.remaining_label = text_label(strings.PROGRESS_REMAINING_UNKNOWN, muted=True)
        layout.addWidget(self.step_label)
        layout.addWidget(self.remaining_label)

        self.gpu_chart = LiveChart(strings.CHART_GPU_TEMP, "#d93025")
        self.cpu_chart = LiveChart(strings.CHART_CPU_CLOCK, "#4a6fd1")
        self.gpu_chart_card = card(self.gpu_chart)
        self.cpu_chart_card = card(self.cpu_chart)
        charts = QHBoxLayout()
        charts.addWidget(self.gpu_chart_card)
        charts.addWidget(self.cpu_chart_card)
        layout.addLayout(charts)
        # Текущие значения на случай, если графики скрыты.
        self.now_label = text_label("")
        layout.addWidget(self.now_label)
        self.now_values: dict[str, str] = {}
        self.set_charts_allowed(True)

        self.log = QListWidget()
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop_button = QPushButton(strings.PROGRESS_STOP)
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

    def begin(self, planned_total_s: float = 0.0) -> None:
        """Новая проверка. `planned_total_s` — плановая длительность в реальных секундах."""
        self.started_at = time.monotonic()
        self.planned_total_s = planned_total_s
        self.shown_remaining = None
        self.bar.setValue(0)
        self.step_label.setText("")
        self.remaining_label.setText(strings.PROGRESS_REMAINING_UNKNOWN)
        self.gpu_chart.clear()
        self.cpu_chart.clear()
        self.now_values = {}
        self.now_label.setText("")
        self.log.clear()
        self.stop_button.setEnabled(True)
        self.stop_button.setText(strings.PROGRESS_STOP)

    def on_progress(self, fraction: float, step: str) -> None:
        self.bar.setValue(int(fraction * PROGRESS_STEPS))
        self.step_label.setText(
            strings.PROGRESS_STEP.format(step=strings.TEST_NAMES.get(step, step))
        )
        estimate = remaining_seconds(
            time.monotonic() - self.started_at, fraction, self.planned_total_s
        )
        if estimate is not None and self.shown_remaining is not None:
            estimate = min(estimate, self.shown_remaining)  # оценка не растёт
        if estimate is not None:
            self.shown_remaining = estimate
        self.remaining_label.setText(format_remaining(estimate))

    def on_sample(self, step: str, sample: SensorSample) -> None:
        # По оси X — время от начала всей проверки (у каждого теста своё время начинается с 0).
        elapsed = time.monotonic() - self.started_at
        if sample.component.startswith("gpu") and sample.values.get("temp_c") is not None:
            temp = float(sample.values["temp_c"] or 0)
            self.gpu_chart.add_point(elapsed, temp)
            self.now_values["gpu"] = f"видеокарта {temp:.0f} °C"
        if sample.component == "cpu" and sample.values.get("clock_mhz") is not None:
            clock = float(sample.values["clock_mhz"] or 0)
            self.cpu_chart.add_point(elapsed, clock)
            self.now_values["cpu"] = f"процессор {clock / 1000:.2f} ГГц"
        if self.now_values and not self.charts_allowed:
            values = ", ".join(self.now_values[key] for key in sorted(self.now_values))
            self.now_label.setText(strings.PROGRESS_NOW.format(values=values))

    def set_charts_allowed(self, allowed: bool) -> None:
        """Графики доступны всем; метод оставлен для совместимости вызова из окна."""
        self.charts_allowed = allowed
        self.gpu_chart_card.setVisible(allowed)
        self.cpu_chart_card.setVisible(allowed)
        self.now_label.setVisible(not allowed)

    def on_step_done(self, result: TestResult) -> None:
        self.log.addItem(
            strings.STEP_DONE.format(
                test=strings.TEST_NAMES.get(result.name, result.name),
                status=strings.STATUS_NAMES.get(result.status.value, result.status.value),
            )
        )

    def _stop(self) -> None:
        self.stop_button.setEnabled(False)
        self.stop_button.setText(strings.PROGRESS_STOPPING)
        self.stop_requested.emit()
