"""Тест клавиатуры ноутбука: закрытие окна (25.1) и геометрия схемы (25.2)."""

from itertools import combinations
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from hwcheck.laptop.keyboard import LAYOUT, KeyboardTest
from hwcheck.ui import keyboard_guard
from hwcheck.ui.pages.laptop import RESULT_MAX_HEIGHT
from hwcheck.ui.widgets.keyboard_view import KeyboardView, key_rects
from tests.ui.helpers import make_window

# ---------------------------------------------------------------- 25.1 закрытие окна


def test_alt_f4_message_is_counted_and_blocked() -> None:
    lparam = keyboard_guard.ALT_CONTEXT | (0x3E << 16) | 1
    decision = keyboard_guard.decide(keyboard_guard.WM_SYSKEYDOWN, keyboard_guard.VK_F4, lparam)
    assert decision.block and decision.scan == 0x3E and decision.qt_key == int(Qt.Key.Key_F4)


@pytest.mark.parametrize(
    "wparam", [0xF100, 0xF100 | 0x2]
)  # Alt, F10, Alt+Space (младшие биты — служебные)
def test_system_menu_is_blocked(wparam: int) -> None:
    assert keyboard_guard.decide(keyboard_guard.WM_SYSCOMMAND, wparam, 0).block


def test_other_messages_pass() -> None:
    assert not keyboard_guard.decide(keyboard_guard.WM_SYSCOMMAND, 0xF060, 0).block  # SC_CLOSE
    assert not keyboard_guard.decide(keyboard_guard.WM_SYSKEYDOWN, keyboard_guard.VK_F4, 0).block


def test_guard_works_only_during_test(qtbot: QtBot) -> None:
    view = KeyboardView()
    qtbot.addWidget(view)
    guard = keyboard_guard.KeyboardGuard(view)
    lparam = keyboard_guard.ALT_CONTEXT | (0x3E << 16)
    assert not guard.apply(keyboard_guard.WM_SYSKEYDOWN, keyboard_guard.VK_F4, lparam)
    assert not view.is_lit("F4")
    view.start()
    assert guard.apply(keyboard_guard.WM_SYSKEYDOWN, keyboard_guard.VK_F4, lparam)
    assert view.is_lit("F4") and view.alt_f4_recent()


def test_close_during_keyboard_test_asks_and_stays(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    asked: list[str] = []
    window.confirm = lambda _title, text: asked.append(text) is not None and False  # «Нет»
    window.show()
    window.laptop_page.start_keyboard_test()
    window.close()  # кнопка «×», Alt+F4 без события клавиши и т.п.
    assert window.isVisible() and asked
    assert window.laptop_page.keyboard.running


def test_close_confirmed_during_keyboard_test(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    window.confirm = lambda _title, _text: True  # «Да, прервать»
    window.show()
    window.laptop_page.start_keyboard_test()
    window.close()
    assert not window.isVisible()


def test_close_without_test_does_not_ask(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    window.confirm = lambda _title, _text: pytest.fail("вопрос без теста не нужен")
    window.show()
    window.close()
    assert not window.isVisible()


def test_finish_button_stops_test(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    page = window.laptop_page
    page.start_keyboard_test()
    assert page.keyboard.running
    page.keyboard_done.click()
    assert not page.keyboard.running


def test_win_key_is_checked_separately() -> None:
    win = next(key for row in LAYOUT for key in row if key.label == "Win")
    assert win.separate
    assert "Win" not in [key.label for key in KeyboardTest().missing()]


# ---------------------------------------------------------------- 25.2 геометрия схемы


def _assert_no_overlaps(rects: dict, width: float, height: float) -> None:
    for (a_name, a), (b_name, b) in combinations(rects.items(), 2):
        assert not a.intersects(b), f"{a_name!r} наезжает на {b_name!r}"
    for name, rect in rects.items():
        assert rect.left() >= 0 and rect.top() >= 0, name
        assert rect.right() <= width + 0.01 and rect.bottom() <= height + 0.01, name


@pytest.mark.parametrize(("width", "height"), [(300, 80), (700, 200), (1500, 300), (900, 900)])
def test_key_rects_never_overlap(width: int, height: int) -> None:
    _assert_no_overlaps(key_rects(width, height), width, height)


# Окно программы на экранах 1280×720, 1366×768, 1920×1080; 150 % масштаба Windows —
# это те же экраны с логическим размером в 1,5 раза меньше.
SCREENS = [(1280, 720, 1.0), (1366, 768, 1.0), (1920, 1080, 1.0), (1920, 1080, 1.5)]


@pytest.mark.parametrize(("width", "height", "scale"), SCREENS)
def test_keyboard_fits_window_without_overlaps(
    qtbot: QtBot, tmp_path: Path, width: int, height: int, scale: float
) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    window.resize(int(width / scale), int(height / scale) - 40)  # минус заголовок окна
    window.show()
    window.go_to("laptop")
    page = window.laptop_page
    page.start_keyboard_test()
    qtbot.wait(50)
    view = page.keyboard
    top_before = view.mapTo(page, view.rect().topLeft()).y()
    _assert_no_overlaps(view.key_rects(), view.width(), view.height())
    min_key = min(rect.height() for rect in view.key_rects().values())
    assert min_key >= 18, "клавиши должны оставаться читаемыми"
    # Длинный итог «не нажимались: …» не сдвигает и не сжимает схему.
    page.keyboard_done.click()
    qtbot.wait(50)
    assert page.keyboard_result.text()
    assert view.mapTo(page, view.rect().topLeft()).y() == top_before
    assert page.keyboard_result_area.height() <= RESULT_MAX_HEIGHT
    _assert_no_overlaps(view.key_rects(), view.width(), view.height())
    # Схема и итог видны целиком без прокрутки: страница сама прокрутилась к тесту.
    viewport = page.scroll_area.viewport()
    for widget in (view, page.keyboard_result_area):
        top_left = widget.mapTo(viewport, widget.rect().topLeft())
        bottom = top_left.y() + widget.height()
        assert top_left.y() >= 0 and bottom <= viewport.height(), type(widget).__name__


def test_missing_list_names_right_keys() -> None:
    from hwcheck.laptop.keyboard import display_name

    names = [display_name(key) for key in KeyboardTest().missing()]
    assert "Alt (правый)" in names and "Alt" in names and "Ctrl (правый)" in names
