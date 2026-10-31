"""Права администратора: проверить, есть ли они, и перезапустить программу с ними.

Часть проверок (S.M.A.R.T., журнал событий) требует прав администратора.
Программа не требует их при запуске, а предлагает перезапуск кнопкой —
тогда Windows сама покажет окно «Разрешить этому приложению вносить изменения?».

Перезапуск идёт через ShellExecuteEx: так программа получает дескриптор новой копии и может
убедиться, что та действительно запустилась (а если копия сразу закрылась — остаться открытой,
сообщить об этом и записать код выхода в журнал, а не «молча исчезнуть»).
На других ОС функции — заглушки (нужны только для тестов и разработки).
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from typing import Any, Protocol

log = logging.getLogger(__name__)

_SW_SHOWNORMAL = 1
_SEE_MASK_NOCLOSEPROCESS = 0x00000040  # вернуть дескриптор запущенного процесса
_SEE_MASK_NOASYNC = 0x00000100  # дождаться, пока запуск завершится (вызывающий может закрыться)
_WAIT_OBJECT_0 = 0
_ERROR_CANCELLED = 1223  # пользователь нажал «Нет» в окне UAC
_ASFW_ANY = 0xFFFFFFFF  # AllowSetForegroundWindow: любой процесс может вывести окно вперёд

# Аргумент копии с правами и одноразовый ключ после него: копия пишет ключ в отметку «готова»,
# и старое окно узнаёт, что готова именно она. Номер процесса для этого не годится: при
# разработке python.exe из .venv — «запускалка», настоящий Python работает другим процессом.
RELAUNCH_FLAG = "--relaunched"


class ElevatedProcess(Protocol):
    """Запущенная копия программы с правами администратора."""

    pid: int  # номер процесса — только для журнала (0 — неизвестен)

    def poll(self) -> int | None:
        """None — копия работает; число — копия уже закрылась с этим кодом выхода."""
        ...

    def close(self) -> None:
        """Освободить дескриптор (саму копию не закрывает)."""
        ...


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


def _relaunch_parameters(token: str) -> str:
    """Аргументы для перезапуска: в сборке — только аргументы, при разработке — `-m hwcheck`.
    В конце — `--relaunched <ключ>` (старая пара, если копию перезапускают снова, убирается)."""
    args: list[str] = []
    skip_value = False
    for arg in sys.argv[1:]:
        if skip_value:
            skip_value = False
        elif arg == RELAUNCH_FLAG:
            skip_value = True
        else:
            args.append(arg)
    args += [RELAUNCH_FLAG, token]
    if not getattr(sys, "frozen", False):
        args = ["-m", "hwcheck", *args]
    return subprocess.list2cmdline(args)


def _program_dir() -> str:
    """Папка программы: копия с правами стартует в ней, а не в C:\\Windows\\System32."""
    from hwcheck.config import get_paths

    return str(get_paths().root)


def _shell_execute_ex(
    verb: str, file: str, parameters: str, directory: str, show: int = _SW_SHOWNORMAL
) -> int | None:
    """ShellExecuteExW: дескриптор запущенного процесса или None (отказ, ошибка)."""
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(ShellExecuteInfo)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_NOASYNC
    info.lpVerb = verb
    info.lpFile = file
    info.lpParameters = parameters
    info.lpDirectory = directory
    info.nShow = show
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == _ERROR_CANCELLED:
            log.info("Запуск «%s» отменён пользователем (окно UAC)", verb)
        else:
            log.warning("ShellExecuteEx «%s» не удался: ошибка Windows %s", verb, error)
        return None
    if not info.hProcess:
        log.warning("ShellExecuteEx «%s»: процесс запущен, но дескриптора нет", verb)
        return None
    return int(info.hProcess)


class WindowsProcess:
    """Дескриптор процесса Windows: жив ли он и с каким кодом закрылся."""

    def __init__(self, handle: int) -> None:
        from ctypes import wintypes

        self.handle: int | None = handle
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
        kernel32.GetProcessId.restype = wintypes.DWORD
        self._kernel32 = kernel32
        self.pid = int(kernel32.GetProcessId(handle))

    def poll(self) -> int | None:
        if self.handle is None:
            return None
        from ctypes import wintypes

        if self._kernel32.WaitForSingleObject(self.handle, 0) != _WAIT_OBJECT_0:
            return None  # процесс ещё работает
        code = wintypes.DWORD()
        if not self._kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return -1
        return int(code.value)

    def close(self) -> None:
        if self.handle is not None:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def _allow_foreground() -> None:
    """Разрешает новой копии вывести своё окно вперёд: после окна UAC Windows иначе может
    открыть его позади других, и кажется, будто программа просто закрылась."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.AllowSetForegroundWindow.argtypes = [ctypes.c_uint32]
        user32.AllowSetForegroundWindow(_ASFW_ANY)
    except (OSError, AttributeError) as error:  # не критично: окно просто откроется не впереди
        log.info("AllowSetForegroundWindow недоступна: %s", error)


def relaunch_elevated(token: str) -> ElevatedProcess | None:
    """Запускает копию программы с правами администратора. None — запуск не начался.

    Текущий экземпляр закрывается интерфейсом, когда копия запишет `token` в отметку «готова».
    """
    if sys.platform != "win32":
        return None
    _allow_foreground()
    try:
        parameters = _relaunch_parameters(token)
        handle = _shell_execute_ex("runas", sys.executable, parameters, _program_dir())
    except (OSError, AttributeError, ValueError) as error:
        log.warning("Перезапуск с правами администратора не удался: %s", error)
        return None
    return WindowsProcess(handle) if handle else None
