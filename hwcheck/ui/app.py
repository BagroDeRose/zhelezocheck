"""Создание приложения Qt: настройки, тема, главное окно."""

from __future__ import annotations

import os
import threading

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from hwcheck.backends import create_backend
from hwcheck.config import get_paths, package_data_dir
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow
from hwcheck.ui.theme import apply_theme

# В демо-режиме «секунда» теста длится 0.05 с: быстрая проверка занимает ~30 секунд.
DEMO_TIME_SCALE = 0.05


# Qt по умолчанию кэширует скомпилированные шейдеры в %LOCALAPPDATA% — программа портативная,
# поэтому кэш на диск выключаем (переменные нужно задать до создания QApplication).
NO_DISK_CACHE_ENV = ("QSG_RHI_DISABLE_DISK_CACHE", "QT_DISABLE_SHADER_DISK_CACHE")


def configure_qt_environment() -> None:
    for name in NO_DISK_CACHE_ENV:
        os.environ[name] = "1"


def ensure_application(argv: list[str] | None = None) -> QApplication:
    """Возвращает QApplication (создаёт при необходимости)."""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    configure_qt_environment()
    app = QApplication(argv or [])
    app.setApplicationName(strings.APP_NAME)
    app.setWindowIcon(QIcon(str(package_data_dir() / "icon.ico")))
    return app


def show_error_dialog(text: str) -> None:
    """Сообщение о непредвиденной ошибке (только из главного потока — окна живут в нём)."""
    if threading.current_thread() is threading.main_thread():
        QMessageBox.critical(None, strings.ERROR_TITLE, text)


def show_already_running() -> None:
    """Сообщение второй копии программы: первая уже открыта."""
    QMessageBox.information(None, strings.APP_NAME, strings.ALREADY_RUNNING)


def create_window(
    demo_scenario: str = "",
    time_scale: float = DEMO_TIME_SCALE,
    ctx: AppContext | None = None,
) -> MainWindow:
    """Главное окно с контекстом (реальный компьютер или демо-сценарий)."""
    app = ensure_application()
    if ctx is None:
        backend = create_backend(demo_scenario or None, time_scale=time_scale)
        ctx = AppContext.create(backend, get_paths(), demo_scenario)
    apply_theme(app, ctx.settings.theme)
    window = MainWindow(ctx)
    window.start_page.start_collect()
    return window
