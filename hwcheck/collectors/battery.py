"""Сборщик сведений о батарее ноутбука.

Источник — встроенный отчёт Windows: `powercfg /batteryreport /xml /output <файл>`.
Отчёт сохраняется во временную папку (она удаляется сразу после чтения).
Из отчёта берём проектную ёмкость, текущую полную ёмкость и число циклов заряда;
по ним считается износ. Если батарей несколько — ёмкости складываются.

На компьютере без батареи powercfg завершается с ошибкой — это нормально, возвращаем None.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from hwcheck.collectors._util import clean, to_int
from hwcheck.config import temp_dir
from hwcheck.models import BatteryInfo
from hwcheck.platform import runner
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

_NS = "{http://schemas.microsoft.com/battery/2012}"


def _field(battery: ET.Element, name: str) -> str:
    node = battery.find(f"{_NS}{name}")
    return clean(node.text) if node is not None and node.text else ""


_ISO_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:[\d.]+S)?$")


def iso_minutes(text: str) -> int | None:
    """«PT3H12M» → 192 минуты. Пусто или ноль → None."""
    match = _ISO_DURATION.match(text.strip()) if text else None
    if match is None:
        return None
    minutes = int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
    return minutes or None


def _runtime(root: ET.Element, capacity: str) -> int | None:
    node = root.find(f"{_NS}RuntimeEstimates/{_NS}{capacity}/{_NS}ActiveRuntime")
    return iso_minutes(node.text or "") if node is not None else None


def parse(xml_text: str) -> BatteryInfo | None:
    """Разбирает XML отчёта о батарее. Нет батарей или битый файл → None."""
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        log.warning("Не удалось разобрать отчёт о батарее: %s", error)
        return None
    batteries = root.findall(f"{_NS}Batteries/{_NS}Battery")
    if not batteries:
        return None
    design = sum(to_int(_field(b, "DesignCapacity")) or 0 for b in batteries)
    full = sum(to_int(_field(b, "FullChargeCapacity")) or 0 for b in batteries)
    cycles = [to_int(_field(b, "CycleCount")) for b in batteries]
    known_cycles = [c for c in cycles if c]
    makers = [_field(b, "Manufacturer") for b in batteries if _field(b, "Manufacturer")]
    chemistry = [_field(b, "Chemistry") for b in batteries if _field(b, "Chemistry")]
    return BatteryInfo(
        design_capacity_mwh=design,
        full_charge_capacity_mwh=full,
        cycle_count=max(known_cycles) if known_cycles else None,
        manufacturer=", ".join(makers),
        chemistry=chemistry[0] if chemistry else "",
        runtime_minutes=_runtime(root, "FullChargeCapacity"),
        design_runtime_minutes=_runtime(root, "DesignCapacity"),
    )


def collect(run_fn: RunFn = runner.run) -> BatteryInfo | None:
    """Строит отчёт powercfg во временной папке и читает его. Нет батареи → None."""
    with temp_dir("hwcheck_battery_") as folder:
        report = folder / "battery.xml"
        result = run_fn(
            ["powercfg", "/batteryreport", "/xml", "/output", str(report)], timeout=60.0
        )
        if not report.is_file():
            log.info("Отчёт о батарее не создан (код %s): батареи, видимо, нет", result.returncode)
            return None
        return parse(report.read_text(encoding="utf-8-sig", errors="replace"))
