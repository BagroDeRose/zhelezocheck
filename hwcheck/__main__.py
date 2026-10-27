"""Запуск графического интерфейса: `python -m hwcheck [--demo [СЦЕНАРИЙ]]`.

Без аргументов — проверка этого компьютера.
`--demo` — демо-режим на «компьютере понарошку» (по умолчанию healthy_gaming_pc),
ничего не нагружает и показывает, как выглядит программа.
`--demo --smoke-test` — самопроверка сборки: демо-проверка до вердикта и отчёта, затем выход.
Программа бесплатная и открытая (версия 2.0): все функции доступны всем, без ключей и активации.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hwcheck.models import TestResult

DEFAULT_DEMO = "healthy_gaming_pc"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hwcheck", description="ЖелезоЧек")
    parser.add_argument(
        "--demo",
        nargs="?",
        const=DEFAULT_DEMO,
        default="",
        metavar="СЦЕНАРИЙ",
        help="демо-режим без реального железа",
    )
    parser.add_argument("--time-scale", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--smoke-test", action="store_true", help="самопроверка сборки (только с --demo)"
    )
    return parser.parse_args(argv)


def _frozen_worker_check() -> Callable[[], TestResult] | None:
    """В собранной программе — 3 секунды настоящей нагрузки CPU двумя процессами."""
    if not getattr(sys, "frozen", False):
        return None
    import threading

    from hwcheck.stress.cpu_load import run_cpu_load

    return lambda: run_cpu_load(3, threading.Event(), worker_count=2, use_sensors=False)


def main(argv: list[str] | None = None) -> int:
    # Нужно для дочерних процессов нагрузки в собранной программе (PyInstaller).
    multiprocessing.freeze_support()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from hwcheck.backends.fake import list_scenarios
    from hwcheck.config import get_paths
    from hwcheck.logging_setup import setup_logging
    from hwcheck.ui.app import DEMO_TIME_SCALE, create_window, ensure_application

    if args.demo and args.demo not in list_scenarios():
        print(f"Неизвестный сценарий «{args.demo}». Доступны: {', '.join(list_scenarios())}")
        return 2
    from hwcheck import crash_guard
    from hwcheck.ui.app import show_error_dialog

    paths = get_paths()
    setup_logging(paths)
    app = ensure_application(sys.argv)
    # Необработанная ошибка — в журнал и сообщение пользователю, а не молчаливое закрытие.
    # В самопроверке сборки окно с сообщением заблокировало бы выход, поэтому только журнал.
    crash_guard.install(paths, notify=None if args.smoke_test else show_error_dialog)
    # Вторая копия программы с той же флешки не запускается (20.3).
    from hwcheck.single_instance import InstanceLock
    from hwcheck.ui.app import show_already_running

    instance = InstanceLock(paths.data / "hwcheck.lock")
    if not instance.acquire():
        show_already_running()
        return 1
    time_scale = args.time_scale if args.time_scale is not None else DEMO_TIME_SCALE
    if args.smoke_test:
        if not args.demo:
            print("--smoke-test работает только вместе с --demo")
            return 2
        from hwcheck.ui.smoke import run_smoke_test

        window = create_window(args.demo, time_scale=0.002)
        window.show()
        return run_smoke_test(window, worker_check=_frozen_worker_check())
    from hwcheck.ui.watchdog import UiWatchdog

    started = time.monotonic()
    window = create_window(args.demo, time_scale=time_scale)
    window.show()
    logging.getLogger(__name__).info("Окно открыто за %.1f с", time.monotonic() - started)
    watchdog = UiWatchdog()  # подвисания окна дольше 2 с — в журнал (задача 22.7)
    watchdog.start()
    code = app.exec()
    watchdog.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
