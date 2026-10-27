"""Поиск названия чипа по кодам PCI (производитель + устройство).

Справочник — выборка из открытой базы PCI ID Repository, файл `hwcheck/data/pci_ids.txt`
(обновляется скриптом `scripts/update_pci_ids.py`). Строки вида
«(табуляция)2204  GA102 [GeForce RTX 3090]» дают чип (GA102) и маркетинговое имя (GeForce RTX 3090).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from hwcheck.config import package_data_dir


@dataclass(frozen=True)
class ChipName:
    """Что известно о устройстве по его кодам PCI."""

    vendor: str  # «NVIDIA Corporation»
    name: str  # строка целиком: «GA102 [GeForce RTX 3090]»
    chip: str  # «GA102»
    marketing: str  # «GeForce RTX 3090» (может быть пустым)


def data_file() -> Path:
    return package_data_dir() / "pci_ids.txt"


def parse_device_name(name: str) -> tuple[str, str]:
    """`GA102 [GeForce RTX 3090]` → (`GA102`, `GeForce RTX 3090`)."""
    if "[" in name and name.endswith("]"):
        chip, _, rest = name.partition("[")
        return chip.strip(), rest[:-1].strip()
    return name.strip(), ""


@cache
def _load() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    vendors: dict[str, str] = {}
    devices: dict[tuple[str, str], str] = {}
    current = ""
    for line in data_file().read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if line.startswith("\t\t"):
            continue
        if line.startswith("\t"):
            code, _, name = line.strip().partition("  ")
            devices[(current, code.lower())] = name.strip()
        else:
            code, _, name = line.partition("  ")
            current = code.lower()
            vendors[current] = name.strip()
    return vendors, devices


def lookup(vendor_id: str, device_id: str) -> ChipName | None:
    """Ищет устройство по кодам (регистр не важен). Не найдено → None."""
    vendors, devices = _load()
    vendor = vendor_id.lower()
    name = devices.get((vendor, device_id.lower()))
    if name is None:
        return None
    chip, marketing = parse_device_name(name)
    return ChipName(vendor=vendors.get(vendor, ""), name=name, chip=chip, marketing=marketing)
