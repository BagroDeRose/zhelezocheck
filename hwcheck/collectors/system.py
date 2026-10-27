"""Сборщик сведений об операционной системе, модели компьютера и BIOS.

Источник — классы WMI `Win32_OperatingSystem`, `Win32_ComputerSystem`, `Win32_BIOS`
и `Win32_SystemEnclosure` (тип корпуса — чтобы понять, ноутбук ли это).
Серийные номера не читаем: они не нужны для проверки и относятся к личным данным.
"""

from __future__ import annotations

from typing import Any

from hwcheck.collectors._util import clean, to_int
from hwcheck.models import SystemInfo
from hwcheck.platform import runner
from hwcheck.platform.powershell import RunFn, parse_ps_date, ps_json

SCRIPT = (
    "$os = Get-CimInstance Win32_OperatingSystem; "
    "$cs = Get-CimInstance Win32_ComputerSystem; "
    "$bios = Get-CimInstance Win32_BIOS; "
    "$enc = Get-CimInstance Win32_SystemEnclosure; "
    "[PSCustomObject]@{ "
    "OS = $os | Select-Object Caption,Version,BuildNumber,OSArchitecture,"
    "InstallDate,LastBootUpTime; "
    "CS = $cs | Select-Object Manufacturer,Model,PCSystemType; "
    "BIOS = $bios | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate; "
    "ChassisTypes = $enc.ChassisTypes }"
)

# PCSystemType = 2 — «мобильный» компьютер (ноутбук).
_PC_SYSTEM_TYPE_MOBILE = 2
# Типы корпусов SMBIOS, означающие ноутбук/планшет: Portable, Laptop, Notebook, Hand Held,
# Sub Notebook, Docking Station? (нет), Tablet, Convertible, Detachable и т.д.
_LAPTOP_CHASSIS = {8, 9, 10, 11, 14, 30, 31, 32}


def _is_laptop(computer: dict[str, Any], chassis: Any) -> bool:
    if to_int(computer.get("PCSystemType")) == _PC_SYSTEM_TYPE_MOBILE:
        return True
    types = chassis if isinstance(chassis, list) else [chassis]
    return any(to_int(item) in _LAPTOP_CHASSIS for item in types)


def parse(data: Any) -> SystemInfo:
    """Превращает вывод `SCRIPT` в SystemInfo. Отсутствующие поля остаются пустыми."""
    if not isinstance(data, dict):
        return SystemInfo()
    os_part = data.get("OS") or {}
    computer = data.get("CS") or {}
    bios = data.get("BIOS") or {}
    return SystemInfo(
        os_name=clean(os_part.get("Caption")),
        os_version=clean(os_part.get("Version")),
        os_build=clean(os_part.get("BuildNumber")),
        architecture=clean(os_part.get("OSArchitecture")),
        install_date=parse_ps_date(os_part.get("InstallDate")),
        last_boot=parse_ps_date(os_part.get("LastBootUpTime")),
        manufacturer=clean(computer.get("Manufacturer")),
        model=clean(computer.get("Model")),
        is_laptop=_is_laptop(computer, data.get("ChassisTypes")),
        bios_vendor=clean(bios.get("Manufacturer")),
        bios_version=clean(bios.get("SMBIOSBIOSVersion")),
        bios_date=parse_ps_date(bios.get("ReleaseDate")),
    )


def collect(run_fn: RunFn = runner.run) -> SystemInfo:
    """Читает сведения о системе через PowerShell."""
    return parse(ps_json(SCRIPT, run_fn=run_fn))
