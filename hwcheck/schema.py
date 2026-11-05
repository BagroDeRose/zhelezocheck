"""Версия схемы данных и чтение старых проверок (с версии 2.1).

Что делает модуль:
- `load_session(text)` — открывает проверку из JSON любой версии программы: старая (без
  `schema_version`) приводится к текущей схеме, будущая читается «как сможем», версия не
  занижается. Исходные данные не меняются и не теряются: приведение делается над копией,
  а записи истории в базе не перезаписываются.
- `series_points(result)` — замеры теста в полном виде временного ряда: время, секунды от
  начала, датчик, значение, единица, источник, качество. Пропущенный замер датчика (None) —
  не точка с нулём, а отсутствие точки.

Схема 1 → 2: добавлены необязательные поля (параметры с источником и статусом, отметки на
рядах, время начала теста, источники датчиков). Старые поля не переименовывались, поэтому
приведение только проставляет версию и запоминает, из какой версии проверка пришла.
"""

from __future__ import annotations

import copy
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from hwcheck.models import SCHEMA_VERSION, CheckSession, SeriesPoint, TestResult

log = logging.getLogger(__name__)

LEGACY_VERSION = 1  # проверки до 2.1: поля schema_version не было


class SchemaError(ValueError):
    """Файл проверки не читается: не JSON, не та структура или испорченная версия."""


def _version(data: dict[str, Any]) -> int:
    value = data.get("schema_version", LEGACY_VERSION)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchemaError(f"Непонятная версия схемы: {value!r}")
    return value


def upgrade_session_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Копия словаря проверки, приведённая к текущей схеме (исходный словарь не меняется)."""
    if not isinstance(data, dict):
        raise SchemaError("Проверка должна быть объектом JSON")
    version = _version(data)
    upgraded = copy.deepcopy(data)
    if version > SCHEMA_VERSION:
        log.warning(
            "Проверка из более новой версии программы (схема %s) — читаем частично", version
        )
        return upgraded
    if version < SCHEMA_VERSION:
        upgraded["migrated_from"] = version
    upgraded["schema_version"] = SCHEMA_VERSION
    snapshot = upgraded.get("snapshot")
    if isinstance(snapshot, dict):
        snapshot["schema_version"] = SCHEMA_VERSION
    return upgraded


def load_session(text: str) -> CheckSession:
    """Проверка из JSON любой версии программы. Не читается — SchemaError."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise SchemaError(f"Файл проверки — не JSON: {error}") from error
    upgraded = upgrade_session_dict(data)
    try:
        return CheckSession.from_dict(upgraded)
    except (TypeError, ValueError, KeyError, AttributeError) as error:
        raise SchemaError(f"Файл проверки не по схеме: {error}") from error


# --------------------------------------------------------------------------
# Временные ряды
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SensorDef:
    """Как называется ключ замера в полном временном ряду."""

    name: str  # часть sensor_id после компонента: «temperature» → «gpu0.temperature»
    label: str
    unit: str
    source: str


# Ключи замеров видеокарты (nvidia-smi) и процессора (счётчики Windows) → описание датчика.
GPU_SENSORS: dict[str, SensorDef] = {
    "temp_c": SensorDef("temperature", "Температура GPU", "°C", "nvidia-smi"),
    "clock_mhz": SensorDef("core_clock", "Частота ядра GPU", "МГц", "nvidia-smi"),
    "mem_clock_mhz": SensorDef("memory_clock", "Частота памяти GPU", "МГц", "nvidia-smi"),
    "power_w": SensorDef("power", "Потребление GPU", "Вт", "nvidia-smi"),
    "fan_pct": SensorDef("fan", "Вентилятор GPU", "%", "nvidia-smi"),
    "util_pct": SensorDef("utilization", "Загрузка GPU", "%", "nvidia-smi"),
    "mem_util_pct": SensorDef(
        "memory_utilization", "Загрузка контроллера памяти GPU", "%", "nvidia-smi"
    ),
    "vram_used_mb": SensorDef("vram_used", "Занято видеопамяти", "МБ", "nvidia-smi"),
    "throttle_mask": SensorDef(
        "throttle_reasons", "Причины снижения частот (биты)", "", "nvidia-smi"
    ),
}
CPU_SENSORS: dict[str, SensorDef] = {
    "clock_mhz": SensorDef(
        "clock", "Частота CPU", "МГц", "Windows: % Processor Performance × номинал"
    ),
    "perf_pct": SensorDef(
        "performance", "Производительность CPU от номинала", "%", "Windows: % Processor Performance"
    ),
    # «% Processor Time» (0–100 %). До 2.1.0-rc2 здесь был «% Processor Utility» — он считает
    # загрузку относительно номинальной частоты и при турбо показывает больше 100 % (134 % на
    # ручной проверке rc1), а это не «загрузка» в обычном смысле.
    "util_pct": SensorDef("utilization", "Загрузка CPU", "%", "Windows: % Processor Time"),
    # Это датчик платы рядом с процессором, а не температура ядер CPU. Счётчик Windows и класс
    # WMI читают одну и ту же ACPI-зону (sensors.py берёт тот, что доступен).
    "zone_temp_c": SensorDef(
        "zone_temp",
        "Температура тепловой зоны ACPI (датчик платы, не ядра CPU)",
        "°C",
        "Windows: ACPI-тепловая зона (ThermalZoneInformation / MSAcpi_ThermalZoneTemperature)",
    ),
}


def sensor_def(component: str, key: str) -> SensorDef | None:
    """Описание датчика по компоненту замера («gpu0», «cpu») и ключу значения."""
    if component.startswith("gpu"):
        return GPU_SENSORS.get(key)
    if component == "cpu":
        return CPU_SENSORS.get(key)
    return None


def sensor_by_name(component: str, name: str) -> SensorDef | None:
    """Описание датчика по имени из sensor_id: («gpu0», «temperature») → «Температура GPU»."""
    registry = GPU_SENSORS if component.startswith("gpu") else CPU_SENSORS
    return next((d for d in registry.values() if d.name == name), None)


def sensor_id(component: str, key: str) -> str:
    definition = sensor_def(component, key)
    return f"{component}.{definition.name if definition else key}"


def _start(result: TestResult) -> datetime | None:
    if not result.started_at:
        return None
    try:
        return datetime.fromisoformat(result.started_at)
    except ValueError:
        return None


def _source(
    result: TestResult, component: str, identifier: str, definition: SensorDef | None
) -> str:
    """Источник датчика: особый для этого теста («gpu0.power» или «gpu.power») или обычный."""
    if identifier in result.sensor_sources:
        return result.sensor_sources[identifier]
    kind = component.rstrip("0123456789")  # «gpu0» → «gpu»
    generic = kind + identifier[len(component) :]
    if generic in result.sensor_sources:
        return result.sensor_sources[generic]
    return definition.source if definition else ""


@dataclass(frozen=True)
class SeriesStats:
    """Минимум, среднее и максимум датчика за тест — только по реально полученным точкам."""

    minimum: float
    average: float
    maximum: float
    count: int
    first_s: float
    last_s: float
    unit: str
    source: str


def series_stats(result: TestResult, identifier: str) -> SeriesStats | None:
    """Статистика датчика `identifier` («gpu0.temperature»); нет точек — None, а не нули."""
    points = [p for p in series_points(result) if p.sensor_id == identifier]
    if not points:
        return None
    values = [p.value for p in points]
    return SeriesStats(
        minimum=min(values),
        average=sum(values) / len(values),
        maximum=max(values),
        count=len(values),
        first_s=points[0].elapsed_seconds,
        last_s=points[-1].elapsed_seconds,
        unit=points[0].unit,
        source=points[0].source,
    )


def _finite(value: object) -> float | None:
    """Конечное число из значения датчика; None, если это не число, NaN или бесконечность."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def series_points(result: TestResult) -> list[SeriesPoint]:
    """Все замеры теста как точки временного ряда (без выдуманных значений и времени)."""
    start = _start(result)
    points: list[SeriesPoint] = []
    for sample in result.samples:
        moment = (
            (start + timedelta(seconds=sample.t)).isoformat(timespec="seconds") if start else ""
        )
        for key, value in sample.values.items():
            number = _finite(value)
            if number is None:
                continue  # датчик промолчал или прислал не число (NaN, текст) — точки нет
            definition = sensor_def(sample.component, key)
            identifier = sensor_id(sample.component, key)
            source = _source(result, sample.component, identifier, definition)
            points.append(
                SeriesPoint(
                    timestamp=moment,
                    elapsed_seconds=sample.t,
                    sensor_id=identifier,
                    value=number,
                    unit=definition.unit if definition else "",
                    source=source,
                )
            )
    return points
