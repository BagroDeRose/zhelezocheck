"""Данные технического отчёта «Для специалиста» (SPEC_V2_1, этап 43; MVP-спека, 4 и 8.3).

Из одного снимка проверки строятся паспорт и разделы: плата и BIOS, процессор, видеокарты,
память, накопители, блок питания, система, ноутбук, тесты, находки, неполученные данные,
источники. Каждая строка — значение, источник, статус («получено», «не поддерживается»,
«не удалось получить») и пояснение.

Правила честности (они важнее «красивого» отчёта):
- нет значения — строка «Не удалось получить» или «Не поддерживается оборудованием» с
  причиной, никаких подставленных нулей;
- статистика под нагрузкой считается только по реально полученным точкам;
- неоднозначное значение показывается целиком с пометкой «требует интерпретации»;
- оговорки о пределах программной проверки (блок питания, быстрый тест памяти,
  тепловая зона вместо ядер CPU) пишутся прямо в строках.

Модуль не импортирует `builder.py` (тот подключает этот модуль), события и объявление
добавляет в контекст сам `builder`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hwcheck import __version__
from hwcheck.knowledge.gpu_db import identify
from hwcheck.knowledge.smart import ata_title, interpret_attribute, nvme_rows
from hwcheck.laptop.details import laptop_details
from hwcheck.models import (
    SCHEMA_VERSION,
    Availability,
    CheckSession,
    CheckState,
    DiskInfo,
    GpuInfo,
    SmartData,
    TestResult,
    check_state,
    vram_text,
)
from hwcheck.report.labels import metric_rows, readable_evidence
from hwcheck.schema import series_stats
from hwcheck.ui import strings
from hwcheck.ui.summary_cards import is_placeholder, is_placeholder_serial
from hwcheck.verdict.assessment import assess_components

NOT_RECEIVED = "Не удалось получить"
NOT_SUPPORTED = "Не поддерживается оборудованием"
NEEDS_INTERPRETATION = "требует интерпретации"

STATUS_NAMES = {
    Availability.AVAILABLE: "получено",
    Availability.UNSUPPORTED: "не поддерживается",
    Availability.UNAVAILABLE: "не удалось получить",
}
STATE_NAMES = {
    CheckState.NOT_CHECKED: "не проверено",
    CheckState.PASSED: "проверено — ошибок нет",
    CheckState.PROBLEMS: "проверено — обнаружены проблемы",
    CheckState.INTERRUPTED: "проверка прервана",
}

# Источники данных (как их называют в отчёте).
SRC_APP = "ЖелезоЧек"
SRC_OS = "WMI: Win32_OperatingSystem"
SRC_CS = "WMI: Win32_ComputerSystem"
SRC_BIOS = "WMI: Win32_BIOS"
SRC_BOARD = "WMI: Win32_BaseBoard"
SRC_CPU = "WMI: Win32_Processor"
SRC_RAM = "WMI: Win32_PhysicalMemory"
SRC_SECURE_BOOT = "Реестр: SecureBoot\\State"
SRC_GPU_DB = "Справочник видеокарт ЖелезоЧек"
SRC_PCI_IDS = "База PCI ID (pci.ids)"
SRC_BATTERY = "powercfg /batteryreport"
SRC_NONE = "—"

REASON_DRIVER = (
    "Windows не отдаёт этот датчик без драйвера уровня ядра; программа драйверы не "
    "устанавливает (работает с флешки, только чтение)."
)
# Ручная проверка 2.1.0-rc1: на ASUS B360 зона ACPI весь тест показывала 27,9 °C.
ZONE_FROZEN_NOTE = (
    "Значение не менялось весь тест: этот датчик платы не отражает нагрев процессора. "
    "В вердикте не используется; температура процессора считается не измеренной."
)
REASON_ADMIN = "Windows даёт прочитать только с правами администратора."
REASON_NOT_COLLECTED = "Не собирается в этой версии программы."
REASON_NO_VALUE = "Источник не сообщил значение."
REASON_NO_LOAD = "Нагрузочный тест не проводился или датчик не отвечал во время теста."


@dataclass(frozen=True)
class Row:
    """Строка технического отчёта."""

    label: str
    value: str
    source: str
    status: Availability = Availability.AVAILABLE
    note: str = ""

    @property
    def status_name(self) -> str:
        return STATUS_NAMES[self.status]


@dataclass
class Section:
    title: str
    anchor: str
    rows: list[Row] = field(default_factory=list)

    def add(self, row: Row) -> None:
        self.rows.append(row)


# --------------------------------------------------------------------------
# Строки
# --------------------------------------------------------------------------


def value_row(
    label: str,
    value: Any,
    source: str,
    unit: str = "",
    reason: str = REASON_NO_VALUE,
    note: str = "",
) -> Row:
    """Строка со значением; пусто/None — «Не удалось получить» с причиной (не ноль)."""
    if value is None or value == "":
        return unavailable_row(label, reason, source)
    text = f"{value} {unit}".strip() if unit else str(value)
    return Row(label, text, source, Availability.AVAILABLE, note)


REASON_PLACEHOLDER = "Производитель не заполнил это поле: вместо значения стоит заглушка."


NOT_SPECIFIED = "Не указано производителем"


def placeholder_row(label: str, source: str) -> Row:
    """Поле заполнено заглушкой: сам текст заглушки не показываем (решение этапа 44)."""
    return Row(label, NOT_SPECIFIED, source, Availability.UNSUPPORTED, REASON_PLACEHOLDER)


def name_row(
    label: str, value: str | None, source: str, reason: str = REASON_NO_VALUE, note: str = ""
) -> Row:
    """Название, ревизия или серийный номер; заглушка («System manufacturer», «Rev X.0x»,
    «00000000») — не значение (ручная проверка 2.1.0-rc1)."""
    if value and (is_placeholder(value) or is_placeholder_serial(value)):
        return placeholder_row(label, source)
    return value_row(label, value, source, reason=reason, note=note)


def unavailable_row(label: str, reason: str, source: str = SRC_NONE) -> Row:
    return Row(label, NOT_RECEIVED, source or SRC_NONE, Availability.UNAVAILABLE, reason)


def unsupported_row(label: str, reason: str, source: str = SRC_NONE) -> Row:
    return Row(label, NOT_SUPPORTED, source or SRC_NONE, Availability.UNSUPPORTED, reason)


def _yes_no(value: bool | None, yes: str = "включено", no: str = "выключено") -> str | None:
    return None if value is None else (yes if value else no)


def _number(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 10 or value == int(value) else f"{value:.1f}"


def stats_row(label: str, result: TestResult | None, identifier: str, note: str = "") -> Row:
    """Мин/сред/макс датчика под нагрузкой — только из реальных точек ряда."""
    stats = series_stats(result, identifier) if result else None
    if stats is None:
        return unavailable_row(label, REASON_NO_LOAD)
    unit = f" {stats.unit}" if stats.unit else ""
    text = (
        f"мин {_number(stats.minimum)} · сред {_number(stats.average)} · "
        f"макс {_number(stats.maximum)}{unit} "
        f"({stats.count} замеров, {stats.first_s:.0f}–{stats.last_s:.0f} с)"
    )
    return Row(label, text, stats.source or SRC_NONE, Availability.AVAILABLE, note)


def _reason(session: CheckSession, collector: str) -> str:
    """Почему нет данных сборщика: его ошибка из снимка или общая причина."""
    error = session.snapshot.errors.get(collector)
    return f"Сборщик не получил данные: {error}" if error else REASON_NO_VALUE


def _result(session: CheckSession, name: str) -> TestResult | None:
    return next((r for r in session.results if r.name == name), None)


def duration_text(started: str, finished: str) -> str | None:
    try:
        seconds = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).seconds
    except ValueError:
        return None
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} мин {rest} с" if minutes else f"{rest} с"


def _when(text: str) -> str | None:
    try:
        return datetime.fromisoformat(text).strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Паспорт проверки
# --------------------------------------------------------------------------


def tool_versions(session: CheckSession) -> list[str]:
    """Версии утилит и драйверов, реально использованных при проверке."""
    versions: list[str] = []
    for gpu in session.snapshot.gpus:
        if gpu.driver_version:
            versions.append(f"Драйвер видеокарты {gpu.name}: {gpu.driver_version}")
    vram = _result(session, "vram")
    if vram and vram.metrics.get("memtest_version"):
        versions.append(f"memtest_vulkan {vram.metrics['memtest_version']}")
    tools = {
        disk.smart.tool_version
        for disk in session.snapshot.disks
        if disk.smart and disk.smart.tool_version
    }
    versions += [f"smartctl {version}" for version in sorted(tools)]
    return versions


def incompleteness(session: CheckSession) -> list[str]:
    reasons = [
        f"{strings.COLLECTOR_NAMES.get(name, name)}: {error}"
        for name, error in session.snapshot.errors.items()
    ]
    if session.verdict:
        reasons += session.verdict.not_checked
    return reasons


def passport(session: CheckSession) -> Section:
    snap = session.snapshot
    system = snap.system
    section = Section("Паспорт проверки", "passport")
    version = session.app_version or __version__
    section.add(Row("Программа", f"ЖелезоЧек {version}", SRC_APP))
    section.add(Row("Версия схемы отчёта", str(session.schema_version or SCHEMA_VERSION), SRC_APP))
    section.add(value_row("Начало", _when(session.started_at), SRC_APP))
    section.add(value_row("Окончание", _when(session.finished_at), SRC_APP))
    section.add(
        value_row("Длительность", duration_text(session.started_at, session.finished_at), SRC_APP)
    )
    mode = {"quick": "Быстрая", "full": "Полная", "short": "Короткий прогон"}
    section.add(Row("Режим", mode.get(session.mode, session.mode), SRC_APP))
    if session.demo_scenario:
        section.add(
            Row(
                "Демо-режим",
                session.demo_scenario,
                SRC_APP,
                note="Данные учебного сценария, не настоящего компьютера.",
            )
        )
    no_system = _reason(session, "system")
    section.add(
        value_row("Операционная система", system and system.os_name, SRC_OS, reason=no_system)
    )
    build = system and " / ".join(part for part in (system.os_version, system.os_build) if part)
    section.add(value_row("Версия и сборка", build, SRC_OS, reason=no_system))
    section.add(value_row("Архитектура", system and system.architecture, SRC_OS, reason=no_system))
    section.add(
        value_row(
            "Имя компьютера",
            system and system.computer_name,
            SRC_CS,
            note="Скрывается при экспорте с включённым скрытием идентификаторов.",
        )
    )
    rights = "администратор" if snap.is_admin else "обычный пользователь"
    section.add(Row("Права", rights, SRC_APP))
    done = [r for r in session.results if check_state(r) is not CheckState.NOT_CHECKED]
    skipped = [r for r in session.results if check_state(r) is CheckState.NOT_CHECKED]
    section.add(Row("Проведённые тесты", _tests_text(done) or "нет", SRC_APP))
    section.add(Row("Не проведённые тесты", _tests_text(skipped) or "нет", SRC_APP))
    section.add(Row("Утилиты и драйверы", "; ".join(tool_versions(session)) or "—", SRC_APP))
    reasons = [reason.rstrip(". ") for reason in incompleteness(session)]
    section.add(Row("Причины неполноты", "; ".join(reasons) or "нет", SRC_APP))
    return section


def _tests_text(results: list[TestResult]) -> str:
    return "; ".join(
        f"{strings.TEST_NAMES.get(r.name, r.name)} ({STATE_NAMES[check_state(r)]})" for r in results
    )


# --------------------------------------------------------------------------
# Разделы
# --------------------------------------------------------------------------


def board_section(session: CheckSession) -> Section:
    snap = session.snapshot
    board, system = snap.board, snap.system
    section = Section("Материнская плата и BIOS", "board")
    no_board = _reason(session, "board")
    section.add(name_row("Производитель платы", board and board.manufacturer, SRC_BOARD, no_board))
    section.add(name_row("Модель платы", board and board.product, SRC_BOARD, no_board))
    section.add(name_row("Ревизия платы", board and board.version, SRC_BOARD, no_board))
    no_system = _reason(session, "system")
    section.add(
        value_row("Производитель BIOS", system and system.bios_vendor, SRC_BIOS, reason=no_system)
    )
    section.add(
        value_row("Версия BIOS", system and system.bios_version, SRC_BIOS, reason=no_system)
    )
    section.add(
        value_row("Дата BIOS", system and (system.bios_date or "")[:10], SRC_BIOS, reason=no_system)
    )
    section.add(
        value_row(
            "Secure Boot",
            _yes_no(system.secure_boot if system else None),
            SRC_SECURE_BOOT,
            reason="Ключ реестра не найден: загрузка без UEFI Secure Boot или Windows не сообщает.",
        )
    )
    # Ручная проверка 2.1.0-rc1: запуск был с правами администратора, а причина говорила
    # «нужны права». TPM в этой версии не собирается — так и пишем; без прав — честно о правах.
    tpm_reason = REASON_NOT_COLLECTED if session.snapshot.is_admin else REASON_ADMIN
    section.add(unavailable_row("TPM", tpm_reason))
    section.add(unavailable_row("Режим загрузки (UEFI/Legacy)", REASON_NOT_COLLECTED))
    section.add(unavailable_row("Чипсет", "Надёжного источника без драйвера нет."))
    section.add(
        unavailable_row("Датчики платы: температуры, напряжения, вентиляторы", REASON_DRIVER)
    )
    return section


def cpu_section(session: CheckSession) -> Section:
    cpu = session.snapshot.cpu
    section = Section("Процессор", "cpu")
    reason = _reason(session, "cpu")
    section.add(value_row("Модель", cpu and cpu.name, SRC_CPU, reason=reason))
    section.add(value_row("Производитель", cpu and cpu.manufacturer, SRC_CPU, reason=reason))
    section.add(
        value_row("CPUID (family / model / stepping)", cpu and cpu.cpuid, SRC_CPU, reason=reason)
    )
    section.add(value_row("Сокет", cpu and cpu.socket, SRC_CPU, reason=reason))
    section.add(value_row("Физические ядра", cpu and (cpu.cores or None), SRC_CPU, reason=reason))
    section.add(
        value_row("Логические потоки", cpu and (cpu.threads or None), SRC_CPU, reason=reason)
    )
    section.add(
        value_row(
            "Номинальная частота",
            cpu and cpu.max_clock_mhz,
            SRC_CPU,
            "МГц",
            reason,
            note="Так её сообщает Windows (MaxClockSpeed); турбочастота не указывается.",
        )
    )
    section.add(
        value_row(
            "Частота при сборе сведений", cpu and cpu.current_clock_mhz, SRC_CPU, "МГц", reason
        )
    )
    section.add(value_row("Кэш L2", cpu and cpu.l2_cache_kb, SRC_CPU, "КБ", reason))
    section.add(value_row("Кэш L3", cpu and cpu.l3_cache_kb, SRC_CPU, "КБ", reason))
    section.add(
        value_row(
            "Виртуализация в прошивке",
            _yes_no(cpu.virtualization_enabled if cpu else None),
            SRC_CPU,
            reason=reason,
        )
    )
    section.add(
        # Процессор эти сведения не скрывает — их не отдаёт Windows без драйвера, поэтому
        # статус «не удалось получить», а не «не поддерживается оборудованием».
        unavailable_row("Техпроцесс и кодовое имя", "Надёжного источника без драйвера нет.")
    )
    load = _result(session, "cpu_load")
    section.add(stats_row("Частота под нагрузкой", load, "cpu.clock"))
    section.add(stats_row("Загрузка под нагрузкой", load, "cpu.utilization"))
    zone_note = "Датчик ACPI на плате рядом с процессором, не ядра CPU; точность примерная."
    if load is not None and load.metrics.get("zone_temp_frozen"):
        zone_note = ZONE_FROZEN_NOTE
    section.add(
        stats_row("Температура тепловой зоны под нагрузкой", load, "cpu.zone_temp", zone_note)
    )
    section.add(unavailable_row("Температура ядер (Package)", REASON_DRIVER))
    section.add(unavailable_row("Потребление (Package Power)", REASON_DRIVER))
    section.add(unavailable_row("Напряжение ядра", REASON_DRIVER))
    return section


def gpu_section(session: CheckSession, index: int, gpu: GpuInfo) -> Section:
    section = Section(f"Видеокарта {index + 1}: {gpu.name or 'без названия'}", f"gpu{index}")
    source = "WMI: Win32_VideoController" + (" + nvidia-smi" if "nvidia" in gpu.source else "")
    ident = identify(gpu)
    card = ident.real[0] if len(ident.real) == 1 else ident.claimed
    section.add(value_row("Имя в Windows", gpu.name, source))
    section.add(value_row("Производитель GPU", gpu.vendor, source))
    ids = f"{gpu.pci_vendor_id}:{gpu.pci_device_id}" if gpu.pci_device_id else None
    section.add(value_row("PCI Vendor:Device", ids, source))
    section.add(value_row("PCI Subsystem", gpu.subsystem_id, source))
    section.add(value_row("Чип по коду устройства", ident.real_chip, SRC_PCI_IDS))
    section.add(
        value_row(
            "Сверка с названием",
            {"match": "совпадает", "fake": "НЕ совпадает", "unknown": "не удалось сверить"}[
                ident.status.value
            ],
            SRC_GPU_DB,
            note=" ".join(ident.reasons),
        )
    )
    section.add(value_row("Видеопамять", vram_text(gpu), source))
    section.add(
        value_row(
            "Тип памяти",
            card and card.memory_type,
            SRC_GPU_DB,
            reason="Модели нет в справочнике; Windows тип памяти не сообщает.",
        )
    )
    section.add(
        value_row(
            "Шина памяти",
            card and card.bus_width_bits,
            SRC_GPU_DB,
            "бит",
            reason="Модели нет в справочнике; Windows ширину шины не сообщает.",
        )
    )
    section.add(value_row("Версия VBIOS", gpu.vbios_version, source))
    section.add(value_row("Версия драйвера", gpu.driver_version, source))
    narrow = bool(
        gpu.pcie_width_current
        and gpu.pcie_width_max
        and gpu.pcie_width_current < gpu.pcie_width_max
    )
    current = (
        f"PCIe {gpu.pcie_gen_current}.0 ×{gpu.pcie_width_current}"
        if gpu.pcie_gen_current and gpu.pcie_width_current
        else None
    )
    section.add(
        value_row(
            "Шина PCIe (сейчас)",
            current,
            source,
            note=(
                f"Ширина меньше максимальной (×{gpu.pcie_width_max}) — {NEEDS_INTERPRETATION}: "
                "слот, райзер, загрязнение контактов или настройки платы."
                if narrow
                else "В простое поколение PCIe снижается — это норма."
            ),
        )
    )
    maximum = (
        f"PCIe {gpu.pcie_gen_max}.0 ×{gpu.pcie_width_max}"
        if gpu.pcie_gen_max and gpu.pcie_width_max
        else None
    )
    section.add(value_row("Шина PCIe (максимум)", maximum, source))
    low_limit = bool(
        gpu.enforced_power_limit_w
        and gpu.default_power_limit_w
        and gpu.enforced_power_limit_w < gpu.default_power_limit_w * 0.95
    )
    section.add(
        value_row(
            "Лимит мощности (действующий)",
            gpu.enforced_power_limit_w,
            source,
            "Вт",
            note=(
                f"Ниже заводского ({gpu.default_power_limit_w:.0f} Вт) — {NEEDS_INTERPRETATION}: "
                "лимит снижают настройками или прошивкой; это не доказательство майнинга."
                if low_limit and gpu.default_power_limit_w
                else ""
            ),
        )
    )
    section.add(value_row("Лимит мощности (заводской)", gpu.default_power_limit_w, source, "Вт"))
    section.add(value_row("Лимит мощности (максимум)", gpu.max_power_limit_w, source, "Вт"))
    for key, title in (("graphics", "ядра"), ("memory", "памяти")):
        section.add(
            value_row(f"Максимальная частота {title}", gpu.max_clocks.get(key), source, "МГц")
        )
    load = _result(session, "gpu_load")
    component = f"gpu{index}"
    for label, sensor in (
        ("Температура GPU под нагрузкой", "temperature"),
        ("Частота ядра под нагрузкой", "core_clock"),
        ("Частота памяти под нагрузкой", "memory_clock"),
        ("Загрузка GPU под нагрузкой", "utilization"),
        ("Загрузка контроллера памяти под нагрузкой", "memory_utilization"),
        ("Занято видеопамяти под нагрузкой", "vram_used"),
        ("Потребление под нагрузкой", "power"),
        ("Вентилятор под нагрузкой", "fan"),
    ):
        section.add(stats_row(label, load, f"{component}.{sensor}"))
    if gpu.vendor == "NVIDIA":
        for label in ("Температура Hot Spot", "Температура видеопамяти"):
            section.add(
                unavailable_row(label, "nvidia-smi у этой карты и драйвера значение не отдаёт.")
            )
    else:
        section.add(
            unavailable_row(
                "Датчики видеокарты",
                "Для AMD и Intel источника датчиков без драйвера нет (nvidia-smi — только NVIDIA).",
            )
        )
    section.add(unavailable_row("Напряжение и обороты вентилятора (RPM)", REASON_DRIVER))
    return section


def memory_section(session: CheckSession) -> Section:
    memory = session.snapshot.memory
    section = Section("Оперативная память", "memory")
    reason = _reason(session, "memory")
    total = memory.total_mb if memory and memory.total_mb else None
    section.add(value_row("Установлено", total, SRC_RAM, "МБ", reason))
    available = memory.available_mb if memory else None
    section.add(value_row("Доступно Windows", available, "psutil", "МБ", reason))
    slots = memory.slots_total if memory else None
    section.add(
        value_row("Слотов на плате", slots, "WMI: Win32_PhysicalMemoryArray", reason=reason)
    )
    section.add(
        value_row(
            "Занято слотов",
            len(memory.modules) if memory and memory.modules else None,
            SRC_RAM,
            reason=reason,
        )
    )
    for module in memory.modules if memory else []:
        name = module.slot or "слот ?"
        rated, configured = module.speed_mhz, module.configured_speed_mhz
        slow = bool(rated and configured and configured < rated)
        section.add(value_row(f"{name}: объём", module.capacity_mb or None, SRC_RAM, "МБ"))
        section.add(value_row(f"{name}: тип", module.memory_type, SRC_RAM))
        section.add(value_row(f"{name}: производитель", module.manufacturer, SRC_RAM))
        section.add(value_row(f"{name}: модель (part number)", module.part_number, SRC_RAM))
        section.add(
            name_row(
                f"{name}: серийный номер",
                module.serial_number,
                SRC_RAM,
                note="Скрывается при экспорте с включённым скрытием идентификаторов.",
            )
        )
        section.add(value_row(f"{name}: номинальная частота", rated, SRC_RAM, "МГц"))
        section.add(
            value_row(
                f"{name}: текущая частота",
                configured,
                SRC_RAM,
                "МГц",
                note=f"Ниже номинальной — {NEEDS_INTERPRETATION}: профиль XMP/EXPO не включён или "
                "плата/процессор не тянут."
                if slow
                else "",
            )
        )
        section.add(value_row(f"{name}: напряжение", module.voltage_mv, SRC_RAM, "мВ"))
    section.add(
        unavailable_row(
            "Rank, тайминги, XMP/EXPO, режим каналов",
            "Windows не сообщает их без драйвера; надёжного источника нет.",
        )
    )
    ram = _result(session, "ram_quick")
    quick_note = (
        "Быстрый тест в Windows: проверяется только свободная часть памяти и только "
        "несколькими шаблонами. Он не заменяет полную загрузочную проверку (MemTest86 и подобные)."
    )
    if ram is None:
        section.add(unavailable_row("Тест памяти", quick_note + " Тест не запускался."))
    else:
        tested = ram.metrics.get("tested_mb")
        errors = ram.metrics.get("errors")
        text = STATE_NAMES[check_state(ram)]
        if tested is not None:
            text += f"; проверено {tested} МБ"
        if errors is not None:
            text += f"; ошибок: {errors}"
        section.add(Row("Тест памяти", text, "ЖелезоЧек: быстрый тест (numpy)", note=quick_note))
    return section


def disk_section(session: CheckSession, index: int, disk: DiskInfo) -> Section:
    section = Section(f"Накопитель {index + 1}: {disk.model or 'без названия'}", f"disk{index}")
    smart = disk.smart
    source = (
        f"smartctl {smart.tool_version}".strip()
        if smart and smart.source == "smartctl"
        else ("Windows: Get-PhysicalDisk" if smart else "Windows")
    )
    section.add(value_row("Модель", disk.model, source))
    section.add(value_row("Устройство", disk.device, source))
    section.add(value_row("Объём", round(disk.size_gb, 1) if disk.size_gb else None, source, "ГБ"))
    media = {"ssd": "SSD", "hdd": "HDD"}.get(disk.media_type)
    section.add(value_row("Тип", media, source))
    section.add(value_row("Интерфейс", disk.bus_type.upper() if disk.bus_type else None, source))
    identity_reason = "Источник не сообщил (или проверка сделана до версии 2.1)."
    section.add(value_row("Семейство модели", disk.model_family, source, reason=identity_reason))
    section.add(
        name_row(
            "Серийный номер",
            disk.serial_number,
            source,
            identity_reason,
            note="Скрывается при экспорте с включённым скрытием идентификаторов.",
        )
    )
    section.add(value_row("Прошивка", disk.firmware, source, reason=identity_reason))
    section.add(
        value_row("Скорость подключения", disk.interface_speed, source, reason=identity_reason)
    )
    if smart is None:
        section.add(
            unavailable_row(
                "S.M.A.R.T.",
                disk.note or "Устройство не отдаёт S.M.A.R.T. (часто — USB-флешки и переходники).",
                source,
            )
        )
        return section
    health = (
        None
        if smart.health_passed is None
        else ("в норме" if smart.health_passed else "НЕИСПРАВЕН")
    )
    section.add(value_row("Самодиагностика (health)", health, source))
    section.add(
        value_row(
            "Самотест",
            smart.self_test,
            source,
            reason="Журнал самотестов пуст или недоступен; программа самотест не запускает.",
        )
    )
    # Показываем только поля, которые есть у такого типа накопителя: у HDD нет износа и полей
    # NVMe, у NVMe нет счётчиков секторов и CRC интерфейса SATA. Неприменимое — не «не получено».
    nvme = disk.bus_type == "nvme"
    fields: list[tuple[str, Any, str]] = [
        ("Наработка", smart.power_on_hours, "ч"),
        ("Включений", smart.power_cycles, ""),
        ("Температура", smart.temperature_c, "°C"),
    ]
    if not nvme:
        fields += [
            ("Переназначенные сектора", smart.reallocated_sectors, ""),
            ("Ожидающие сектора", smart.pending_sectors, ""),
            ("Неисправимые сектора", smart.uncorrectable_sectors, ""),
            ("Ошибки интерфейса (CRC)", smart.crc_errors, ""),
        ]
    if disk.media_type != "hdd":
        fields.append(("Износ (израсходовано ресурса)", smart.wear_percent, "%"))
    if nvme and not smart.nvme_log:  # полный журнал NVMe ниже покажет всё это сам
        fields += [
            ("Ошибки носителя (NVMe)", smart.media_errors, ""),
            ("Записано (NVMe)", smart.data_written_tb, "ТБ"),
            ("Аварийных выключений (NVMe)", smart.unsafe_shutdowns, ""),
            ("Резерв ячеек (NVMe)", smart.available_spare_pct, "%"),
            ("Порог резерва (NVMe)", smart.available_spare_threshold_pct, "%"),
        ]
    for label, value, unit in fields:
        section.add(
            value_row(
                label,
                value,
                source,
                unit,
                reason="Накопитель или источник это значение не сообщает.",
            )
        )
    _full_smart(section, smart, source, nvme)
    if disk.note:
        section.add(Row("Примечание", disk.note, source))
    return section


def _full_smart(section: Section, smart: SmartData, source: str, nvme: bool) -> None:
    """Все атрибуты SATA (Current/Worst/Threshold/Raw) или весь журнал здоровья NVMe."""
    for attribute in smart.attributes:
        threshold = "не прочитан" if attribute.threshold is None else str(attribute.threshold)
        value = (
            f"Current {_dash(attribute.value)} · Worst {_dash(attribute.worst)} · "
            f"Threshold {threshold} · Raw {attribute.raw_text or _dash(attribute.raw)}"
        )
        section.add(Row(ata_title(attribute), value, source, note=interpret_attribute(attribute)))
    for row in nvme_rows(smart.nvme_log):
        section.add(Row(row.title, row.value, source, note=row.note))
    if not smart.attributes and not smart.nvme_log:
        reason = (
            "Полная таблица в этой проверке не сохранялась (проверка до версии 2.1 или "
            "данные получены средствами Windows, а не smartctl)."
        )
        section.add(unavailable_row("Полная таблица S.M.A.R.T.", reason, source))
    elif nvme and not smart.nvme_log:
        section.add(unavailable_row("Журнал здоровья NVMe", "smartctl не отдал журнал.", source))


def _dash(value: int | None) -> str:
    return "—" if value is None else str(value)


def psu_section() -> Section:
    section = Section("Блок питания", "psu")
    section.add(
        unsupported_row(
            "Модель и мощность",
            "Программно не определяется; узнать можно только по наклейке на блоке.",
        )
    )
    section.add(
        unsupported_row(
            "Исправность блока питания",
            "Программная проверка не подтверждает исправность БП: не измеряются пульсации, "
            "реальная мощность и поведение при скачках нагрузки.",
        )
    )
    section.add(unavailable_row("Напряжения 12 В / 5 В / 3,3 В", REASON_DRIVER))
    return section


def system_section(session: CheckSession) -> Section:
    system = session.snapshot.system
    section = Section("Система", "system")
    reason = _reason(session, "system")
    section.add(
        name_row("Производитель компьютера", system and system.manufacturer, SRC_CS, reason)
    )
    section.add(name_row("Модель компьютера", system and system.model, SRC_CS, reason))
    section.add(
        value_row(
            "Windows установлена",
            system and _when(system.install_date or ""),
            SRC_OS,
            reason=reason,
        )
    )
    section.add(
        value_row(
            "Последний запуск", system and _when(system.last_boot or ""), SRC_OS, reason=reason
        )
    )
    events = session.snapshot.events
    section.add(
        value_row(
            "Журнал событий: период",
            f"{events.days} дней" if events else None,
            "Журнал Windows (System)",
            reason=_reason(session, "events"),
        )
    )
    return section


def laptop_section(session: CheckSession) -> Section | None:
    details = laptop_details(session)
    if not details:
        return None
    section = Section("Ноутбук", "laptop")
    for label, text in details:
        section.add(Row(label, text, SRC_BATTERY if "атаре" in label else SRC_APP))
    section.add(
        Row(
            "Ручные проверки",
            "экран и клавиатура — по результату проверки человеком",
            SRC_APP,
            note="Результат зависит от внимательности проверяющего.",
        )
    )
    return section


def tests_table(session: CheckSession) -> list[dict[str, Any]]:
    """Все тесты: состояние, длительность, все метрики с подписями по-русски (специалисту не
    скрываем ни одной: неизвестная метрика показывается под своим ключом)."""
    return [
        {
            "name": strings.TEST_NAMES.get(r.name, r.name),
            "state": STATE_NAMES[check_state(r)],
            "state_key": check_state(r).value,
            "duration": f"{r.duration_s:.0f} с",
            "started": _when(r.started_at) or "—",
            "metrics": metric_rows(r.metrics),
            "markers": [f"{m.elapsed_seconds:.0f} с — {m.text}" for m in r.markers],
            "notes": r.notes,
        }
        for r in session.results
    ]


def findings_table(session: CheckSession) -> list[dict[str, str]]:
    findings = session.verdict.findings if session.verdict else []
    return [
        {
            "rule": f.id,
            "severity": strings.SEVERITY_NAMES.get(f.severity.value, f.severity.value),
            "severity_key": f.severity.value,
            "title": f.title,
            "explanation": f.explanation,
            "evidence": readable_evidence(f.evidence) or "—",
            "impact": f.impact,
            "limitations": f.limitations,
            "bargain": f.bargain,
        }
        for f in findings
    ]


def specialist_context(session: CheckSession) -> dict[str, Any]:
    """Паспорт, разделы, тесты, находки, неполученные данные и источники."""
    snap = session.snapshot
    sections = [board_section(session), cpu_section(session)]
    sections += [gpu_section(session, i, gpu) for i, gpu in enumerate(snap.gpus)]
    sections.append(memory_section(session))
    sections += [disk_section(session, i, disk) for i, disk in enumerate(snap.disks)]
    sections += [psu_section(), system_section(session)]
    laptop = laptop_section(session)
    if laptop:
        sections.append(laptop)
    head = passport(session)
    rows = [row for section in [head, *sections] for row in section.rows]
    missing = [
        (section.title, row)
        for section in [head, *sections]
        for row in section.rows
        if row.status is not Availability.AVAILABLE
    ]
    sources = sorted({row.source for row in rows if row.source != SRC_NONE})
    return {
        "passport": head,
        "sections": sections,
        "tests": tests_table(session),
        "findings": findings_table(session),
        "assessments": assess_components(session),
        "missing": missing,
        "sources": sources,
    }
