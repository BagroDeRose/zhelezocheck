"""Перехват системных сочетаний во время теста клавиатуры (Windows, задача 25.1).

Почему не хватило обработки клавиш в виджете (v1.2): Alt+F4 Qt передаёт самой Windows и
**не присылает** виджету событие клавиши, а Windows сразу закрывает окно. Так же Alt (отдельно),
F10 и Alt+Space открывают системное меню окна, и следующие клавиши уходят в него.

Фильтр смотрит сообщения окна до Qt и, **только пока идёт тест клавиатуры**:
- Alt+F4 (`WM_SYSKEYDOWN` с VK_F4) — засчитывает F4 в тесте и гасит, окно не закрывается;
- вход в системное меню (`WM_SYSCOMMAND` / `SC_KEYMENU`: Alt, F10, Alt+Space) — гасит.
Остальное проходит как обычно. Клавиши, которые Windows обрабатывает до программы (Win,
Ctrl+Alt+Del, Alt+Tab), перехватить без системного перехватчика нельзя — в тесте они помечены
«проверяется отдельно». Система при этом не меняется: фильтр видит только сообщения своего окна.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, Qt

from hwcheck.ui.widgets.keyboard_view import KeyboardView

WM_SYSKEYDOWN = 0x0104
WM_SYSCOMMAND = 0x0112
VK_F4 = 0x73
SC_KEYMENU = 0xF100
ALT_CONTEXT = 1 << 29  # бит lParam: клавиша нажата вместе с Alt
F4_SCAN = 0x3E


@dataclass(frozen=True)
class Decision:
    """Что сделать с сообщением: погасить его и/или засчитать клавишу в тесте."""

    block: bool = False
    scan: int = 0
    qt_key: int = 0


def decide(message: int, wparam: int, lparam: int) -> Decision:
    """Решение для сообщения окна во время теста клавиатуры (без Windows — для тестов)."""
    if message == WM_SYSKEYDOWN and wparam == VK_F4 and lparam & ALT_CONTEXT:
        scan = (lparam >> 16) & 0xFF or F4_SCAN
        return Decision(block=True, scan=scan, qt_key=int(Qt.Key.Key_F4))
    if message == WM_SYSCOMMAND and (wparam & 0xFFF0) == SC_KEYMENU:
        return Decision(block=True)
    return Decision()


class KeyboardGuard(QAbstractNativeEventFilter):
    """Фильтр сообщений Windows; действует, только пока `view.running`."""

    def __init__(self, view: KeyboardView) -> None:
        super().__init__()
        self.view = view

    def apply(self, message: int, wparam: int, lparam: int) -> bool:
        """Применяет решение к тесту; True — сообщение погашено."""
        if not self.view.running:
            return False
        decision = decide(message, wparam, lparam)
        if decision.qt_key:
            self.view.press_native(decision.scan, decision.qt_key)
        return decision.block

    def nativeEventFilter(  # noqa: N802 — имя метода Qt
        self,
        eventType: QByteArray | bytes | bytearray | memoryview,  # noqa: N803 — имя из Qt
        message: int,
        /,
    ) -> object:
        kind = eventType.data() if isinstance(eventType, QByteArray) else bytes(eventType)
        if not self.view.running or kind != b"windows_generic_MSG":
            return False, 0
        msg = ctypes.wintypes.MSG.from_address(int(message))
        return self.apply(int(msg.message), int(msg.wParam or 0), int(msg.lParam or 0)), 0
