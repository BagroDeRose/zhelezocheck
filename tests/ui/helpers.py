"""Помощники тестов интерфейса: окно на фейковом бэкенде во временной папке."""

from pathlib import Path

from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import get_paths
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow

# Быстрая проверка (~570 «секунд») пройдёт примерно за 1 секунду.
TEST_TIME_SCALE = 0.002


def make_window(
    qtbot: QtBot,
    tmp_path: Path,
    scenario: str = "healthy_gaming_pc",
    demo: bool = True,
    pro: bool = True,  # оставлено для совместимости вызовов: все функции бесплатны
    time_scale: float = TEST_TIME_SCALE,
) -> tuple[MainWindow, AppContext, list[Path]]:
    opened: list[Path] = []
    ctx = AppContext.create(
        FakeBackend(scenario, time_scale=time_scale), get_paths(tmp_path), scenario if demo else ""
    )
    ctx.admin_check = lambda: False
    ctx.relaunch = lambda: False
    ctx.open_path = opened.append
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    return window, ctx, opened
