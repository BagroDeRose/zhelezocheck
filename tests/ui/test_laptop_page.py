"""Страница «Ноутбук»: тест экрана и клавиатуры (без настоящего полноэкранного режима)."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from hwcheck.laptop import screen
from hwcheck.models import Severity
from tests.ui.helpers import make_window


def test_screen_test_cycles_colors_then_asks(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="laptop_worn_battery", pro=True)
    window.go_to("laptop")
    page = window.laptop_page
    test_window = page.start_screen_test(fullscreen=False)
    qtbot.addWidget(test_window)
    assert not page.screen_question.isVisibleTo(page)
    for _ in range(len(screen.COLORS) - 1):
        QTest.mouseClick(test_window, Qt.MouseButton.LeftButton)
    QTest.keyClick(test_window, Qt.Key.Key_Space)  # последний цвет — клавишей
    assert test_window.test.finished
    assert page.screen_question.isVisibleTo(page)
    page.screen_yes.click()
    finding, _ = ctx.manual_findings["screen"]
    assert finding.severity is Severity.CRITICAL
    assert not page.screen_question.isVisibleTo(page)


def test_screen_test_escape_cancels(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.laptop_page
    test_window = page.start_screen_test(fullscreen=False)
    qtbot.addWidget(test_window)
    QTest.keyClick(test_window, Qt.Key.Key_Escape)
    assert not page.screen_question.isVisibleTo(page)
    assert "screen" not in ctx.manual_findings


def test_keyboard_highlights_and_reports_missing(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.laptop_page
    page.start_keyboard_test()
    QTest.keyClick(page.keyboard, Qt.Key.Key_Q)
    QTest.keyClick(page.keyboard, Qt.Key.Key_Space)
    assert page.keyboard.is_lit("Q") and page.keyboard.is_lit("Пробел")
    assert not page.keyboard.is_lit("W")
    page.keyboard_done.click()
    finding, bargain = ctx.manual_findings["keyboard"]
    assert finding.id == "laptop.keyboard_missing"
    assert "W" in finding.explanation and "Q," not in finding.explanation
    assert bargain


def test_manual_results_enter_next_verdict(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="laptop_worn_battery", pro=True)
    page = window.laptop_page
    test_window = page.start_screen_test(fullscreen=False)
    qtbot.addWidget(test_window)
    for _ in screen.COLORS:
        QTest.mouseClick(test_window, Qt.MouseButton.LeftButton)
    page.screen_yes.click()
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.last_session is not None and window.last_session.verdict is not None
    assert window.last_session.verdict.decision.value == "walk_away"
    assert "битые пиксели" in window.verdict_page.reasons.text()


def test_laptop_page_available_for_everyone(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=False)
    window.go_to("laptop")
    page = window.laptop_page
    # Версия 2.0: тесты ноутбука доступны всем, без ключа.
    assert page.screen_button.isEnabled() and page.keyboard_button.isEnabled()
