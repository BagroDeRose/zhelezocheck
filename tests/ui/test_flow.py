"""Приёмка этапа 7: полный проход «старт → быстрая проверка → вердикт → отчёт», отмена,
интерфейс не блокируется во время проверки."""

from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from pytestqt.qtbot import QtBot

from hwcheck.ui import strings
from tests.ui.helpers import make_window


@pytest.mark.parametrize(
    ("scenario", "decision"), [("healthy_gaming_pc", "buy"), ("mining_gpu", "negotiate")]
)
def test_full_flow(qtbot: QtBot, tmp_path: Path, scenario: str, decision: str) -> None:
    window, ctx, opened = make_window(qtbot, tmp_path, scenario=scenario)
    assert window.current_page_name() == "start"
    window.start_page.next_button.click()
    assert window.current_page_name() == "mode"
    window.mode_page.quick.setChecked(True)
    window.mode_page.start_button.click()
    assert window.current_page_name() == "progress"
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert strings.DECISION_TITLES[decision].upper() in window.verdict_page.banner.text()
    window.verdict_page.save_button.click()
    window.verdict_page.open_button.click()
    assert len(opened) == 1 and opened[0].suffix == ".html"
    assert strings.DECISION_TITLES[decision].upper() in opened[0].read_text(encoding="utf-8")
    window.verdict_page.new_button.click()
    assert window.current_page_name() == "start"


def test_gui_not_blocked_during_check(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, time_scale=0.004)
    ticks: list[int] = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(window.progress_page.bar.value()))
    timer.start(20)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    timer.stop()
    during = [value for value in ticks if 0 < value < 1000]
    assert len(during) >= 5, "таймер событий должен тикать, пока идёт проверка"


def test_cancel_in_the_middle(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, scenario="mining_gpu", time_scale=0.05)
    window.start_page.next_button.click()
    window.mode_page.start_button.click()
    qtbot.waitUntil(lambda: window.progress_page.bar.value() > 300, timeout=20000)
    window.progress_page.stop_button.click()
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=4000)
    session = window.last_session
    assert session is not None
    statuses = [result.status.value for result in session.results]
    assert "skipped" in statuses
    assert window.verdict_page.stopped_label.isVisibleTo(window.verdict_page)
