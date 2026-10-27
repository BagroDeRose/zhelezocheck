"""Сборщик сведений об оперативной памяти.

WMI `Win32_PhysicalMemory` — список планок (объём, частота, производитель, модель, слот),
`Win32_PhysicalMemoryArray` — сколько всего слотов на плате.
psutil — сколько памяти видит система и сколько сейчас свободно.
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from hwcheck.collectors._util import as_list, clean, to_int
from hwcheck.models import MemoryInfo, MemoryModule
from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, RunFn, ps_json

log = logging.getLogger(__name__)

SCRIPT = (
    "[PSCustomObject]@{ "
    "Modules = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,"
    "ConfiguredClockSpeed,Manufacturer,PartNumber,DeviceLocator,BankLabel); "
    "Arrays = @(Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices) }"
)

_MB = 1024 * 1024


def parse(
    data: Any, psutil_total_mb: int | None = None, psutil_available_mb: int | None = None
) -> MemoryInfo:
    """Превращает вывод `SCRIPT` (и данные psutil) в MemoryInfo."""
    raw = data if isinstance(data, dict) else {}
    modules = [
        MemoryModule(
            capacity_mb=(to_int(item.get("Capacity")) or 0) // _MB,
            speed_mhz=to_int(item.get("Speed")),
            configured_speed_mhz=to_int(item.get("ConfiguredClockSpeed")),
            manufacturer=clean(item.get("Manufacturer")),
            part_number=clean(item.get("PartNumber")),
            slot=clean(item.get("DeviceLocator")),
        )
        for item in as_list(raw.get("Modules"))
    ]
    slots = sum(to_int(item.get("MemoryDevices")) or 0 for item in as_list(raw.get("Arrays")))
    installed = sum(module.capacity_mb for module in modules)
    return MemoryInfo(
        total_mb=installed or psutil_total_mb or 0,
        available_mb=psutil_available_mb,
        modules=modules,
        slots_total=slots or None,
    )


def is_mixed(info: MemoryInfo) -> bool:
    """True, если планки разные (частота, производитель или модель) — повод для пометки."""
    keys = {(m.speed_mhz, m.manufacturer.lower(), m.part_number.lower()) for m in info.modules}
    return len(keys) > 1


def collect(run_fn: RunFn = runner.run) -> MemoryInfo:
    """Читает сведения о памяти; при ошибке WMI — только общий объём из psutil."""
    try:
        data = ps_json(SCRIPT, run_fn=run_fn)
    except PowerShellError as error:
        log.warning("Win32_PhysicalMemory недоступен: %s", error)
        data = None
    virtual = psutil.virtual_memory()
    return parse(data, virtual.total // _MB, virtual.available // _MB)
