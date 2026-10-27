"""Строки ресурса версии exe-файла (вкладка «Подробно» в свойствах файла Windows).

Нужна самопроверке сборки (SPEC 1.5, 34.7): в свойствах ЖелезоЧек.exe правообладатель —
только псевдоним. Только чтение, через version.dll; на других ОС — пустой результат.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

FIELDS = ("CompanyName", "LegalCopyright", "ProductName", "ProductVersion")


def read_version_strings(path: Path) -> dict[str, str]:
    """Поля ресурса версии файла (пустой словарь, если ресурса нет или это не Windows)."""
    if sys.platform != "win32":
        return {}
    version = ctypes.WinDLL("version")
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return {}
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return {}
    pointer = ctypes.c_void_p()
    length = ctypes.c_uint()
    if (
        not version.VerQueryValueW(
            buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
        )
        or length.value < 4
    ):
        return {}
    lang, codepage = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort * 2)).contents
    result: dict[str, str] = {}
    for field in FIELDS:
        query = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}"
        if version.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length)):
            result[field] = ctypes.wstring_at(pointer.value or 0, max(length.value - 1, 0))
    return result
