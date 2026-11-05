"""Сборщик сводки тревожных событий из журнала Windows за последние 30 дней.

Что ищем в журнале «Система» (только чтение, `Get-WinEvent`):
- `whea` — аппаратные ошибки (WHEA-Logger): процессор, память, шина PCIe;
- `kernel_power_41` — компьютер выключился без нормального завершения работы
  (пропадало питание, зависание, перегрев);
- `bugcheck` — «синие экраны» (событие 1001);
- `disk` — ошибки внутренних дисков (события 7, 11, 51, 153 от источника `disk`);
- `disk_removable` — такие же ошибки флешек, карт памяти и уже отключённых дисков;
- с 2.1: `storage` — файловая система и контроллеры дисков (Ntfs, storahci, stornvme),
  `gpu_driver` — ошибки драйверов видеокарт и восстановление драйвера (Display 4101),
  `unexpected_shutdown` — «предыдущее завершение работы было неожиданным» (EventLog 6008).

Для каждого вида события (источник + код) запоминаются уровень, число повторений, время
первого и последнего и первая строка текста. Источники запрашиваются по одному: если в системе
нет, например, драйвера AMD, запрос с ним целиком упал бы («нет такого источника»), а это
значит лишь «таких событий нет». Имя пользователя в путях текста события заменяется.

Без прав администратора часть журнала может быть недоступна — тогда сводка помечается
как частичная (`partial`), а не считается ошибкой.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from hwcheck.collectors._util import as_list, clean, to_int
from hwcheck.models import EventRecord, EventSummary
from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, parse_ps_date, ps_json
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

DAYS = 30

_ERRORS = "Level=1,2,3"  # критические, ошибки, предупреждения (без «сведений»)

# Ключ сводки → фильтры Get-WinEvent, по одному источнику (журнал System и StartTime
# добавляются в скрипте).
QUERIES: dict[str, list[str]] = {
    "whea": ["ProviderName='Microsoft-Windows-WHEA-Logger'"],
    "kernel_power_41": ["ProviderName='Microsoft-Windows-Kernel-Power'; Id=41"],
    "bugcheck": ["ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=1001"],
    "disk": ["ProviderName='disk'; Id=7,11,51,153"],
    "storage": [
        f"ProviderName='{name}'; {_ERRORS}"
        for name in ("Microsoft-Windows-Ntfs", "Ntfs", "storahci", "stornvme")
    ],
    "gpu_driver": [
        *(
            f"ProviderName='{name}'; {_ERRORS}"
            for name in ("nvlddmkm", "amdkmdag", "amdwddmg", "igfx", "igfxn")
        ),
        "ProviderName='Display'; Id=4101",
    ],
    "unexpected_shutdown": ["ProviderName='EventLog'; Id=6008"],
}
MESSAGE_LIMIT = 300  # первая строка события, не длиннее
ITEMS_PER_GROUP = 20  # видов событий в группе — достаточно для разбора
_USER_PATH = re.compile(r"([A-Za-z]:\\Users\\)[^\\\s]+", re.IGNORECASE)

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


# Виды событий группы: источник + код → уровень, число, первое и последнее время, текст.
ITEMS = (
    "$items = @($events | Group-Object ProviderName, Id | ForEach-Object { $g = @($_.Group); "
    "$m = $g[0].Message; if ($m) { $m = ($m -split \"`r?`n\")[0] } else { $m = '' }; "
    "[PSCustomObject]@{ Provider=$g[0].ProviderName; Id=$g[0].Id; Level=$g[0].Level; "
    "Count=$g.Count; Last=$g[0].TimeCreated.ToString('s'); "
    "First=$g[-1].TimeCreated.ToString('s'); Message=$m } } "
    f"| Select-Object -First {ITEMS_PER_GROUP}); "
)


def build_script(days: int = DAYS) -> str:
    """Скрипт PowerShell: для каждой группы — количество, дата последнего, виды событий, ошибка."""
    parts = [f"$since = (Get-Date).AddDays(-{int(days)}); $out = @(); "]
    for key, queries in QUERIES.items():
        filters = ", ".join(
            f"@{{ LogName='System'; {query}; StartTime=$since }}" for query in queries
        )
        parts.append(
            "$events = @(); $err = $null; "
            f"foreach ($f in @({filters})) {{ "
            "try { $events += @(Get-WinEvent -FilterHashtable $f -ErrorAction Stop) } "
            "catch { if ($_.FullyQualifiedErrorId -notlike 'NoMatching*') "
            "{ $err = $_.Exception.Message } } }; "
            "$events = @($events | Sort-Object TimeCreated -Descending); "
            + (DISK_BREAKDOWN if key == "disk" else "$disks = $null; ")
            + ITEMS
            + f"$out += [PSCustomObject]@{{ Key='{key}'; Count=$events.Count; "
            "Last=$(if ($events.Count) { $events[0].TimeCreated.ToString('s') } else { $null }); "
            "Error=$err; Disks=$disks; Items=$items }; "
        )
    parts.append("$out")
    return "".join(parts)


def clean_message(text: str) -> str:
    """Первая строка события: без имени пользователя в путях и не длиннее MESSAGE_LIMIT."""
    message = _USER_PATH.sub(r"\1<пользователь>", text.strip())
    return message if len(message) <= MESSAGE_LIMIT else message[:MESSAGE_LIMIT] + "…"


def _items(group: str, data: Any) -> list[EventRecord]:
    return [
        EventRecord(
            group=group,
            provider=clean(item.get("Provider")),
            event_id=to_int(item.get("Id")) or 0,
            level=to_int(item.get("Level")),
            count=to_int(item.get("Count")) or 0,
            first_seen=parse_ps_date(item.get("First")) or "",
            last_seen=parse_ps_date(item.get("Last")) or "",
            message=clean_message(clean(item.get("Message"))),
        )
        for item in as_list(data)
        if isinstance(item, dict)
    ]


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
        group = key
        if key == "disk" and item.get("Disks") is not None:
            removable = sum(
                to_int(disk.get("Count")) or 0
                for disk in as_list(item.get("Disks"))
                if clean(disk.get("Bus")).lower() in REMOVABLE_BUSES
            )
            summary.counts["disk"] = max(0, summary.counts["disk"] - removable)
            summary.counts["disk_removable"] = removable
            # Подробности сгруппированы по источнику и коду, не по диску: если ошибки были
            # только у съёмных — это их группа, если у разных — «вместе» (номер диска в тексте).
            if removable and summary.counts["disk"] == 0:
                group = "disk_removable"
            elif removable:
                group = "disk_mixed"
        summary.items += _items(group, item.get("Items"))
        last = parse_ps_date(item.get("Last"))
        if last:
            # Все ошибки — у съёмных: и время их (ручная проверка 2.1.0-rc1).
            summary.last_seen["disk_removable" if group == "disk_removable" else key] = last
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
