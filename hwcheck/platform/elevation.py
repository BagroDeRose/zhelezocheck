"""Права администратора: проверить, есть ли они, и перезапустить программу с ними.

Часть проверок (S.M.A.R.T., журнал событий) требует прав администратора.
Программа не требует их при запуске, а предлагает перезапуск кнопкой —
тогда Windows сама покажет окно «Разрешить этому приложению вносить изменения?».
На других ОС функции — заглушки (нужны только для тестов и разработки).
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from typing import Any

# ShellExecute возвращает число > 32 при успехе.
_SHELL_EXECUTE_OK = 32
_SW_SHOWNORMAL = 1


def _shell32() -> Any:
    """Доступ к shell32.dll (вынесен отдельно, чтобы подменять в тестах)."""
    return ctypes.windll.shell32  # type: ignore[attr-defined]  # windll есть только на Windows


def is_admin() -> bool:
    """True, если программа запущена с правами администратора."""
    if sys.platform != "win32":
        return False
    try:
        return bool(_shell32().IsUserAnAdmin())
    except (OSError, AttributeError):
        return False


def _relaunch_parameters() -> str:
    """Аргументы для перезапуска: в сборке — только аргументы, при разработке — `-m hwcheck`."""
    args = list(sys.argv[1:])
    if not getattr(sys, "frozen", False):
        args = ["-m", "hwcheck", *args]
    return subprocess.list2cmdline(args)


def relaunch_elevated() -> bool:
    """Запускает копию программы с правами администратора. True — если запуск начался.

    Текущий экземпляр после успешного вызова нужно закрыть (это делает интерфейс).
    """
    if sys.platform != "win32":
        return False
    try:
        code = _shell32().ShellExecuteW(
            None, "runas", sys.executable, _relaunch_parameters(), None, _SW_SHOWNORMAL
        )
    except (OSError, AttributeError):
        return False
    return int(code) > _SHELL_EXECUTE_OK
