"""Сборщик подробных сведений о видеокартах NVIDIA через `nvidia-smi -q -x` (XML).

`nvidia-smi` входит в драйвер NVIDIA. Он сообщает то, чего не знает Windows:
версию BIOS видеокарты, лимиты мощности (заниженный лимит — частый признак майнинговой
прошивки), максимальные частоты, режим шины PCIe, обороты вентилятора и причины
снижения частот.

Если `nvidia-smi` нет (нет карты NVIDIA или драйвера) — это не ошибка: возвращаем пустой список.

Разные версии драйвера называют поля по-разному, это учтено:
- причины снижения частот: `clocks_throttle_reasons` (старые) / `clocks_event_reasons` (новые);
- мощность: `power_readings` + `enforced_power_limit` (старые) /
  `gpu_power_readings` + `current_power_limit` (новые).
"""

from __future__ import annotations

import logging
import shutil
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from hwcheck.collectors._util import clean, to_float, to_int
from hwcheck.models import GpuInfo
from hwcheck.platform import runner
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

# Где искать nvidia-smi, если его нет в PATH (старые драйверы ставили его в Program Files).
_KNOWN_LOCATIONS = [
    Path(r"C:\Windows\System32\nvidia-smi.exe"),
    Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
]

_MAX_CLOCK_TAGS = {
    "graphics_clock": "graphics",
    "sm_clock": "sm",
    "mem_clock": "memory",
    "video_clock": "video",
}


def find_nvidia_smi() -> str:
    """Путь к nvidia-smi (или просто имя — тогда запуск сообщит «не найден»)."""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    for path in _KNOWN_LOCATIONS:
        if path.is_file():
            return str(path)
    return "nvidia-smi"


def _text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return clean(found.text) if found is not None and found.text else ""


def _width(value: str) -> int | None:
    """`16x` → 16."""
    return to_int(value.rstrip("xX")) if value else None


def _active_reasons(gpu: ET.Element) -> list[str]:
    """Список активных причин снижения частот (имена без префикса)."""
    reasons: list[str] = []
    for section, prefix in (
        ("clocks_event_reasons", "clocks_event_reason_"),
        ("clocks_throttle_reasons", "clocks_throttle_reason_"),
    ):
        node = gpu.find(section)
        if node is None:
            continue
        for child in node:
            if clean(child.text).lower() == "active":
                reasons.append(child.tag.removeprefix(prefix))
    return reasons


def _power_limits(gpu: ET.Element) -> tuple[float | None, float | None, float | None]:
    """(по умолчанию, действующий, максимальный) лимит мощности в ваттах."""
    node = gpu.find("gpu_power_readings")
    if node is None:
        node = gpu.find("power_readings")
    default = to_float(_text(node, "default_power_limit"))
    enforced = to_float(_text(node, "current_power_limit") or _text(node, "enforced_power_limit"))
    maximum = to_float(_text(node, "max_power_limit"))
    return default, enforced, maximum


def _parse_gpu(gpu: ET.Element, driver: str) -> GpuInfo:
    pci_id = _text(gpu, "pci/pci_device_id").lower()  # «218410de»: устройство + производитель
    max_clocks: dict[str, int] = {}
    for tag, key in _MAX_CLOCK_TAGS.items():
        value = to_int(to_float(_text(gpu, f"max_clocks/{tag}")))
        if value:
            max_clocks[key] = value
    default, enforced, maximum = _power_limits(gpu)
    return GpuInfo(
        vendor="NVIDIA",
        name=_text(gpu, "product_name"),
        pci_vendor_id=pci_id[4:8],
        pci_device_id=pci_id[0:4],
        subsystem_id=_text(gpu, "pci/pci_sub_system_id").lower(),
        vram_mb=to_int(to_float(_text(gpu, "fb_memory_usage/total"))),
        vbios_version=_text(gpu, "vbios_version"),
        driver_version=driver,
        default_power_limit_w=default,
        enforced_power_limit_w=enforced,
        max_power_limit_w=maximum,
        max_clocks=max_clocks,
        pcie_gen_current=to_int(_text(gpu, "pci/pci_gpu_link_info/pcie_gen/current_link_gen")),
        pcie_gen_max=to_int(_text(gpu, "pci/pci_gpu_link_info/pcie_gen/max_link_gen")),
        pcie_width_current=_width(
            _text(gpu, "pci/pci_gpu_link_info/link_widths/current_link_width")
        ),
        pcie_width_max=_width(_text(gpu, "pci/pci_gpu_link_info/link_widths/max_link_width")),
        fan_speed_percent=to_float(_text(gpu, "fan_speed")),
        throttle_reasons=_active_reasons(gpu),
        source="nvidia-smi",
    )


def parse(xml_text: str) -> list[GpuInfo]:
    """Разбирает вывод `nvidia-smi -q -x`. Испорченный XML → пустой список."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        log.warning("Не удалось разобрать XML nvidia-smi: %s", error)
        return []
    driver = _text(root, "driver_version") or _text(root, "kmd_version")
    return [_parse_gpu(gpu, driver) for gpu in root.findall("gpu")]


def collect(run_fn: RunFn = runner.run) -> list[GpuInfo]:
    """Запускает nvidia-smi (только чтение). Нет программы или ошибка → пустой список."""
    result = run_fn([find_nvidia_smi(), "-q", "-x"], timeout=30.0, encoding_hint="utf-8")
    if not result.ok:
        log.info("nvidia-smi недоступен (код %s)", result.returncode)
        return []
    return parse(result.stdout)


def merge(wmi_gpus: list[GpuInfo], nvidia_gpus: list[GpuInfo]) -> list[GpuInfo]:
    """Дополняет карты из WMI подробностями из nvidia-smi (сопоставление по кодам устройства).

    Имя и PNPDeviceID берём из Windows, остальное — из nvidia-smi.
    Карты, которых нет в WMI, добавляются в конец списка.
    """
    remaining = list(nvidia_gpus)
    merged: list[GpuInfo] = []
    for gpu in wmi_gpus:
        match = _find_match(gpu, remaining)
        if match is None:
            merged.append(gpu)
            continue
        remaining.remove(match)
        merged.append(
            replace(
                match,
                name=gpu.name or match.name,
                pnp_device_id=gpu.pnp_device_id,
                vram_mb=match.vram_mb or gpu.vram_mb,
                driver_version=match.driver_version or gpu.driver_version,
                source="wmi+nvidia-smi",
            )
        )
    return merged + remaining


def _find_match(gpu: GpuInfo, candidates: list[GpuInfo]) -> GpuInfo | None:
    same_device = [
        c
        for c in candidates
        if c.pci_vendor_id == gpu.pci_vendor_id and c.pci_device_id == gpu.pci_device_id
    ]
    for candidate in same_device:
        if candidate.subsystem_id == gpu.subsystem_id:
            return candidate
    return same_device[0] if same_device else None
