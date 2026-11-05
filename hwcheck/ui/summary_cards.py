"""Сводка «Что найдено» карточками по компонентам (задача 22.5).

Из снимка железа собирается список карточек: плата, BIOS, процессор, память, видеокарты,
накопители, Windows, журнал событий и (у ноутбуков) батарея. В карточке — иконка, заголовок,
2–7 ключевых параметров и цветной статус. Здесь только данные; рисует их
`widgets/summary_grid.py`.

Статус — короткая подсказка по уже собранным сведениям, а не вердикт: вердикт выносится
после тестов. Пороги износа, секторов и ширины шины берутся из `thresholds.json`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from hwcheck.knowledge.gpu_db import IdentStatus, identify
from hwcheck.models import (
    BatteryInfo,
    DiskInfo,
    EventSummary,
    GpuInfo,
    HardwareSnapshot,
    MemoryModule,
    vram_text,
)
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.ui import strings

# Windows, установленная за столько дней до проверки, могла «стереть» историю сбоев.
RECENT_INSTALL_DAYS = 14
# Начала строк-заглушек, которые сборные компьютеры пишут вместо производителя и модели.
OEM_PLACEHOLDERS = (
    "system manufacturer",
    "system product name",
    "to be filled",
    "default string",
    "not applicable",
    "o.e.m.",
    "rev x.0x",  # ревизия платы ASUS без значения (ручная проверка 2.1.0-rc1)
)
# Счётчики журнала, которые показываем в карточке: ключ сборщика → название.
EVENT_PARAMS = [
    ("whea", "Аппаратные сбои (WHEA)"),
    ("bugcheck", "Синие экраны"),
    ("kernel_power_41", "Внезапные выключения"),
    ("disk", "Ошибки дисков"),
]

OK, INFO, WARNING, CRITICAL = "ok", "info", "warning", "critical"


@dataclass
class SummaryCard:
    """Одна карточка сводки."""

    key: str  # board / bios / cpu / memory / gpu0 / disk0 / windows / events / battery / errors
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


def _number(value: int) -> str:
    """12345 → «12 345» (разряды через пробел, как принято в русском тексте)."""
    return f"{value:,}".replace(",", " ")


def _decimal(value: float) -> str:
    """46.6 → «46,6» (десятичная запятая)."""
    return f"{value:.1f}".replace(".", ",")


def hours_text(hours: int) -> str:
    """Наработка: «14 210 ч (≈1,6 г.)» или «3 120 ч (≈4 мес.)»."""
    years = hours / 8760
    if years >= 1:
        return f"{_number(hours)} ч (≈{_decimal(years)} г.)"
    months = round(hours / 730)
    return f"{_number(hours)} ч (≈{months} мес.)" if months else f"{_number(hours)} ч"


def written_text(terabytes: float) -> str:
    """Сколько записано на SSD: «46,6 ТБ», а меньше терабайта — в гигабайтах."""
    return f"{_decimal(terabytes)} ТБ" if terabytes >= 1 else f"{terabytes * 1000:.0f} ГБ"


def moment(text: str | None) -> datetime | None:
    """Дата из снимка → местное время без пояса (чтобы даты можно было вычитать)."""
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def uptime_text(seconds: float) -> str:
    """Сколько компьютер работает без перезагрузки: «2 ч 59 мин» или «3 дн. 4 ч»."""
    minutes = int(seconds // 60)
    days, hours, minutes = minutes // 1440, minutes // 60 % 24, minutes % 60
    if days:
        return f"{days} дн. {hours} ч"
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


def modules_text(modules: list[MemoryModule]) -> str:
    """Планки по группам: «16 ГБ Kingston ×2» или «8 ГБ Kingston ×2, 8 ГБ Corsair»."""
    groups = Counter(
        f"{m.capacity_mb / 1024:g} ГБ {m.manufacturer.strip()}".strip()
        for m in modules
        if m.capacity_mb
    )
    return ", ".join(name + (f" ×{count}" if count > 1 else "") for name, count in groups.items())


def is_placeholder(text: str) -> bool:
    """Заглушка вместо названия у сборных компьютеров: «System Product Name», «To be filled…»."""
    value = text.strip().lower()
    return not value or value.startswith(OEM_PLACEHOLDERS)


def is_placeholder_serial(text: str) -> bool:
    """Серийный номер-заглушка: одни нули или F («00000000», «FFFFFFFF», «0x00000000»)."""
    value = text.strip().lower().removeprefix("0x")
    return len(value) >= 4 and (set(value) == {"0"} or set(value) == {"f"})


def computer_name(manufacturer: str, model: str) -> str:
    """Название компьютера без заглушек. Модель — заглушка → пусто (показывать нечего)."""
    if is_placeholder(model):
        return ""
    return " ".join(part.strip() for part in (manufacturer, model) if not is_placeholder(part))


def _board(snapshot: HardwareSnapshot) -> SummaryCard | None:
    board, system = snapshot.board, snapshot.system
    if board is None and system is None:
        return None
    params = [
        ("Производитель", _value(board.manufacturer if board else system and system.manufacturer)),
        ("Модель", _value(board.product if board else system and system.model)),
    ]
    if system and computer_name(system.manufacturer, system.model):
        kind = "Ноутбук" if system.is_laptop else "Компьютер"
        params.append((kind, computer_name(system.manufacturer, system.model)))
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
    if cpu.socket.strip():
        params.append(("Сокет", cpu.socket.strip()))
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
    if modules_text(modules):
        params.append(("Модули", modules_text(modules)))
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


def pcie_text(gpu: GpuInfo) -> str:
    """Шина видеокарты: «PCIe 4.0 ×16». В простое поколение снижается — берём максимальное."""
    generation = gpu.pcie_gen_max or gpu.pcie_gen_current
    width = gpu.pcie_width_current or gpu.pcie_width_max
    if not (generation or width):
        return ""
    text = f"PCIe {generation}.0" if generation else "PCIe"
    return f"{text} ×{width}" if width else text


def _gpu(index: int, gpu: GpuInfo, thresholds: Thresholds) -> SummaryCard:
    ident = identify(gpu)
    params = [
        ("Модель", _value(gpu.name)),
        ("Видеопамять", vram_text(gpu) or strings.CARD_UNKNOWN),
        ("Драйвер", _value(gpu.driver_version)),
    ]
    if ident.real_chip:
        params.append(("Чип", ident.real_chip))
    if pcie_text(gpu):
        params.append(("Шина", pcie_text(gpu)))
    power = gpu.enforced_power_limit_w or gpu.default_power_limit_w
    if power:
        params.append(("Лимит мощности", f"{power:.0f} Вт"))

    current, maximum = gpu.pcie_width_current, gpu.pcie_width_max
    if ident.status is IdentStatus.FAKE:
        status, text = CRITICAL, strings.CARD_GPU_FAKE
    elif current and maximum and current < maximum * thresholds.get("gpu.pcie_width_ratio"):
        status, text = WARNING, strings.CARD_GPU_PCIE.format(current=current, maximum=maximum)
    elif ident.status is IdentStatus.MATCH:
        status, text = OK, strings.CARD_GPU_MATCH
    else:
        status, text = OK, strings.CARD_READ_OK
    return SummaryCard(f"gpu{index}", "🎮", strings.CARD_GPU, params, status, text)


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
    spare, spare_limit = smart.available_spare_pct, smart.available_spare_threshold_pct
    if spare is not None and spare_limit is not None and spare <= spare_limit:
        return WARNING, strings.CARD_DISK_SPARE_LOW
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
    smart = disk.smart
    if smart and smart.wear_percent is not None:
        params.append(("Износ", f"{smart.wear_percent:.0f}%"))
    if smart and smart.power_on_hours is not None:
        params.append(("Наработка", hours_text(smart.power_on_hours)))
    if smart and smart.data_written_tb is not None:
        params.append(("Записано", written_text(smart.data_written_tb)))
    if smart and smart.temperature_c is not None:
        params.append(("Температура", f"{smart.temperature_c:.0f} °C"))
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
    installed, booted = moment(system.install_date), moment(system.last_boot)
    checked = moment(snapshot.collected_at)
    if installed:
        params.append(("Установлена", installed.strftime("%d.%m.%Y")))
    if booted and checked and checked >= booted:
        params.append(("Без перезагрузки", uptime_text((checked - booted).total_seconds())))
    if installed and checked and 0 <= (checked - installed).days <= RECENT_INSTALL_DAYS:
        return SummaryCard(
            "windows", "💻", strings.CARD_WINDOWS, params, INFO, strings.CARD_WINDOWS_RECENT
        )
    return SummaryCard("windows", "💻", strings.CARD_WINDOWS, params, OK, strings.CARD_READ_OK)


def _events(events: EventSummary | None) -> SummaryCard | None:
    if events is None:
        return None
    params = [(name, str(events.counts.get(key, 0))) for key, name in EVENT_PARAMS]
    title = f"{strings.CARD_EVENTS} ({events.days} дн.)"
    if any(events.counts.get(key, 0) > 0 for key, _ in EVENT_PARAMS):
        status, text = WARNING, strings.CARD_EVENTS_FOUND.format(days=events.days)
    elif events.partial:
        status, text = INFO, strings.CARD_EVENTS_PARTIAL
    else:
        status, text = OK, strings.CARD_EVENTS_OK.format(days=events.days)
    return SummaryCard("events", "📋", title, params, status, text)


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
    cards += [_gpu(i, gpu, limits) for i, gpu in enumerate(snapshot.gpus)]
    cards += [_disk(i, disk, limits) for i, disk in enumerate(snapshot.disks)]
    cards += [_windows(snapshot), _events(snapshot.events)]
    cards += [_battery(snapshot, limits), _errors(snapshot)]
    return [card for card in cards if card is not None]
