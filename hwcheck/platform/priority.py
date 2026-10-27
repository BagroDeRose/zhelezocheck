"""Приоритет процессов нагрузки (задача 22.7).

Процессы нагрузочных тестов работают с приоритетом «ниже обычного»: окно программы и сама
Windows получают процессор первыми, поэтому компьютер не «замирает» во время теста.
Меняется приоритет только собственного процесса программы — настройки системы не трогаются.
"""

from __future__ import annotations

import logging
import sys

import psutil

log = logging.getLogger(__name__)

POSIX_NICE = 10  # аналог «ниже обычного» на Linux/macOS (только для разработки)


def lower_own_priority(process: psutil.Process | None = None) -> bool:
    """Ставит текущему процессу приоритет «ниже обычного». False — если не удалось."""
    target = process or psutil.Process()
    try:
        if sys.platform == "win32":
            target.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            target.nice(POSIX_NICE)
    except (psutil.Error, OSError) as error:
        log.warning("Не удалось понизить приоритет процесса нагрузки: %s", error)
        return False
    return True


def load_worker_count(logical_cpus: int | None) -> int:
    """Сколько процессов нагрузки CPU запускать: все логические ядра, кроме одного.

    Одно ядро остаётся свободным для окна программы и системы — на ноутбуках с процессорами
    AMD полная загрузка всех потоков подвешивала интерфейс.
    """
    if not logical_cpus or logical_cpus < 2:
        return 1
    return logical_cpus - 1
