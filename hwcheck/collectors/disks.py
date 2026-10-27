"""Сборщик сведений о накопителях (SSD, HDD, флешки) и их «здоровье» S.M.A.R.T.

Основной путь — программа smartctl из smartmontools (лежит в `vendor/smartmontools/`):
- `smartctl --scan-open --json` — список накопителей;
- `smartctl -a --json -d <тип> <устройство>` — данные S.M.A.R.T. каждого (только чтение).

Запасной путь (если smartctl нет или он ничего не нашёл) — средства Windows:
`Get-PhysicalDisk` и `Get-StorageReliabilityCounter`. Счётчики надёжности Windows отдаёт
только администратору — без прав будет частичный результат с пометкой.

Все данные приводятся к одной модели SmartData: наработка, переназначенные/ожидающие/
неисправимые сектора, износ SSD, температура, ошибки кабеля (CRC), общий статус.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from hwcheck.collectors._util import as_list, clean, to_float, to_int
from hwcheck.config import get_paths
from hwcheck.models import DiskInfo, SmartData
from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, ps_json
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

_GB = 1000**3  # производители дисков считают в десятичных гигабайтах

# Биты кода завершения smartctl, означающие, что данные НЕ прочитаны:
# бит 0 — ошибка командной строки, бит 1 — устройство не открылось.
_SMARTCTL_FATAL_BITS = 0b11

# Атрибуты ATA, где нормализованное значение = «осталось ресурса, %».
_WEAR_REMAINING_ATTRS = (177, 231, 233, 202, 169)

FALLBACK_SCRIPT = (
    "$disks = @(Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,Model,MediaType,"
    "BusType,Size,HealthStatus); "
    "$relError = $null; "
    "$rel = @(try { Get-PhysicalDisk | Get-StorageReliabilityCounter -ErrorAction Stop | "
    "Select-Object DeviceId,PowerOnHours,Temperature,Wear,ReadErrorsUncorrected,"
    "ReadErrorsTotal,WriteErrorsUncorrected,StartStopCycleCount } "
    "catch { $relError = $_.Exception.Message }); "
    "[PSCustomObject]@{ Disks = $disks; Reliability = $rel; ReliabilityError = $relError }"
)

UNKNOWN_DISK_MODEL = "Накопитель без названия"
NO_SMART_NOTE = "S.M.A.R.T. недоступен для этого устройства (например, USB-флешка)."
NO_ADMIN_NOTE = "Подробные данные о здоровье диска доступны только при запуске от администратора."


# --------------------------------------------------------------------------
# smartctl
# --------------------------------------------------------------------------


def find_smartctl() -> str | None:
    """Путь к smartctl: сначала из папки программы (vendor), затем из PATH."""
    bundled = get_paths().vendor / "smartmontools" / "bin" / "smartctl.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("smartctl")


def parse_scan(data: Any) -> list[dict[str, str]]:
    """Список устройств из `smartctl --scan-open --json`."""
    devices = data.get("devices") if isinstance(data, dict) else None
    return [
        {"name": clean(item.get("name")), "type": clean(item.get("type"))}
        for item in as_list(devices)
        if item.get("name")
    ]


def _ata_attributes(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    table = (data.get("ata_smart_attributes") or {}).get("table")
    return {int(item["id"]): item for item in as_list(table) if "id" in item}


def _raw(attrs: dict[int, dict[str, Any]], attr_id: int) -> int | None:
    item = attrs.get(attr_id)
    if item is None:
        return None
    return to_int((item.get("raw") or {}).get("value"))


def _ata_wear(attrs: dict[int, dict[str, Any]]) -> float | None:
    for attr_id in _WEAR_REMAINING_ATTRS:
        item = attrs.get(attr_id)
        if item is not None:
            remaining = to_int(item.get("value"))
            if remaining is not None and 0 <= remaining <= 100:
                return float(100 - remaining)
    return None


def _smartctl_media(data: dict[str, Any], protocol: str) -> tuple[str, str]:
    """(тип носителя, шина) по данным smartctl."""
    if protocol == "nvme":
        return "ssd", "nvme"
    rotation = to_int(data.get("rotation_rate"))
    media = "unknown" if rotation is None else ("ssd" if rotation == 0 else "hdd")
    device_type = clean((data.get("device") or {}).get("type")).lower()
    bus = "sata" if protocol == "ata" or device_type in ("sat", "ata") else device_type
    if "usb" in device_type or device_type.startswith("snt"):
        bus = "usb"
    return media, bus


def parse_smartctl(data: dict[str, Any]) -> DiskInfo:
    """Превращает JSON `smartctl -a --json` в DiskInfo с нормализованными SmartData."""
    device = data.get("device") or {}
    exit_status = to_int((data.get("smartctl") or {}).get("exit_status")) or 0
    protocol = clean(device.get("protocol")).lower()
    media, bus = _smartctl_media(data, protocol)
    size = to_int((data.get("user_capacity") or {}).get("bytes")) or to_int(
        data.get("nvme_total_capacity")
    )
    disk = DiskInfo(
        model=clean(data.get("model_name")) or clean(device.get("info_name")),
        size_gb=round((size or 0) / _GB, 1),
        media_type=media,
        bus_type=bus,
        device=clean(device.get("name")),
    )
    smart_available = (data.get("smart_support") or {}).get("available")
    if exit_status & _SMARTCTL_FATAL_BITS or smart_available is False:
        disk.note = NO_SMART_NOTE
        return disk

    status = data.get("smart_status") or {}
    smart = SmartData(
        power_on_hours=to_int((data.get("power_on_time") or {}).get("hours")),
        power_cycles=to_int(data.get("power_cycle_count")),
        temperature_c=to_float((data.get("temperature") or {}).get("current")),
        health_passed=status.get("passed") if isinstance(status.get("passed"), bool) else None,
        source="smartctl",
    )
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        smart.wear_percent = to_float(nvme.get("percentage_used"))
        smart.media_errors = to_int(nvme.get("media_errors"))
        smart.power_on_hours = smart.power_on_hours or to_int(nvme.get("power_on_hours"))
        if smart.temperature_c is None:
            smart.temperature_c = to_float(nvme.get("temperature"))
    attrs = _ata_attributes(data)
    if attrs:
        smart.reallocated_sectors = _raw(attrs, 5)
        smart.pending_sectors = _raw(attrs, 197)
        smart.uncorrectable_sectors = _raw(attrs, 198)
        smart.crc_errors = _raw(attrs, 199)
        if media == "ssd":
            smart.wear_percent = _ata_wear(attrs)
    disk.smart = smart
    return disk


def _run_smartctl(run_fn: RunFn, smartctl: str, args: list[str]) -> dict[str, Any] | None:
    """Запускает smartctl и разбирает JSON (ненулевой код — не повод отбрасывать вывод)."""
    result = run_fn([smartctl, *args], timeout=60.0, encoding_hint="utf-8")
    if result.not_found or result.timed_out or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.warning("smartctl вернул не JSON: %s", result.stdout[:200])
        return None
    return data if isinstance(data, dict) else None


def collect_smartctl(run_fn: RunFn, smartctl: str) -> list[DiskInfo]:
    """Основной путь: все накопители, которые видит smartctl."""
    scan = _run_smartctl(run_fn, smartctl, ["--scan-open", "--json"])
    disks: list[DiskInfo] = []
    for device in parse_scan(scan):
        args = ["-a", "--json"]
        if device["type"]:
            args += ["-d", device["type"]]
        data = _run_smartctl(run_fn, smartctl, [*args, device["name"]])
        if data is None:
            disks.append(DiskInfo(model=device["name"], device=device["name"], note=NO_SMART_NOTE))
        else:
            disk = parse_smartctl(data)
            # Некоторые устройства (кардридеры, флешки) не сообщают ни название, ни имя.
            disk.device = disk.device or device["name"]
            disk.model = disk.model or f"{UNKNOWN_DISK_MODEL} ({disk.device})"
            disks.append(disk)
    return disks


# --------------------------------------------------------------------------
# Запасной путь: средства Windows
# --------------------------------------------------------------------------

_MEDIA_TYPES = {"3": "hdd", "4": "ssd", "hdd": "hdd", "ssd": "ssd"}
_BUS_TYPES = {"17": "nvme", "11": "sata", "7": "usb", "8": "raid", "10": "sas", "3": "ata"}
_HEALTHY = {"0", "healthy"}


def parse_fallback(data: Any) -> list[DiskInfo]:
    """Превращает вывод `FALLBACK_SCRIPT` в список накопителей."""
    raw = data if isinstance(data, dict) else {}
    reliability = {clean(item.get("DeviceId")): item for item in as_list(raw.get("Reliability"))}
    reliability_error = clean(raw.get("ReliabilityError"))
    disks: list[DiskInfo] = []
    for item in as_list(raw.get("Disks")):
        bus_raw = clean(item.get("BusType")).lower()
        health = clean(item.get("HealthStatus")).lower()
        counters = reliability.get(clean(item.get("DeviceId")), {})
        smart = SmartData(
            power_on_hours=to_int(counters.get("PowerOnHours")),
            power_cycles=to_int(counters.get("StartStopCycleCount")),
            uncorrectable_sectors=to_int(counters.get("ReadErrorsUncorrected")),
            wear_percent=to_float(counters.get("Wear")) if counters else None,
            temperature_c=to_float(counters.get("Temperature")) or None,
            health_passed=(health in _HEALTHY) if health else None,
            source="windows",
        )
        disks.append(
            DiskInfo(
                model=clean(item.get("Model")) or clean(item.get("FriendlyName")),
                size_gb=round((to_int(item.get("Size")) or 0) / _GB, 1),
                media_type=_MEDIA_TYPES.get(clean(item.get("MediaType")).lower(), "unknown"),
                bus_type=_BUS_TYPES.get(bus_raw, bus_raw),
                device=f"PhysicalDisk{clean(item.get('DeviceId'))}",
                smart=smart,
                note=NO_ADMIN_NOTE if reliability_error and not counters else "",
            )
        )
    return disks


def collect(run_fn: RunFn = runner.run, smartctl: str | None = "auto") -> list[DiskInfo]:
    """Собирает накопители: smartctl, а если его нет или он ничего не нашёл — средства Windows.

    `smartctl="auto"` — найти программу самостоятельно; `None` — не использовать.
    """
    path = find_smartctl() if smartctl == "auto" else smartctl
    if path:
        disks = collect_smartctl(run_fn, path)
        if any(disk.smart is not None for disk in disks):
            if any(disk.size_gb == 0 or disk.media_type == "unknown" for disk in disks):
                # smartctl иногда не сообщает объём и тип (например, без прав администратора) —
                # дополняем сведениями Windows.
                return enrich(disks, _collect_fallback(run_fn))
            return disks
        # smartctl видит диски, но не может их прочитать (бывает без прав администратора).
        log.info("smartctl не прочитал ни одного накопителя, переходим к средствам Windows")
    return _collect_fallback(run_fn)


def _collect_fallback(run_fn: RunFn) -> list[DiskInfo]:
    try:
        return parse_fallback(ps_json(FALLBACK_SCRIPT, run_fn=run_fn))
    except PowerShellError as error:
        log.warning("Get-PhysicalDisk недоступен: %s", error)
        return []


def _same_model(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def enrich(smart_disks: list[DiskInfo], windows_disks: list[DiskInfo]) -> list[DiskInfo]:
    """Дополняет диски из smartctl объёмом/типом из Windows (по совпадению модели)."""
    for disk in smart_disks:
        match = next((w for w in windows_disks if _same_model(w.model, disk.model)), None)
        if match is None:
            continue
        if disk.size_gb == 0:
            disk.size_gb = match.size_gb
        if disk.media_type == "unknown":
            disk.media_type = match.media_type
        if not disk.bus_type or disk.bus_type in ("ata", "scsi"):
            disk.bus_type = match.bus_type or disk.bus_type
    return smart_disks
