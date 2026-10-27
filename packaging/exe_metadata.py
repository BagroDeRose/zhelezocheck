"""Свойства файла ЖелезоЧек.exe — вкладка «Подробно» в Windows (SPEC 1.5, задача 34.7).

Правообладатель указывается только псевдонимом **BagroDeRose** (SPEC 1.5, 33.1): никаких личных
данных в CompanyName, LegalCopyright и других полях. Используется `packaging/hwcheck.spec`.
"""

from __future__ import annotations

import re
from typing import Any

HOLDER = "BagroDeRose"
PRODUCT = "ЖелезоЧек"


def file_version(version: str) -> tuple[int, int, int, int]:
    """1.5.0 → (1, 5, 0, 0); 1.5.0-rc1 → (1, 5, 0, 1) — четыре числа для ресурса Windows."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?", version)
    if not match:
        raise ValueError(f"версия «{version}» не вида 1.2.3 или 1.2.3-rc1")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), int(rc or 0)


def version_strings(version: str) -> dict[str, str]:
    return {
        "CompanyName": HOLDER,
        "FileDescription": "ЖелезоЧек — проверка б/у компьютера перед покупкой",
        "FileVersion": version,
        "InternalName": PRODUCT,
        "LegalCopyright": f"© 2026 {HOLDER}. MIT License.",
        "OriginalFilename": f"{PRODUCT}.exe",
        "ProductName": PRODUCT,
        "ProductVersion": version,
    }


def version_info(version: str) -> Any:
    """Ресурс версии для PyInstaller (EXE(version=...))."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = file_version(version)
    strings = [StringStruct(key, value) for key, value in version_strings(version).items()]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("041904B0", strings)]),  # русский, Unicode
            VarFileInfo([VarStruct("Translation", [0x0419, 1200])]),
        ],
    )
