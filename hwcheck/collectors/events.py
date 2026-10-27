"""Сборщик сводки тревожных событий из журнала Windows за последние 30 дней.

Что ищем в журнале «Система» (только чтение, `Get-WinEvent`):
- `whea` — аппаратные ошибки (WHEA-Logger): процессор, память, шина PCIe;
- `kernel_power_41` — компьютер выключился без нормального завершения работы
  (пропадало питание, зависание, перегрев);
- `bugcheck` — «синие экраны» (событие 1001);
- `disk` — ошибки внутренних дисков (события 7, 11, 51, 153 от источника `disk`);
- `disk_removable` — такие же ошибки флешек, карт памяти и уже отключённых дисков.

Без прав администратора часть журнала может быть недоступна — тогда сводка помечается
как частичная (`partial`), а не считается ошибкой.
"""

from __future__ import annotations

import logging
from typing import Any

from hwcheck.collectors._util import as_list, clean, to_int
from hwcheck.models import EventSummary
from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, parse_ps_date, ps_json
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

DAYS = 30

# Ключ сводки → фильтр Get-WinEvent (без StartTime — он добавляется в скрипте).
QUERIES: dict[str, str] = {
    "whea": "LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'",
    "kernel_power_41": "LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=41",
    "bugcheck": (
        "LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=1001"
    ),
    "disk": "LogName='System'; ProviderName='disk'; Id=7,11,51,153",
}

# Для ошибок дисков: номер диска из текста события («\Device\Harddisk1\DR1» → 1) и шина
# этого диска сейчас (Get-PhysicalDisk, только чтение). Ошибки флешек и карт памяти (USB/SD)
# и уже отключённых устройств считаются отдельно — на вердикт по компьютеру они не влияют.
DISK_BREAKDOWN = (
    "$disks = @($events | ForEach-Object { "
    "if ($_.Properties.Count -gt 0 -and \"$($_.Properties[0].Value)\" -match 'Harddisk(\\d+)') "
    "{ [int]$Matches[1] } } | Group-Object | ForEach-Object { $n = $_.Name; "
    "$pd = @(Get-PhysicalDisk -ErrorAction SilentlyContinue | "
    "Where-Object { $_.DeviceId -eq $n }); "
    "[PSCustomObject]@{ Disk=[int]$n; Count=$_.Count; "
    "Bus=$(if ($pd.Count) { [string]$pd[0].BusType } else { '' }) } }); "
)
REMOVABLE_BUSES = {"usb", "sd", ""}  # "" — диска сейчас нет (флешку уже вынули)

PARTIAL_NOTE = (
    "Часть журнала событий недоступна без прав администратора — сводка может быть неполной."
)


def build_script(days: int = DAYS) -> str:
    """Скрипт PowerShell: для каждого вида событий — количество, дата последнего и ошибка."""
    parts = [f"$since = (Get-Date).AddDays(-{int(days)}); $out = @(); "]
    for key, query in QUERIES.items():
        parts.append(
            "$events = @(); $err = $null; "
            f"try {{ $events = @(Get-WinEvent -FilterHashtable @{{ {query}; StartTime=$since }} "
            "-ErrorAction Stop) } "
            "catch { if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') "
            "{ $err = $_.Exception.Message } }; "
            + (DISK_BREAKDOWN if key == "disk" else "$disks = $null; ")
            + f"$out += [PSCustomObject]@{{ Key='{key}'; Count=$events.Count; "
            "Last=$(if ($events.Count) { $events[0].TimeCreated.ToString('s') } else { $null }); "
            "Error=$err; Disks=$disks }; "
        )
    parts.append("$out")
    return "".join(parts)


def parse(data: Any, days: int = DAYS) -> EventSummary:
    """Превращает вывод скрипта в EventSummary."""
    summary = EventSummary(days=days)
    errors: list[str] = []
    for item in as_list(data):
        key = clean(item.get("Key"))
        if not key:
            continue
        error = clean(item.get("Error"))
        if error:
            errors.append(f"{key}: {error}")
            continue
        summary.counts[key] = to_int(item.get("Count")) or 0
        if key == "disk" and item.get("Disks") is not None:
            removable = sum(
                to_int(disk.get("Count")) or 0
                for disk in as_list(item.get("Disks"))
                if clean(disk.get("Bus")).lower() in REMOVABLE_BUSES
            )
            summary.counts["disk"] = max(0, summary.counts["disk"] - removable)
            summary.counts["disk_removable"] = removable
        last = parse_ps_date(item.get("Last"))
        if last:
            summary.last_seen[key] = last
    if errors:
        summary.partial = True
        summary.note = PARTIAL_NOTE
        log.info("Журнал событий прочитан частично: %s", "; ".join(errors))
    return summary


def collect(run_fn: RunFn = runner.run, days: int = DAYS) -> EventSummary:
    """Читает сводку событий. Если PowerShell не сработал совсем — пустая частичная сводка."""
    try:
        return parse(ps_json(build_script(days), timeout=120.0, run_fn=run_fn), days)
    except PowerShellError as error:
        log.warning("Журнал событий недоступен: %s", error)
        return EventSummary(days=days, partial=True, note=PARTIAL_NOTE)
