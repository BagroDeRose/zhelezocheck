"""Данные специалиста и технический HTML (этап 43 v2.1): паспорт проверки, источник и статус у
каждого параметра, честные пометки о недоступном, офлайн-HTML, старые проверки."""

import re
from pathlib import Path

import pytest

from hwcheck import schema
from hwcheck.models import Availability, CheckSession, SensorSample
from hwcheck.report import builder
from hwcheck.report.specialist import (
    NOT_RECEIVED,
    NOT_SUPPORTED,
    Row,
    passport,
    specialist_context,
)
from tests.report.helpers import demo_session

OLD_SESSION = Path(__file__).parent.parent / "fixtures" / "sessions" / "session_2_0_1.json"

PASSPORT_LABELS = [
    "Программа",
    "Версия схемы отчёта",
    "Начало",
    "Окончание",
    "Длительность",
    "Режим",
    "Операционная система",
    "Версия и сборка",
    "Архитектура",
    "Имя компьютера",
    "Права",
    "Проведённые тесты",
    "Не проведённые тесты",
    "Утилиты и драйверы",
    "Причины неполноты",
]


def rows_of(context: dict, title: str) -> dict[str, Row]:
    section = next(s for s in context["sections"] if s.title == title)
    return {row.label: row for row in section.rows}


def all_rows(context: dict) -> list[Row]:
    return [row for section in [context["passport"], *context["sections"]] for row in section.rows]


def test_passport_is_complete() -> None:
    session = demo_session("healthy_gaming_pc")
    labels = [row.label for row in passport(session).rows]
    for label in PASSPORT_LABELS:
        assert label in labels, label
    rows = {row.label: row for row in passport(session).rows}
    assert rows["Длительность"].value == "10 мин 0 с"
    assert rows["Версия схемы отчёта"].value == "2"
    assert "ЖелезоЧек" in rows["Программа"].value


def test_every_row_has_source_and_status() -> None:
    context = specialist_context(demo_session("mining_gpu"))
    for row in all_rows(context):
        assert row.source.strip(), row.label
        assert isinstance(row.status, Availability), row.label
        if row.status is not Availability.AVAILABLE:
            assert row.value in (NOT_RECEIVED, NOT_SUPPORTED), row.label
            assert row.note.strip(), f"нет причины: {row.label}"


def test_unavailable_sensors_are_marked_not_zero() -> None:
    """Температура ядер CPU без драйвера недоступна — так и пишем, без нуля."""
    rows = rows_of(specialist_context(demo_session("healthy_gaming_pc")), "Процессор")
    package = rows["Температура ядер (Package)"]
    assert package.status is Availability.UNAVAILABLE and "драйвер" in package.note
    assert not any(re.fullmatch(r"0(\.0)?\s*°C", row.value) for row in rows.values())


def test_load_statistics_from_real_series() -> None:
    session = demo_session("healthy_gaming_pc")
    gpu = rows_of(specialist_context(session), "Видеокарта 1: NVIDIA GeForce RTX 3060")
    temp = gpu["Температура GPU под нагрузкой"]
    assert temp.status is Availability.AVAILABLE
    assert re.search(r"мин \d+.*сред \d+.*макс \d+ °C", temp.value), temp.value
    assert temp.source == "nvidia-smi"


def test_zone_temperature_only_when_measured() -> None:
    session = demo_session("healthy_gaming_pc")
    cpu_result = next(r for r in session.results if r.name == "cpu_load")
    for sample in cpu_result.samples:
        sample.values.pop("zone_temp_c", None)
    rows = rows_of(specialist_context(session), "Процессор")
    assert rows["Температура тепловой зоны под нагрузкой"].status is Availability.UNAVAILABLE
    cpu_result.samples.append(SensorSample(t=99.0, component="cpu", values={"zone_temp_c": 55.0}))
    rows = rows_of(specialist_context(session), "Процессор")
    zone = rows["Температура тепловой зоны под нагрузкой"]
    assert zone.status is Availability.AVAILABLE and "55" in zone.value
    assert "не ядра" in zone.note  # честная оговорка: это датчик платы


def test_missing_collector_reason_is_shown() -> None:
    session = demo_session("healthy_gaming_pc")
    session.snapshot.cpu = None
    session.snapshot.errors["cpu"] = "WMI не ответил"
    rows = rows_of(specialist_context(session), "Процессор")
    name = rows["Модель"]
    assert name.status is Availability.UNAVAILABLE and "WMI не ответил" in name.note


def test_quick_ram_test_is_not_called_full() -> None:
    rows = rows_of(specialist_context(demo_session("healthy_gaming_pc")), "Оперативная память")
    note = rows["Тест памяти"].note
    assert "быстрый" in note.lower() and "не заменяет" in note


def test_psu_section_states_limits() -> None:
    rows = rows_of(specialist_context(demo_session("healthy_gaming_pc")), "Блок питания")
    assert all(row.status is not Availability.AVAILABLE for row in rows.values())
    assert any("не подтверждает исправность" in row.note for row in rows.values())


def test_ambiguous_values_are_shown_with_note() -> None:
    """Специалисту не скрываем неудобное: значение есть и с пометкой «требует интерпретации»."""
    session = demo_session("healthy_gaming_pc")
    session.snapshot.gpus[0].pcie_width_current = 8
    gpu = rows_of(specialist_context(session), "Видеокарта 1: NVIDIA GeForce RTX 3060")
    assert "×8" in gpu["Шина PCIe (сейчас)"].value
    assert "требует интерпретации" in gpu["Шина PCIe (сейчас)"].note


def test_tests_table_has_four_states_and_all_metrics() -> None:
    context = specialist_context(demo_session("ram_errors"))
    ram = next(t for t in context["tests"] if t["name"] == "Быстрый тест оперативной памяти")
    assert ram["state"] == "проверено — обнаружены проблемы"
    # С 2.1.0-rc2 метрики подписаны по-русски («errors» → «Ошибок»), значения те же.
    assert ("Ошибок", "3") in ram["metrics"]


def test_specialist_html_offline_with_sources() -> None:
    html = builder.build_specialist_html(demo_session("mining_gpu"))
    assert "<script" not in html and "<link" not in html
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html)
    assert "url(" not in html and "@import" not in html
    assert "Паспорт проверки" in html and "Источник" in html
    assert "nvidia-smi" in html and "Win32_Processor" in html
    assert NOT_RECEIVED in html


def test_old_session_builds_specialist_report() -> None:
    session = schema.load_session(OLD_SESSION.read_text(encoding="utf-8"))
    html = builder.build_specialist_html(session)
    assert "Паспорт проверки" in html


@pytest.mark.parametrize("scenario", ["laptop_worn_battery", "dying_hdd", "fake_gpu_relabel"])
def test_specialist_report_for_scenarios(scenario: str) -> None:
    html = builder.build_specialist_html(demo_session(scenario))
    assert "Неполученные данные и ограничения" in html


def test_empty_session_does_not_crash() -> None:
    context = specialist_context(CheckSession())
    assert context["passport"].rows


def test_disk_shows_only_applicable_fields() -> None:
    """У HDD нет полей NVMe и износа, у NVMe — секторов SATA: это не «не удалось получить»."""
    from hwcheck.models import DiskInfo, SmartData

    session = demo_session("healthy_gaming_pc")
    session.snapshot.disks = [
        DiskInfo(model="HDD", media_type="hdd", bus_type="sata", smart=SmartData(power_on_hours=1)),
        DiskInfo(
            model="NVMe", media_type="ssd", bus_type="nvme", smart=SmartData(wear_percent=3.0)
        ),
    ]
    context = specialist_context(session)
    hdd = rows_of(context, "Накопитель 1: HDD")
    nvme = rows_of(context, "Накопитель 2: NVMe")
    assert not any("NVMe" in label for label in hdd) and "Износ (израсходовано ресурса)" not in hdd
    assert "Переназначенные сектора" in hdd
    assert "Переназначенные сектора" not in nvme and "Ошибки интерфейса (CRC)" not in nvme
    assert "Резерв ячеек (NVMe)" in nvme and nvme["Износ (израсходовано ресурса)"].value == "3.0 %"


def _real_disks_session() -> CheckSession:
    from hwcheck.collectors import disks
    from tests.helpers import fixture_json

    session = demo_session("healthy_gaming_pc")
    session.snapshot.disks = [
        disks.parse_smartctl(fixture_json("smartctl", "real_wd_hdd_ata.json")),
        disks.parse_smartctl(fixture_json("smartctl", "real_ardor_nvme.json")),
    ]
    # В записанном образце серийный номер обезличен нулями — а нули теперь считаются
    # заглушкой. Для проверки строки ставим вымышленный «настоящий» номер.
    session.snapshot.disks[0].serial_number = "WD-WCC0TEST0001"
    return session


def test_full_smart_sata_table() -> None:
    """Этап 45: все атрибуты SATA — Current/Worst/Threshold/Raw, статус и интерпретация."""
    context = specialist_context(_real_disks_session())
    hdd = rows_of(context, "Накопитель 1: WDC WD10EZEX-22MFCA0")
    attributes = [row for label, row in hdd.items() if label.startswith("#")]
    assert len(attributes) == 17
    realloc = hdd["#5 Переназначенные сектора (Reallocated Sectors)"]
    assert "Current 200" in realloc.value and "Threshold не прочитан" in realloc.value
    assert "порог не прочитан" in realloc.note  # без прав администратора — честно
    assert hdd["Прошивка"].value == "01.01A01"
    assert hdd["Самотест"].value == "completed without error"
    assert "Скрывается" in hdd["Серийный номер"].note


def test_full_smart_nvme_log() -> None:
    context = specialist_context(_real_disks_session())
    nvme = rows_of(context, "Накопитель 2: ARDOR GAMING m.2 NVME 256Gb AL1282")
    assert nvme["Записано (Data Units Written)"].value.startswith("46,6 ТБ")
    assert "Команд чтения (Host Read Commands)" in nvme
    assert "Время занятости контроллера (Controller Busy Time)" in nvme
    assert nvme["Критическое предупреждение (Critical Warning)"].value == "0 (нет предупреждений)"


def test_old_check_without_attribute_table_is_explained() -> None:
    session = demo_session("dying_hdd")
    smart = session.snapshot.disks[1].smart
    assert smart is not None
    smart.attributes = []  # проверка до 2.1: полной таблицы атрибутов не сохраняли
    rows = rows_of(specialist_context(session), "Накопитель 2: WDC WD20EZBX-00AYRA0")
    table = rows["Полная таблица S.M.A.R.T."]
    assert table.status is Availability.UNAVAILABLE and "не сохран" in table.note


def _session_with_events() -> CheckSession:
    from hwcheck.collectors import events
    from tests.helpers import fixture_json

    session = demo_session("healthy_gaming_pc")
    session.started_at = "2026-10-05T12:00:00"
    session.snapshot.events = events.parse(fixture_json("powershell", "events_v21.json"))
    return session


def test_event_details_in_specialist_report() -> None:
    """Этап 46: Event ID, источник, уровень, расшифровка, повторы, компонент, значимость."""
    from hwcheck.report.builder import _event_context

    context = _event_context(_session_with_events())
    assert context is not None
    tdr = next(item for item in context["items"] if item["event_id"] == 4101)
    assert tdr["provider"] == "Display" and tdr["count"] == 4
    assert tdr["level"] == "предупреждение" and "TDR" in tdr["title"]
    assert tdr["component"] == "видеокарта (драйвер)" and tdr["significance"] == "средняя"
    assert tdr["when"] == "в том числе во время проверки"  # последнее — 12:05, проверка с 12:00
    kp41 = next(item for item in context["items"] if item["event_id"] == 41)
    assert kp41["when"] == "в истории Windows (до проверки)"
    assert "не доказательство неисправности блока питания" in kp41["note"]
    html = builder.build_specialist_html(_session_with_events())
    assert "4101" in html and "stornvme" in html and "Неожиданные выключения (6008)" in html


def test_unread_event_group_is_not_zero() -> None:
    """Журнал прочитан частично: непрочитанная группа — «не прочитано», а не 0."""
    from hwcheck.models import EventSummary
    from hwcheck.report.builder import _event_context

    session = demo_session("healthy_gaming_pc")
    session.snapshot.events = EventSummary(counts={"kernel_power_41": 1}, partial=True, note="x")
    context = _event_context(session)
    assert context is not None
    rows = {row["name"]: row["count"] for row in context["rows"]}
    assert rows["Синие экраны"] == "не прочитано" and rows["Внезапные выключения"] == 1
