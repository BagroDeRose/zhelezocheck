"""Сборщик сведений о процессоре.

Основной источник — WMI `Win32_Processor` (имя, ядра, потоки, частота).
Если WMI недоступен, число ядер и частота берутся из psutil — он работает на любой ОС.
На компьютерах с двумя процессорами берём первый (для домашних ПК это не встречается).
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from hwcheck.collectors._util import as_list, clean, to_int
from hwcheck.models import CpuInfo
from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, RunFn, ps_json

log = logging.getLogger(__name__)

SCRIPT = (
    "Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,"
    "NumberOfLogicalProcessors,MaxClockSpeed,CurrentClockSpeed,SocketDesignation,"
    "Caption,L2CacheSize,L3CacheSize,VirtualizationFirmwareEnabled"
)


def parse(
    data: Any,
    fallback_cores: int | None = None,
    fallback_threads: int | None = None,
    fallback_max_mhz: float | None = None,
) -> CpuInfo:
    """Превращает вывод `SCRIPT` в CpuInfo; пробелы в данных заполняет запасными значениями."""
    items = as_list(data)
    raw: dict[str, Any] = items[0] if items else {}
    max_mhz = to_int(raw.get("MaxClockSpeed"))
    if max_mhz is None and fallback_max_mhz:
        max_mhz = int(fallback_max_mhz)
    return CpuInfo(
        name=clean(raw.get("Name")),
        manufacturer=clean(raw.get("Manufacturer")),
        cores=to_int(raw.get("NumberOfCores")) or fallback_cores or 0,
        threads=to_int(raw.get("NumberOfLogicalProcessors")) or fallback_threads or 0,
        max_clock_mhz=max_mhz,
        current_clock_mhz=to_int(raw.get("CurrentClockSpeed")),
        socket=clean(raw.get("SocketDesignation")),
        cpuid=clean(raw.get("Caption")),
        l2_cache_kb=to_int(raw.get("L2CacheSize")) or None,
        l3_cache_kb=to_int(raw.get("L3CacheSize")) or None,
        virtualization_enabled=_bool(raw.get("VirtualizationFirmwareEnabled")),
    )


def _bool(value: Any) -> bool | None:
    """True/False из WMI; всё остальное — «не удалось узнать»."""
    return value if isinstance(value, bool) else None


def collect(run_fn: RunFn = runner.run) -> CpuInfo:
    """Читает сведения о процессоре; при ошибке WMI — только данные psutil."""
    try:
        data = ps_json(SCRIPT, run_fn=run_fn)
    except PowerShellError as error:
        log.warning("Win32_Processor недоступен: %s", error)
        data = None
    frequency = psutil.cpu_freq()
    return parse(
        data,
        fallback_cores=psutil.cpu_count(logical=False),
        fallback_threads=psutil.cpu_count(logical=True),
        fallback_max_mhz=frequency.max if frequency else None,
    )
