"""Тесты HTML-отчёта: снимок вёрстки, отсутствие внешних ресурсов, содержимое."""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from hwcheck.models import CheckSession
from hwcheck.report import builder
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


def _hardware(session: CheckSession) -> dict[str, dict[str, Any]]:
    return {row["label"]: row for row in builder.build_context(session)["hardware"]}


def test_hardware_details() -> None:
    rows = _hardware(demo_session("healthy_gaming_pc"))
    assert "сокет AM4" in rows["Процессор"]["text"]
    assert rows["Оперативная память"]["text"] == "32 ГБ, занято 2 из 4 слотов"
    assert any("3200 МГц" in note for note in rows["Оперативная память"]["notes"])
    assert "установлена 14.03.2024" in rows["Windows"]["notes"]
    assert "последний запуск 05.10.2026 09:01" in rows["Windows"]["notes"]


def test_hardware_without_optional_values() -> None:
    """Неизвестные значения не превращаются в «None%» и одинокое «МГц»."""
    session = demo_session("laptop_worn_battery")
    assert session.snapshot.battery is not None and session.snapshot.memory is not None
    session.snapshot.battery.design_capacity_mwh = 0
    for module in session.snapshot.memory.modules:
        module.speed_mhz = module.configured_speed_mhz = None
    html = builder.build_html(session)
    assert "None" not in html
    rows = _hardware(session)
    assert not any("МГц" in note for note in rows["Оперативная память"]["notes"])
    assert "износ не определён" in rows["Батарея"]["text"]


def test_oem_placeholder_computer_name_hidden() -> None:
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.system is not None
    session.snapshot.system.manufacturer = "To be filled by O.E.M."
    session.snapshot.system.model = "To be filled by O.E.M."
    assert "Компьютер" not in _hardware(session)
    assert "O.E.M" not in builder.build_html(session)


def test_gpu_and_disk_details() -> None:
    context = builder.build_context(demo_session("healthy_gaming_pc"))
    assert "PCIe 4.0 ×16" in context["gpus"][0]["extra"]
    ssd, hdd = context["disks"]
    assert ssd["hours"] == "3 120 ч (≈4 мес.)"
    assert "включений: 812" in ssd["extra"]
    assert "включений: 1630" in hdd["extra"] and "34 °C" in hdd["extra"]


def test_nvme_details_in_report() -> None:
    session = demo_session("healthy_gaming_pc")
    smart = session.snapshot.disks[0].smart
    assert smart is not None
    smart.data_written_tb, smart.unsafe_shutdowns = 46.6, 34
    smart.available_spare_pct, smart.available_spare_threshold_pct = 100, 10
    extra = builder.build_context(session)["disks"][0]["extra"]
    assert "записано 46,6 ТБ" in extra
    assert "аварийных выключений: 34" in extra
    assert "резерв ячеек 100% (порог 10%)" in extra


def test_event_log_table() -> None:
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.events is not None
    session.snapshot.events.counts["bugcheck"] = 2
    session.snapshot.events.last_seen["bugcheck"] = "2026-10-01T22:10:00"
    events = builder.build_context(session)["events"]
    assert events["days"] == 30
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
    svg = builder.svg_line_chart([(0, 40), (10, 60), (20, 72)], "T", "°C", limit=83)
    assert svg.startswith("<svg") and "polyline" in svg and "stroke-dasharray" in svg
    assert builder.svg_line_chart([(0, 1)], "T", "°C") == ""


def test_save_html(tmp_path: Path) -> None:
    path = builder.save_html(demo_session("worn_ssd"), tmp_path / "reports")
    assert path.exists() and path.suffix == ".html"
    assert "00000000" in path.name
