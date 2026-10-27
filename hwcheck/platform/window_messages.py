"""Сообщения Windows **своему** окну — для самопроверки собранной программы (задача 25.1).

Самопроверка exe нажимает Alt+F4 и «×» в собственном окне так, как это делает Windows:
- Alt+F4 — сообщения `WM_SYSKEYDOWN`/`WM_SYSKEYUP` с признаком Alt; на время отправки в
  состоянии клавиатуры **потока окна** отмечается нажатый Alt (иначе ни Qt, ни Windows не
  считают сочетание настоящим), затем состояние восстанавливается;
- «×» — `WM_SYSCOMMAND` / `SC_CLOSE`.
Сообщения отправляются только по дескриптору окна программы (`PostMessageW`), поэтому другие
программы не затрагиваются; настройки системы не меняются. На других ОС функции ничего не
делают и возвращают False.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_SYSCOMMAND = 0x0112
SC_CLOSE = 0xF060
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_F4 = 0x73
ALT_CONTEXT = 1 << 29
RELEASED = (1 << 30) | (1 << 31)
SCAN_ALT = 0x38
SCAN_F4 = 0x3E


def _user32() -> Any:
    return ctypes.windll.user32  # type: ignore[attr-defined]  # windll есть только на Windows


def send_alt_f4(hwnd: int) -> bool:
    """Нажимает Alt+F4 в своём окне. False — не Windows или сообщения не отправлены."""
    if sys.platform != "win32" or not _user32().IsWindow(hwnd):
        return False  # не Windows или окно не настоящее (платформа Qt offscreen)
    user32 = _user32()
    state = (ctypes.c_ubyte * 256)()
    user32.GetKeyboardState(state)
    state[VK_MENU] = state[VK_LMENU] = 0x80
    user32.SetKeyboardState(state)  # Alt «нажат» — пока окно не обработает сообщения
    sent = [
        user32.PostMessageW(hwnd, WM_SYSKEYDOWN, VK_MENU, ALT_CONTEXT | (SCAN_ALT << 16) | 1),
        user32.PostMessageW(hwnd, WM_SYSKEYDOWN, VK_F4, ALT_CONTEXT | (SCAN_F4 << 16) | 1),
        user32.PostMessageW(hwnd, WM_SYSKEYUP, VK_F4, ALT_CONTEXT | RELEASED | (SCAN_F4 << 16) | 1),
        user32.PostMessageW(hwnd, WM_SYSKEYUP, VK_MENU, RELEASED | (SCAN_ALT << 16) | 1),
    ]
    return all(sent)


def restore_alt(hwnd: int) -> None:
    """Снимает отметку «Alt нажат» в состоянии клавиатуры потока окна (после send_alt_f4)."""
    if sys.platform != "win32":
        return
    user32 = _user32()
    state = (ctypes.c_ubyte * 256)()
    user32.GetKeyboardState(state)
    state[VK_MENU] = state[VK_LMENU] = 0
    user32.SetKeyboardState(state)


def send_close(hwnd: int) -> bool:
    """Нажимает «×» своего окна (как Windows: WM_SYSCOMMAND / SC_CLOSE)."""
    if sys.platform != "win32":
        return False
    return bool(_user32().PostMessageW(hwnd, WM_SYSCOMMAND, SC_CLOSE, 0))
