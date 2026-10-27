"""Сводка «Что найдено» карточками по компонентам (задача 22.5).

Из снимка железа собирается список карточек: плата, BIOS, процессор, память, видеокарты,
накопители, Windows и (у ноутбуков) батарея. В карточке — иконка, заголовок, 2–4 ключевых
параметра и цветной статус. Здесь только данные; рисует их `widgets/summary_grid.py`.

Статус — короткая подсказка по уже собранным сведениям, а не вердикт: вердикт выносится
после тестов. Пороги износа и секторов берутся из `thresholds.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hwcheck.models import BatteryInfo, DiskInfo, GpuInfo, HardwareSnapshot, vram_text
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.ui import strings

OK, INFO, WARNING, CRITICAL = "ok", "info", "warning", "critical"


@dataclass
class SummaryCard:
    """Одна карточка сводки."""

    key: str  # board / bios / cpu / memory / gpu0 / disk0 / windows / battery / errors
    icon: str
    title: str
    params: list[tuple[str, str]] = field(default_factory=list)  # (название, значение)
    status: str = OK
    status_text: str = ""

    def plain_text(self) -> str:
        """Текст карточки одной строкой (для журнала и тестов)."""
        values = "; ".join(f"{name}: {value}" for name, value in self.params)
        return f"{self.title} — {values} — {self.status_text}"


def _value(text: str | None) -> str:
    return (text or "").strip() or strings.CARD_UNKNOWN


def _size_gb(size: float) -> str:
    if not size:
        return strings.CARD_UNKNOWN
    return f"{size / 1024:.1f} ТБ" if size >= 1000 else f"{size:.0f} ГБ"


def _board(snapshot: HardwareSnapshot) -> SummaryCard | None:
    board, system = snapshot.board, snapshot.system
    if board is None and system is None:
        return None
    params = [
        ("Производитель", _value(board.manufacturer if board else system and system.manufacturer)),
        ("Модель", _value(board.product if board else system and system.model)),
    ]
    if system and system.model:
        kind = "Ноутбук" if system.is_laptop else "Компьютер"
        params.append((kind, f"{system.manufacturer} {system.model}".strip()))
    return SummaryCard("board", "🧩", strings.CARD_BOARD, params, OK, strings.CARD_READ_OK)


def _bios(snapshot: HardwareSnapshot) -> SummaryCard | None:
    system = snapshot.system
    if system is None or not (system.bios_version or system.bios_date or system.bios_vendor):
        return None
    params = [
        ("Версия", _value(system.bios_version)),
        ("Дата", _value((system.bios_date or "")[:10])),
    ]
    if system.bios_vendor:
        params.append(("Производитель", system.bios_vendor))
    return SummaryCard("bios", "⚙️", strings.CARD_BIOS, params, OK, strings.CARD_READ_OK)


def _cpu(snapshot: HardwareSnapshot) -> SummaryCard | None:
    cpu = snapshot.cpu
    if cpu is None:
        return None
    params = [
        ("Модель", _value(cpu.name)),
        ("Ядра / потоки", f"{cpu.cores} / {cpu.threads}" if cpu.cores else strings.CARD_UNKNOWN),
    ]
    if cpu.max_clock_mhz:
        params.append(("Частота", f"до {cpu.max_clock_mhz / 1000:.1f} ГГц"))
    return SummaryCard("cpu", "🔲", strings.CARD_CPU, params, OK, strings.CARD_READ_OK)


def _memory(snapshot: HardwareSnapshot) -> SummaryCard | None:
    memory = snapshot.memory
    if memory is None:
        return None
    modules = memory.modules
    slots = f"занято {len(modules)}" + (f" из {memory.slots_total}" if memory.slots_total else "")
    speeds = [m.configured_speed_mhz or m.speed_mhz for m in modules]
    known = [s for s in speeds if s]
    params = [
        ("Объём", f"{memory.total_mb / 1024:.0f} ГБ" if memory.total_mb else strings.CARD_UNKNOWN),
        ("Планки", slots if modules else strings.CARD_UNKNOWN),
        ("Частота", f"{min(known)} МГц" if known else strings.CARD_UNKNOWN),
    ]
    if len(modules) == 1:
        return SummaryCard(
            "memory", "🧠", strings.CARD_MEMORY, params, INFO, strings.CARD_MEMORY_SINGLE
        )
    rated = [m.speed_mhz for m in modules if m.speed_mhz]
    if known and rated and min(known) < max(rated):
        return SummaryCard(
            "memory", "🧠", strings.CARD_MEMORY, params, INFO, strings.CARD_MEMORY_SLOW
        )
    return SummaryCard("memory", "🧠", strings.CARD_MEMORY, params, OK, strings.CARD_READ_OK)


def _gpu(index: int, gpu: GpuInfo) -> SummaryCard:
    params = [
        ("Модель", _value(gpu.name)),
        ("Видеопамять", vram_text(gpu) or strings.CARD_UNKNOWN),
        ("Драйвер", _value(gpu.driver_version)),
    ]
    return SummaryCard(f"gpu{index}", "🎮", strings.CARD_GPU, params, OK, strings.CARD_READ_OK)


def disk_status(disk: DiskInfo, thresholds: Thresholds) -> tuple[str, str]:
    """Статус накопителя по SMART: (статус, пояснение)."""
    smart = disk.smart
    if smart is None:
        return INFO, strings.CARD_DISK_NO_SMART
    sectors = sum(
        value or 0
        for value in (smart.reallocated_sectors, smart.pending_sectors, smart.uncorrectable_sectors)
    )
    if smart.health_passed is False or sectors >= thresholds.get("disk.sectors_critical"):
        return CRITICAL, strings.CARD_DISK_CRITICAL
    if sectors >= thresholds.get("disk.sectors_warning") or (smart.media_errors or 0) > 0:
        return WARNING, strings.CARD_DISK_WARNING
    return OK, strings.CARD_DISK_OK


def _disk(index: int, disk: DiskInfo, thresholds: Thresholds) -> SummaryCard:
    kind = {"ssd": "SSD", "hdd": "HDD"}.get(disk.media_type, strings.CARD_UNKNOWN)
    bus = disk.bus_type.upper() if disk.bus_type else ""
    params = [
        ("Модель", _value(disk.model)),
        ("Объём", _size_gb(disk.size_gb)),
        ("Тип", f"{kind}, {bus}" if bus else kind),
    ]
    if disk.smart and disk.smart.wear_percent is not None:
        params.append(("Износ", f"{disk.smart.wear_percent:.0f}%"))
    status, text = disk_status(disk, thresholds)
    return SummaryCard(f"disk{index}", "💽", strings.CARD_DISK, params, status, text)


def _windows(snapshot: HardwareSnapshot) -> SummaryCard | None:
    system = snapshot.system
    if system is None or not (system.os_name or system.os_build):
        return None
    params = [
        ("Версия", _value(system.os_name)),
        ("Сборка", _value(system.os_build or system.os_version)),
        ("Разрядность", _value(system.architecture)),
    ]
    return SummaryCard("windows", "💻", strings.CARD_WINDOWS, params, OK, strings.CARD_READ_OK)


def battery_status(battery: BatteryInfo, thresholds: Thresholds) -> tuple[str, str]:
    """Статус батареи по износу: (статус, пояснение)."""
    wear = battery.wear_percent
    if wear is None:
        return INFO, strings.CARD_BATTERY_UNKNOWN
    if wear >= thresholds.get("battery.wear_bargain_pct"):
        return CRITICAL, strings.CARD_BATTERY_BAD
    if wear >= thresholds.get("battery.wear_warning_pct"):
        return WARNING, strings.CARD_BATTERY_WORN
    return OK, strings.CARD_BATTERY_OK


def _battery(snapshot: HardwareSnapshot, thresholds: Thresholds) -> SummaryCard | None:
    battery = snapshot.battery
    if battery is None:
        return None
    wear = battery.wear_percent
    params = [
        ("Износ", f"{wear:.0f}%" if wear is not None else strings.CARD_UNKNOWN),
        (
            "Циклов",
            str(battery.cycle_count) if battery.cycle_count is not None else strings.CARD_UNKNOWN,
        ),
    ]
    if battery.full_charge_capacity_mwh:
        params.append(("Ёмкость", f"{battery.full_charge_capacity_mwh / 1000:.0f} Вт·ч"))
    status, text = battery_status(battery, thresholds)
    return SummaryCard("battery", "🔋", strings.CARD_BATTERY, params, status, text)


def _errors(snapshot: HardwareSnapshot) -> SummaryCard | None:
    if not snapshot.errors:
        return None
    params = [
        (strings.COLLECTOR_NAMES.get(name, name), error)
        for name, error in list(snapshot.errors.items())[:4]
    ]
    return SummaryCard(
        "errors", "❔", strings.CARD_ERRORS, params, WARNING, strings.CARD_ERRORS_HINT
    )


def build_cards(
    snapshot: HardwareSnapshot, thresholds: Thresholds | None = None
) -> list[SummaryCard]:
    """Карточки сводки в порядке показа. Отсутствующие сведения — без карточки."""
    limits = thresholds or load_thresholds()
    cards = [_board(snapshot), _bios(snapshot), _cpu(snapshot), _memory(snapshot)]
    cards += [_gpu(i, gpu) for i, gpu in enumerate(snapshot.gpus)]
    cards += [_disk(i, disk, limits) for i, disk in enumerate(snapshot.disks)]
    cards += [_windows(snapshot), _battery(snapshot, limits), _errors(snapshot)]
    return [card for card in cards if card is not None]
