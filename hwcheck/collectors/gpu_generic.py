"""Общий сборщик сведений о видеокартах (любой производитель).

Источники (только чтение):
- WMI `Win32_VideoController` — имя, производитель, версия драйвера, `PNPDeviceID`;
- `PNPDeviceID` содержит настоящие коды устройства: `PCI\\VEN_10DE&DEV_2503&SUBSYS_...`.
  По ним потом определяется реальный чип (защита от перемаркированных карт);
- реестр, ветка класса видеоадаптеров, значение `HardwareInformation.qwMemorySize` —
  объём видеопамяти. Поле `AdapterRAM` в WMI 32-битное и «упирается» в 4 ГБ, поэтому
  берём объём из реестра. Реестр только ЧИТАЕТСЯ (`Get-ItemProperty`).

Виртуальные адаптеры (удалённый доступ, Parsec и т.п.) — не PCI-устройства, их пропускаем.
"""

from __future__ import annotations

import re
from typing import Any

from hwcheck.collectors._util import as_list, clean, to_int
from hwcheck.models import GpuInfo
from hwcheck.platform import runner
from hwcheck.platform.powershell import RunFn, ps_json

DISPLAY_CLASS_KEY = (
    r"HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
)

SCRIPT = (
    "[PSCustomObject]@{ "
    "Controllers = @(Get-CimInstance Win32_VideoController | Select-Object Name,"
    "AdapterCompatibility,PNPDeviceID,AdapterRAM,DriverVersion,Status); "
    f"Registry = @(Get-ItemProperty -Path '{DISPLAY_CLASS_KEY}\\0*' -ErrorAction SilentlyContinue "
    "| Select-Object 'HardwareInformation.qwMemorySize',MatchingDeviceId,DriverDesc) }"
)

VENDORS = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel", "1414": "Microsoft"}

_PNP_RE = re.compile(
    r"VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})(?:&SUBSYS_([0-9A-F]{8}))?", re.IGNORECASE
)
_MB = 1024 * 1024
# AdapterRAM — 32-битное поле: значения около 4 ГБ означают «4 ГБ или больше».
_ADAPTER_RAM_CAP = 4 * 1024 * _MB - 16 * _MB


def parse_pnp_id(pnp_device_id: str) -> tuple[str, str, str] | None:
    """Достаёт (vendor, device, subsystem) из PNPDeviceID; для не-PCI устройств → None."""
    if not pnp_device_id.upper().startswith("PCI\\"):
        return None
    match = _PNP_RE.search(pnp_device_id)
    if not match:
        return None
    vendor, device, subsystem = match.groups()
    return vendor.lower(), device.lower(), (subsystem or "").lower()


def nvidia_driver_version(windows_version: str) -> str:
    """Версия драйвера Windows `32.0.15.6094` → привычная версия NVIDIA `560.94`."""
    digits = windows_version.replace(".", "")
    if len(digits) < 5 or not digits.isdigit():
        return windows_version
    tail = digits[-5:]
    return f"{int(tail[:3])}.{tail[3:]}"


def _registry_vram_mb(registry: list[dict[str, Any]], vendor: str, device: str) -> int | None:
    """Ищет объём видеопамяти в записях реестра по кодам устройства."""
    prefix = f"pci\\ven_{vendor}&dev_{device}"
    for entry in registry:
        matching = clean(entry.get("MatchingDeviceId")).lower()
        size = to_int(entry.get("HardwareInformation.qwMemorySize"))
        if matching.startswith(prefix) and size:
            return size // _MB
    return None


def parse(data: Any) -> list[GpuInfo]:
    """Превращает вывод `SCRIPT` в список видеокарт."""
    raw = data if isinstance(data, dict) else {}
    registry = as_list(raw.get("Registry"))
    gpus: list[GpuInfo] = []
    for controller in as_list(raw.get("Controllers")):
        pnp = clean(controller.get("PNPDeviceID"))
        ids = parse_pnp_id(pnp)
        if ids is None:
            continue
        vendor_id, device_id, subsystem_id = ids
        vendor = VENDORS.get(vendor_id, clean(controller.get("AdapterCompatibility")))
        vram_mb = _registry_vram_mb(registry, vendor_id, device_id)
        adapter_ram = to_int(controller.get("AdapterRAM"))
        if vram_mb is None and adapter_ram and adapter_ram < _ADAPTER_RAM_CAP:
            vram_mb = adapter_ram // _MB
        driver = clean(controller.get("DriverVersion"))
        if vendor == "NVIDIA":
            driver = nvidia_driver_version(driver)
        gpus.append(
            GpuInfo(
                vendor=vendor,
                name=clean(controller.get("Name")),
                pci_vendor_id=vendor_id,
                pci_device_id=device_id,
                subsystem_id=subsystem_id,
                vram_mb=vram_mb,
                driver_version=driver,
                pnp_device_id=pnp,
                source="wmi",
            )
        )
    return gpus


def collect(run_fn: RunFn = runner.run) -> list[GpuInfo]:
    """Читает список видеокарт через PowerShell (WMI + чтение реестра)."""
    return parse(ps_json(SCRIPT, run_fn=run_fn))
