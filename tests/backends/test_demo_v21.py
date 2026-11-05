"""Демо-сценарии v2.1 (SPEC_V2_1, этап 50).

В каждом сценарии есть данные расширенного отчёта (паспорт, полный SMART, события по видам,
ряды видеопамяти и тепловой зоны) и они согласованы со сводными полями. Оба режима отчёта
строятся из одной проверки без повторного тестирования; недоступные датчики и испорченные
данные не ломают отчёт и не превращаются в выдуманные значения.
"""

import math
import re
import threading
from typing import Any

import pytest

from hwcheck.backends.fake import FakeBackend, list_scenarios, load_scenario
from hwcheck.models import CheckSession, Decision, SensorSample, TestResult
from hwcheck.report import builder
from hwcheck.report.charts import build_series_charts, render_svg
from hwcheck.session import run_check

# Семь случаев из SPEC_V2_1 (этап 50) и ожидаемое решение по каждому.
CASES = {
    "healthy_gaming_pc": Decision.BUY,
    "overheating_cpu": Decision.NEGOTIATE,
    "gpu_vram_errors": Decision.WALK_AWAY,
    "ram_errors": Decision.WALK_AWAY,
    "dying_hdd": Decision.WALK_AWAY,
    "worn_ssd": Decision.NEGOTIATE,
    "fake_gpu_relabel": Decision.WALK_AWAY,
}


class CountingBackend(FakeBackend):
    """Фейковый бэкенд, который считает запуски тестов."""

    def __init__(self, scenario: str) -> None:
        super().__init__(scenario, time_scale=0.0)
        self.runs = 0

    def run_stress(self, *args: Any, **kwargs: Any) -> TestResult:
        self.runs += 1
        return super().run_stress(*args, **kwargs)


def test_all_cases_present() -> None:
    assert set(CASES) <= set(list_scenarios())


@pytest.mark.parametrize("name", list_scenarios())
def test_passport_fields(name: str) -> None:
    snap = load_scenario(name).snapshot
    assert snap.system is not None and snap.system.computer_name
    assert snap.cpu is not None and snap.cpu.cpuid and snap.cpu.l3_cache_kb
    assert snap.memory is not None
    for module in snap.memory.modules:
        assert module.memory_type and module.voltage_mv and module.serial_number
    for disk in snap.disks:
        assert disk.serial_number and disk.firmware


@pytest.mark.parametrize("name", list_scenarios())
def test_full_smart_matches_summary(name: str) -> None:
    for disk in load_scenario(name).snapshot.disks:
        smart = disk.smart
        assert smart is not None and smart.tool_version
        if disk.bus_type == "nvme":
            log = smart.nvme_log
            assert log["percentage_used"] == smart.wear_percent
            assert log["media_errors"] == smart.media_errors
            assert log["power_on_hours"] == smart.power_on_hours
            assert smart.data_written_tb is not None
            continue
        raw = {a.id: a.raw for a in smart.attributes}
        assert raw[5] == smart.reallocated_sectors
        assert raw[9] == smart.power_on_hours
        assert raw[12] == smart.power_cycles
        assert raw[199] == smart.crc_errors
        if disk.media_type == "hdd":
            assert raw[197] == smart.pending_sectors
            assert raw[198] == smart.uncorrectable_sectors


@pytest.mark.parametrize("name", list_scenarios())
def test_event_items_match_counts(name: str) -> None:
    events = load_scenario(name).snapshot.events
    assert events is not None
    for group, count in events.counts.items():
        listed = sum(item.count for item in events.items if item.group == group)
        assert listed == count, (group, count, listed)
    for item in events.items:
        assert item.provider and item.event_id and item.message and item.last_seen


@pytest.mark.parametrize("name", list_scenarios())
def test_new_series_present(name: str) -> None:
    scenario = load_scenario(name)
    for test in ("vram", "gpu_load"):
        points = scenario.stress[test].series_points
        assert {"vram_used_mb", "mem_util_pct", "mem_clock_mhz"} <= set(points)
        # Ряды «gpu0» — первая карта NVIDIA; у ноутбука первой в Windows идёт встроенная.
        vram = max(gpu.vram_mb or 0 for gpu in scenario.snapshot.gpus)
        assert max(v for v in points["vram_used_mb"] if v is not None) <= vram
    cpu = scenario.stress["cpu_load"].series_points
    assert "util_pct" in cpu
    # У ноутбука из демо нет тепловой зоны ACPI — это и есть случай «датчик недоступен».
    assert ("zone_temp_c" in cpu) != bool(
        scenario.snapshot.system and scenario.snapshot.system.is_laptop
    )


@pytest.mark.parametrize(("name", "decision"), CASES.items())
def test_both_modes_from_one_check(name: str, decision: Decision) -> None:
    backend = CountingBackend(name)
    session = run_check(backend, "quick", threading.Event())
    runs = backend.runs
    assert session.verdict is not None and session.verdict.decision is decision
    buyer = builder.build_html(session, mode="buyer")
    specialist = builder.build_html(session, mode="specialist")
    print_html, _ = builder.build_print_html(session)
    assert backend.runs == runs, "переключение режима не должно запускать тесты"
    for html in (buyer, specialist, print_html):
        assert "Паспорт проверки" in html and "Оценка компонентов" in html
        assert "<svg" in specialist
    assert re.search(r'id="mode-buyer"[^>]*\bchecked', buyer)
    assert re.search(r'id="mode-specialist"[^>]*\bchecked', specialist)


def test_missing_zone_sensor_is_marked() -> None:
    session = run_check(FakeBackend("laptop_worn_battery"), "quick", threading.Event())
    html = builder.build_html(session, mode="specialist")
    start = html.index("Температура тепловой зоны под нагрузкой")
    row = html[start : start + 600]
    assert "не удалось получить" in row or "не поддерживается" in row


def test_frozen_zone_temperature_is_explained() -> None:
    """Ручная проверка rc1: зона ACPI весь тест 27,9 °C — показываем с оговоркой."""
    session = run_check(FakeBackend("healthy_gaming_pc"), "quick", threading.Event())
    cpu = next(r for r in session.results if r.name == "cpu_load")
    cpu.metrics["zone_temp_frozen"] = True
    for sample in cpu.samples:
        sample.values["zone_temp_c"] = 27.9
    html = builder.build_html(session, mode="specialist")
    start = html.index("Температура тепловой зоны под нагрузкой")
    assert "не отражает нагрев" in html[start : start + 800]
    chart = next(c for c in build_series_charts(session) if "тепловой зоны" in c.title)
    assert "не менялось" in render_svg(chart, "z")


def test_placeholders_are_not_values() -> None:
    """Ручная проверка rc1: серийный «00000000» у планки Corsair и ревизия «Rev X.0x»."""
    session = run_check(FakeBackend("healthy_gaming_pc"), "quick", threading.Event())
    snap = session.snapshot
    assert snap.memory is not None and snap.board is not None and snap.system is not None
    snap.memory.modules[1].serial_number = "00000000"
    snap.board.version = "Rev X.0x"
    snap.system.manufacturer = "System manufacturer"
    html = builder.build_html(session, mode="specialist")
    for label in ("DIMM_B2: серийный номер", "Ревизия платы", "Производитель компьютера"):
        start = html.index(f"<td>{label}</td>")
        row = html[start : html.index("</tr>", start)]
        assert "Не указано производителем" in row and "заглушка" in row, row
    for text in ("00000000", "Rev X.0x", "System manufacturer"):
        assert text not in html.split('class="view-specialist')[1].split("json-link")[0], text


def test_driver_limited_rows_are_not_hardware_unsupported() -> None:
    """Что не отдаёт Windows без драйвера — «не удалось получить», а не «не поддерживается»."""
    session = run_check(FakeBackend("healthy_gaming_pc"), "quick", threading.Event())
    html = builder.build_html(session, mode="specialist")
    for label in ("Техпроцесс и кодовое имя", "Rank, тайминги, XMP/EXPO, режим каналов"):
        row = html[html.index(label) : html.index("</tr>", html.index(label))]
        assert "не удалось получить" in row and "не поддерживается" not in row, label


def _spoil(session: CheckSession) -> None:
    """Портит данные так, как это бывает у реальных сборщиков."""
    snap = session.snapshot
    for disk in snap.disks:
        if disk.smart is None:
            continue
        disk.smart.nvme_log = {"percentage_used": "abc", "temperature": None, "junk": [1, 2]}
        for item in disk.smart.attributes:
            item.raw = None
            item.value = None
            item.raw_text = ""
    if snap.events is not None:
        for item in snap.events.items:
            item.message = ""
            item.first_seen = "не дата"
            item.level = None
    for result in session.results:
        for index, sample in enumerate(result.samples):
            if index % 3 == 0:
                result.samples[index] = SensorSample(
                    t=sample.t,
                    component=sample.component,
                    values=dict.fromkeys(sample.values, math.nan),
                )
            elif index % 3 == 1:
                sample.values = dict.fromkeys(sample.values)


@pytest.mark.parametrize("name", ["dying_hdd", "worn_ssd", "gpu_vram_errors"])
def test_spoiled_data_does_not_break_reports(name: str) -> None:
    session = run_check(FakeBackend(name), "quick", threading.Event())
    _spoil(session)
    for mode in ("buyer", "specialist"):
        html = builder.build_html(session, mode=mode)
        assert ">nan<" not in html.lower() and ">None<" not in html
    print_html, _ = builder.build_print_html(session)
    assert "nan °C" not in print_html
