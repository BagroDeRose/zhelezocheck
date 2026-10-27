"""Перехват необработанных ошибок: программа не закрывается молча (задача 15.6).

Что делает `install()`:
- любая необработанная ошибка в главном потоке (в том числе в обработчиках кнопок Qt)
  записывается в журнал `data/logs/hwcheck.log`, а пользователь видит понятное сообщение;
- ошибка в фоновом потоке тоже записывается в журнал;
- если программа всё-таки «вылетела» на уровне Windows/Qt (а не Python), модуль
  `faulthandler` успевает записать, где это случилось, в `data/logs/crash.log`.

Журналы лежат в папке программы — по ним можно понять причину сбоя на чужом компьютере.
"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import TextIO

from hwcheck.config import AppPaths
from hwcheck.logging_setup import LOG_FILE_NAME

log = logging.getLogger(__name__)

CRASH_FILE_NAME = "crash.log"

_crash_file: TextIO | None = None


def error_message(paths: AppPaths) -> str:
    """Текст для пользователя: что случилось и где искать подробности."""
    return (
        "Произошла непредвиденная ошибка. Программа продолжает работу, но результат "
        "текущего действия может быть неполным.\n\n"
        f"Подробности записаны в журнал: {paths.logs / LOG_FILE_NAME}\n"
        "Пришлите этот файл разработчику — так ошибку найдут быстрее."
    )


def install(
    paths: AppPaths,
    notify: Callable[[str], None] | None = None,
    enable_faulthandler: bool = True,
) -> None:
    """Подключает перехват ошибок. `notify` показывает сообщение пользователю."""
    message = error_message(paths)

    def on_main_error(
        exc_type: type[BaseException], error: BaseException, tb: TracebackType | None
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, error, tb)
            return
        log.error("Необработанная ошибка", exc_info=(exc_type, error, tb))
        if notify is not None:
            try:
                notify(message)
            except Exception:  # окно сообщения недоступно — ошибка уже в журнале
                log.exception("Не удалось показать сообщение об ошибке")

    def on_thread_error(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        name = args.thread.name if args.thread is not None else "?"
        log.error(
            "Необработанная ошибка в потоке %s",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = on_main_error
    threading.excepthook = on_thread_error
    if enable_faulthandler:
        _enable_faulthandler(paths)


def _enable_faulthandler(paths: AppPaths) -> None:
    global _crash_file
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        # Файл держим открытым всё время работы: при «вылете» писать будет уже некогда.
        _crash_file = open(paths.logs / CRASH_FILE_NAME, "a", encoding="utf-8")
    except OSError:  # флешка защищена от записи — работаем без файла
        log.warning("Не удалось открыть %s", CRASH_FILE_NAME)
        return
    faulthandler.enable(file=_crash_file)


def close() -> None:
    """Отключает запись «вылетов» и закрывает файл (для тестов и выхода)."""
    global _crash_file
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None
