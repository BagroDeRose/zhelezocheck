"""Тесты HTML-отчёта: снимок вёрстки, отсутствие внешних ресурсов, содержимое."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from hwcheck.laptop.details import laptop_details
from hwcheck.models import CheckSession
from hwcheck.report import builder
from hwcheck.report.charts import build_series_charts, render_svg
from hwcheck.report.specialist import specialist_context
from tests.report.helpers import demo_session

SNAPSHOTS = Path(__file__).parent.parent / "fixtures" / "report"
FIXED_TIME = datetime(2026, 10, 5, 12, 15)


def test_snapshot_healthy() -> None:
    html = builder.build_html(demo_session("healthy_gaming_pc"), generated_at=FIXED_TIME)
    snapshot = SNAPSHOTS / "healthy_gaming_pc.html"
    if os.environ.get("UPDATE_SNAPSHOTS") or not snapshot.exists():
        snapshot.write_text(html, encoding="utf-8", newline="\n")
    assert html == snapshot.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "scenario", ["healthy_gaming_pc", "mining_gpu", "dying_hdd", "laptop_worn_battery"]
)
def test_no_external_resources(scenario: str) -> None:
    html = builder.build_html(demo_session(scenario))
    assert "<link" not in html
    assert "<script" not in html
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html)
    assert "url(" not in html
    assert "@import" not in html


def test_contents_mining() -> None:
    session = demo_session("mining_gpu")
    html = builder.build_html(session)
    assert "ТОРГОВАТЬСЯ" in html
    assert session.id in html
    assert builder.session_digest(session) in html
    assert "Аргументы для торга" in html
    assert "Что не удалось проверить" in html
    assert "Быстрая проверка" in html
    assert "Демо-режим" in html
    assert "<svg" in html  # график температуры видеокарты
    assert "GA104" in html  # реальный чип по коду устройства


def _rows(session: CheckSession, title: str) -> dict[str, Any]:
    """Строки раздела технического отчёта (с 2.1 подробности железа — там)."""
    section = next(s for s in specialist_context(session)["sections"] if s.title == title)
    return {row.label: row for row in section.rows}


def test_hardware_details() -> None:
    session = demo_session("healthy_gaming_pc")
    cpu = _rows(session, "Процессор")
    assert cpu["Сокет"].value == "AM4"
    memory = _rows(session, "Оперативная память")
    assert memory["Установлено"].value == "32768 МБ"
    assert memory["Занято слотов"].value == "2" and memory["Слотов на плате"].value == "4"
    assert memory["DIMM_A2: текущая частота"].value == "3200 МГц"
    system = _rows(session, "Система")
    assert system["Windows установлена"].value.startswith("14.03.2024")
    assert system["Последний запуск"].value.startswith("05.10.2026 09:01")


def test_hardware_without_optional_values() -> None:
    """Неизвестные значения не превращаются в «None%» и одинокое «МГц»."""
    session = demo_session("laptop_worn_battery")
    assert session.snapshot.battery is not None and session.snapshot.memory is not None
    session.snapshot.battery.design_capacity_mwh = 0
    for module in session.snapshot.memory.modules:
        module.speed_mhz = module.configured_speed_mhz = None
    html = builder.build_html(session)
    assert "None" not in html
    memory_rows = _rows(session, "Оперативная память").values()
    assert not any(row.value.strip().startswith("МГц") for row in memory_rows)  # единица без числа
    speed = _rows(session, "Оперативная память")["DIMM 0: текущая частота"]
    assert speed.value == "Не удалось получить"
    laptop = dict(laptop_details(session))
    assert "износ не определён" in laptop["Батарея"].lower() or "не определ" in laptop["Батарея"]


def test_oem_placeholder_computer_name_hidden() -> None:
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.system is not None
    session.snapshot.system.manufacturer = "To be filled by O.E.M."
    session.snapshot.system.model = "To be filled by O.E.M."
    rows = _rows(session, "Система")
    # С 2.1.0-rc2 — «Не указано производителем» (было «Не поддерживается оборудованием»).
    assert rows["Модель компьютера"].value == "Не указано производителем"
    assert "O.E.M" not in builder.build_html(session)


def test_gpu_and_disk_details() -> None:
    session = demo_session("healthy_gaming_pc")
    gpu = _rows(session, "Видеокарта 1: NVIDIA GeForce RTX 3060")
    assert gpu["Шина PCIe (максимум)"].value == "PCIe 4.0 ×16"
    ssd = _rows(session, "Накопитель 1: Samsung SSD 980 1TB")
    hdd = _rows(session, "Накопитель 2: WDC WD20EZBX-00AYRA0")
    assert ssd["Наработка"].value == "3120 ч" and ssd["Включений"].value == "812"
    assert hdd["Включений"].value == "1630" and hdd["Температура"].value == "34.0 °C"


def test_nvme_details_in_report() -> None:
    session = demo_session("healthy_gaming_pc")
    smart = session.snapshot.disks[0].smart
    assert smart is not None
    smart.nvme_log = {}  # проверка до 2.1: только сводные поля, без полного журнала NVMe
    smart.data_written_tb, smart.unsafe_shutdowns = 46.6, 34
    smart.available_spare_pct, smart.available_spare_threshold_pct = 100, 10
    rows = _rows(session, "Накопитель 1: Samsung SSD 980 1TB")
    assert rows["Записано (NVMe)"].value == "46.6 ТБ"
    assert rows["Аварийных выключений (NVMe)"].value == "34"
    assert rows["Резерв ячеек (NVMe)"].value == "100 %"
    assert rows["Порог резерва (NVMe)"].value == "10 %"


def test_event_log_table() -> None:
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.events is not None
    session.snapshot.events.counts["bugcheck"] = 2
    session.snapshot.events.last_seen["bugcheck"] = "2026-10-01T22:10:00"
    events = builder._event_context(session)
    assert events is not None and events["days"] == 30
    bsod = next(row for row in events["rows"] if row["name"] == "Синие экраны")
    assert bsod["count"] == 2 and bsod["last"] == "01.10.2026 22:10"
    html = builder.build_html(session)
    print_html, _ = builder.build_print_html(session)
    for text in (html, print_html):
        assert "Журнал Windows за 30 дней" in text and "01.10.2026 22:10" in text


def test_digest_changes_with_content() -> None:
    session = demo_session("healthy_gaming_pc")
    before = builder.session_digest(session)
    session.results[0].metrics["errors"] = 1
    assert builder.session_digest(session) != before


def test_escaping() -> None:
    session = demo_session("healthy_gaming_pc")
    session.snapshot.gpus[0].name = "<script>alert(1)</script>"
    html = builder.build_html(session)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_chart_svg() -> None:
    """График — SVG с линией серии и пунктиром порога; одна точка — не линия."""
    session = demo_session("mining_gpu")
    chart = next(c for c in build_series_charts(session) if "температура" in c.title)
    svg = render_svg(chart, "c0")
    assert svg.startswith("<svg") and "polyline" in svg and "stroke-dasharray" in svg


def test_save_html(tmp_path: Path) -> None:
    path = builder.save_html(demo_session("worn_ssd"), tmp_path / "reports")
    assert path.exists() and path.suffix == ".html"
    assert "00000000" in path.name
