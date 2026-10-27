"""Тесты HTML-отчёта: снимок вёрстки, отсутствие внешних ресурсов, содержимое."""

import os
import re
from datetime import datetime
from pathlib import Path

import pytest

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
