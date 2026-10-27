"""Модели данных программы: всё, что мы узнали о компьютере, и результаты проверок.

Каждая модель — простой dataclass. Любую модель можно превратить в словарь/JSON
(`to_dict`, `to_json`) и обратно (`from_dict`, `from_json`). Это нужно, чтобы
сохранять снимки железа в файлы, хранить сценарии демо-режима и строить отчёты.

Поток данных: сборщики → HardwareSnapshot → нагрузочные тесты → TestResult[] →
правила → Finding[] → движок → Verdict.
"""

from __future__ import annotations

import dataclasses
import json
import re
import types
import typing
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Self

# --------------------------------------------------------------------------
# Перечисления
# --------------------------------------------------------------------------


class TestStatus(StrEnum):
    """Итог одного теста."""

    __test__ = False  # подсказка pytest: это не тестовый класс

    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    ERROR = "error"


class Severity(StrEnum):
    """Важность находки: от «всё плохо» до «всё хорошо»."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    OK = "ok"


class Decision(StrEnum):
    """Итоговое решение для покупателя."""

    BUY = "buy"
    NEGOTIATE = "negotiate"
    WALK_AWAY = "walk_away"


# --------------------------------------------------------------------------
# Общая логика превращения в JSON и обратно
# --------------------------------------------------------------------------


class JsonModel:
    """Базовый класс: добавляет моделям методы to_dict/to_json/from_dict/from_json."""

    def to_dict(self) -> dict[str, Any]:
        """Превращает модель в словарь из простых типов (готов для json.dumps)."""
        if not dataclasses.is_dataclass(self):
            raise TypeError(f"{type(self).__name__} не является dataclass")
        return _plain(dataclasses.asdict(self))

    def to_json(self, indent: int | None = 2) -> str:
        """Превращает модель в строку JSON (кириллица сохраняется как есть)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Создаёт модель из словаря. Лишние ключи игнорируются, недостающие — по умолчанию."""
        return _from_dict(cls, data)

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Создаёт модель из строки JSON."""
        return cls.from_dict(json.loads(text))


def _plain(value: Any) -> Any:
    """Заменяет перечисления на их строковые значения, рекурсивно."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _from_dict[T](cls: type[T], data: dict[str, Any]) -> T:
    """Создаёт dataclass `cls` из словаря, приводя вложенные значения к нужным типам."""
    if not isinstance(data, dict):
        raise TypeError(f"Для {cls.__name__} ожидался словарь, получено {type(data).__name__}")
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls.__name__} не является dataclass")
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in data:
            kwargs[f.name] = _convert(hints[f.name], data[f.name])
    return cls(**kwargs)


def _convert(tp: Any, value: Any) -> Any:
    """Приводит значение из JSON к типу `tp` (вложенные модели, списки, перечисления)."""
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        options = [arg for arg in typing.get_args(tp) if arg is not type(None)]
        # Optional[X] → приводим к X; для смешанных типов оставляем значение как есть.
        return _convert(options[0], value) if len(options) == 1 else value
    if origin is list:
        (item_type,) = typing.get_args(tp)
        return [_convert(item_type, item) for item in value]
    if origin is dict:
        _key_type, value_type = typing.get_args(tp)
        return {key: _convert(value_type, item) for key, item in value.items()}
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return _from_dict(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is float and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
    return value


# --------------------------------------------------------------------------
# Сведения о железе
# --------------------------------------------------------------------------


@dataclass
class SystemInfo(JsonModel):
    """Операционная система, модель компьютера и BIOS материнской платы."""

    os_name: str = ""
    os_version: str = ""
    os_build: str = ""
    architecture: str = ""
    install_date: str | None = None
    last_boot: str | None = None
    manufacturer: str = ""
    model: str = ""
    is_laptop: bool = False
    bios_vendor: str = ""
    bios_version: str = ""
    bios_date: str | None = None


@dataclass
class CpuInfo(JsonModel):
    """Процессор."""

    name: str = ""
    manufacturer: str = ""
    cores: int = 0
    threads: int = 0
    max_clock_mhz: int | None = None
    current_clock_mhz: int | None = None
    socket: str = ""


@dataclass
class MemoryModule(JsonModel):
    """Одна планка оперативной памяти."""

    capacity_mb: int = 0
    speed_mhz: int | None = None
    configured_speed_mhz: int | None = None
    manufacturer: str = ""
    part_number: str = ""
    slot: str = ""


@dataclass
class MemoryInfo(JsonModel):
    """Оперативная память: общий объём и список планок."""

    total_mb: int = 0
    available_mb: int | None = None
    modules: list[MemoryModule] = field(default_factory=list)
    slots_total: int | None = None


@dataclass
class BoardInfo(JsonModel):
    """Материнская плата."""

    manufacturer: str = ""
    product: str = ""
    version: str = ""


@dataclass
class GpuInfo(JsonModel):
    """Видеокарта: что о ней говорит Windows и (для NVIDIA) драйвер."""

    vendor: str = ""
    name: str = ""
    pci_vendor_id: str = ""
    pci_device_id: str = ""
    subsystem_id: str = ""
    vram_mb: int | None = None
    vbios_version: str = ""
    driver_version: str = ""
    default_power_limit_w: float | None = None
    enforced_power_limit_w: float | None = None
    max_power_limit_w: float | None = None
    max_clocks: dict[str, int] = field(default_factory=dict)
    pcie_gen_current: int | None = None
    pcie_gen_max: int | None = None
    pcie_width_current: int | None = None
    pcie_width_max: int | None = None
    fan_speed_percent: float | None = None
    throttle_reasons: list[str] = field(default_factory=list)
    pnp_device_id: str = ""
    source: str = ""


@dataclass
class SmartData(JsonModel):
    """Нормализованные данные S.M.A.R.T. — «медицинская карта» накопителя."""

    power_on_hours: int | None = None
    power_cycles: int | None = None
    reallocated_sectors: int | None = None
    pending_sectors: int | None = None
    uncorrectable_sectors: int | None = None
    wear_percent: float | None = None
    temperature_c: float | None = None
    crc_errors: int | None = None
    media_errors: int | None = None
    health_passed: bool | None = None
    source: str = ""


# Встроенная графика AMD называется «… Radeon(TM) Graphics», «… Vega 8 Graphics», «… 780M Graphics»;
# у дискретных карт в названии есть серия RX / Pro / R9 и т.п.
_AMD_DISCRETE_SERIES = re.compile(r"\b(RX|PRO|R[579]|FURY|VII|HD|FIREPRO|W\d{4})\b", re.IGNORECASE)


def is_discrete_gpu(gpu: GpuInfo) -> bool:
    """Отдельная (дискретная) видеокарта NVIDIA/AMD, а не встроенная в процессор графика."""
    if gpu.vendor == "NVIDIA":
        return True
    if gpu.vendor != "AMD":
        return False  # Intel UHD/Iris и прочие — встроенная графика
    name = gpu.name.strip()
    return bool(_AMD_DISCRETE_SERIES.search(name)) or not name.lower().endswith("graphics")


def vram_text(gpu: GpuInfo) -> str:
    """Объём видеопамяти для людей: «12 ГБ», «512 МБ», «общая с ОЗУ» или ""."""
    if not is_discrete_gpu(gpu) and gpu.vendor in ("AMD", "Intel"):
        return "общая с ОЗУ"
    if not gpu.vram_mb:
        return ""
    if gpu.vram_mb < 1024:
        return f"{gpu.vram_mb} МБ"
    return f"{gpu.vram_mb / 1024:.0f} ГБ"


@dataclass
class DiskInfo(JsonModel):
    """Накопитель (SSD, HDD, флешка)."""

    model: str = ""
    size_gb: float = 0.0
    media_type: str = "unknown"  # ssd / hdd / unknown
    bus_type: str = ""  # nvme / sata / usb / ...
    device: str = ""
    smart: SmartData | None = None
    note: str = ""


@dataclass
class BatteryInfo(JsonModel):
    """Батарея ноутбука."""

    design_capacity_mwh: int = 0
    full_charge_capacity_mwh: int = 0
    cycle_count: int | None = None
    manufacturer: str = ""
    chemistry: str = ""
    runtime_minutes: int | None = None  # оценка Windows: работа от полной зарядки сейчас
    design_runtime_minutes: int | None = None  # то же для новой батареи

    @property
    def wear_percent(self) -> float | None:
        """Износ батареи в процентах: насколько полная ёмкость меньше проектной."""
        if self.design_capacity_mwh <= 0:
            return None
        ratio = self.full_charge_capacity_mwh / self.design_capacity_mwh
        return round(max(0.0, (1.0 - ratio) * 100.0), 1)


@dataclass
class EventSummary(JsonModel):
    """Сводка тревожных событий из журнала Windows за последние дни."""

    days: int = 30
    counts: dict[str, int] = field(default_factory=dict)
    last_seen: dict[str, str] = field(default_factory=dict)
    partial: bool = False
    note: str = ""


@dataclass
class HardwareSnapshot(JsonModel):
    """Всё, что удалось узнать о компьютере без нагрузки."""

    collected_at: str = ""
    is_admin: bool = False
    system: SystemInfo | None = None
    cpu: CpuInfo | None = None
    memory: MemoryInfo | None = None
    board: BoardInfo | None = None
    gpus: list[GpuInfo] = field(default_factory=list)
    disks: list[DiskInfo] = field(default_factory=list)
    battery: BatteryInfo | None = None
    events: EventSummary | None = None
    # Имя сборщика → почему не удалось проверить (показываем в «что не проверено»).
    errors: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Результаты тестов и вердикт
# --------------------------------------------------------------------------


@dataclass
class SensorSample(JsonModel):
    """Один замер датчиков: время от начала теста и набор значений."""

    t: float = 0.0
    component: str = ""  # например "gpu0" или "cpu"
    values: dict[str, float | None] = field(default_factory=dict)


@dataclass
class TestResult(JsonModel):
    """Итог одного нагрузочного теста."""

    __test__ = False  # подсказка pytest: это не тестовый класс

    name: str = ""
    status: TestStatus = TestStatus.SKIPPED
    component: str = ""
    duration_s: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    samples: list[SensorSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Finding(JsonModel):
    """Одна находка: проблема, предупреждение или «всё хорошо» с пояснением для покупателя."""

    id: str = ""
    severity: Severity = Severity.INFO
    component: str = ""
    title: str = ""
    explanation: str = ""
    advice: str = ""
    evidence: str = ""
    weight: float = 0.0


@dataclass
class Verdict(JsonModel):
    """Итоговый вердикт: решение, причины и что проверить не удалось."""

    decision: Decision = Decision.BUY
    findings: list[Finding] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)
    score: float = 0.0
    bargaining_points: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class ListingClaims(JsonModel):
    """Что удалось узнать из объявления о продаже и что в нём заявлено."""

    url: str = ""
    site: str = ""
    title: str = ""
    price_rub: int | None = None
    description: str = ""
    params: dict[str, str] = field(default_factory=dict)
    seller_name: str = ""
    seller_since: str = ""
    seller_listings: int | None = None
    city: str = ""
    analyzed_at: str = ""
    # Заявленное железо (распознано из заголовка, характеристик и описания).
    gpu_model: str = ""
    gpu_vram_gb: float | None = None
    cpu_model: str = ""
    ram_gb: float | None = None
    # Результаты анализа (тревожные признаки и рыночная цена).
    flags: list[Finding] = field(default_factory=list)
    market_median_rub: int | None = None
    market_count: int = 0


@dataclass
class CheckSession(JsonModel):
    """Одна проверка целиком: что за компьютер, какие тесты прошли и итоговый вердикт."""

    id: str = ""
    started_at: str = ""
    finished_at: str = ""
    mode: str = "quick"  # quick / full / short
    demo_scenario: str = ""
    app_version: str = ""
    snapshot: HardwareSnapshot = field(default_factory=HardwareSnapshot)
    results: list[TestResult] = field(default_factory=list)
    verdict: Verdict | None = None
    listing: ListingClaims | None = None
