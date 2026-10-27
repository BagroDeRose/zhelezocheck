"""Обновление справочника PCI ID (инструмент разработчика, запускается вручную).

Скачивает `pci.ids` с официального сайта PCI ID Repository (https://pci-ids.ucw.cz/),
оставляет только производителей видеочипов — NVIDIA (10de), AMD (1002) и Intel (8086) —
без строк подсистем (они не нужны программе) и сохраняет в `hwcheck/data/pci_ids.txt`
с шапкой о лицензии.

Сама программа в интернет не ходит: она читает уже сохранённый файл.

Запуск:  .venv\\Scripts\\python scripts\\update_pci_ids.py
"""

from __future__ import annotations

import sys
import urllib.request
from datetime import date
from pathlib import Path

SOURCE_URL = "https://pci-ids.ucw.cz/v2.2/pci.ids"
VENDORS = ("10de", "1002", "8086")
TARGET = Path(__file__).resolve().parent.parent / "hwcheck" / "data" / "pci_ids.txt"

HEADER = """\
# Выборка из PCI ID Repository (https://pci-ids.ucw.cz/) для производителей
# 10de (NVIDIA), 1002 (AMD), 8086 (Intel), без строк подсистем.
# Источник: {url}
# Дата выборки: {day}
#
# The pci.ids file is maintained by the PCI ID Repository project and is
# available under the 3-clause BSD license or GNU GPL v2.0 or later, at your
# choice. This program uses it under the terms of the 3-clause BSD license
# (see THIRD_PARTY_NOTICES.md).
#
"""


def filter_pci_ids(text: str, vendors: tuple[str, ...] = VENDORS) -> str:
    """Оставляет только строки нужных производителей и их устройств (без подсистем)."""
    kept: list[str] = []
    keep_vendor = False
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("C "):  # дальше идут классы устройств — они не нужны
            break
        if not line.startswith("\t"):
            keep_vendor = line[:4].lower() in vendors
            if keep_vendor:
                kept.append(line)
        elif keep_vendor and not line.startswith("\t\t"):
            kept.append(line)
    return "\n".join(kept) + "\n"


def main() -> int:
    print(f"Скачиваю {SOURCE_URL} …")
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:  # noqa: S310 — фиксированный https-адрес
        text = response.read().decode("utf-8", errors="replace")
    body = filter_pci_ids(text)
    TARGET.write_text(
        HEADER.format(url=SOURCE_URL, day=date.today().isoformat()) + body,
        encoding="utf-8",
        newline="\n",
    )
    print(f"Сохранено {len(body.splitlines())} строк в {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
