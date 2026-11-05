"""Интерпретация и правила вердикта (этап 49 v2.1): находка целиком, оценка компонентов с
уверенностью, без балла 0–100, без диагноза по одному косвенному признаку."""

import re
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import package_data_dir
from hwcheck.models import DiskInfo, Severity
from hwcheck.report import builder
from hwcheck.session import run_check
from hwcheck.verdict.assessment import CONFIDENCE_LEVELS, assess_components
from hwcheck.verdict.engine import decide
from tests.report.helpers import demo_session

DATA = Path(package_data_dir())


def _yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((DATA / name).read_text(encoding="utf-8"))


def all_texts() -> list[tuple[str, str, str]]:
    rules = _yaml("rules.yaml")["rules"]
    match = _yaml("listing_match.yaml")["match"]  # с 2.1 от объявления осталась только сверка
    entries = list(rules.items()) + [(f"listing.{k}", v) for k, v in match.items()]
    return [
        (rule_id, field, str(spec.get(field, "")))
        for rule_id, spec in entries
        for field in ("title", "explanation", "advice", "bargain", "impact", "limits")
    ]


# ---------------------------------------------------------------- находка целиком


@pytest.mark.parametrize("name", ["rules.yaml", "listing_match.yaml"])
def test_every_problem_rule_has_impact_and_limits(name: str) -> None:
    data = _yaml(name)
    entries = data["rules"] if "rules" in data else data["match"]
    for rule_id, spec in entries.items():
        if spec["severity"] == "ok":
            continue
        assert str(spec.get("impact", "")).strip(), f"{rule_id}: нет влияния на покупку"
        assert str(spec.get("limits", "")).strip(), f"{rule_id}: нет ограничения вывода"


def test_findings_carry_impact_limits_and_bargain() -> None:
    session = demo_session("mining_gpu")
    assert session.verdict is not None
    problems = [f for f in session.verdict.findings if f.severity is not Severity.OK]
    assert problems
    for finding in problems:
        assert finding.impact and finding.limitations, finding.id
        assert finding.evidence, finding.id  # с rc4 и у сверки с объявлением
    bargains = [f.bargain for f in session.verdict.findings if f.bargain]
    assert bargains and set(session.verdict.bargaining_points) <= set(bargains)


# ---------------------------------------------------------------- честность формулировок


FORBIDDEN = [
    (r"работала круглосуточно", "майнинг по косвенным признакам"),
    (r"майнинговая прошивка", "майнинг по BIOS/лимитам"),
    (r"скорее всего,? высохла термопаста", "термопаста по температуре"),
    (r"обычно это перегрев: высохла термопаста", "термопаста по частоте"),
    (r"проверен[а]? по (главному признаку|частоте)", "температура по частоте"),
    (r"блок питания (неисправен|исправен)", "вывод о БП программно"),
]


@pytest.mark.parametrize(("pattern", "why"), FORBIDDEN)
def test_no_diagnosis_by_single_indirect_sign(pattern: str, why: str) -> None:
    for rule_id, field, text in all_texts():
        assert not re.search(pattern, text, re.IGNORECASE), f"{rule_id}.{field}: {why}"


def test_power_limit_rule_does_not_claim_mining() -> None:
    session = demo_session("mining_gpu")
    assert session.verdict is not None
    finding = next(f for f in session.verdict.findings if f.id == "gpu.mining_bios")
    assert "не доказывает" in finding.limitations or "не доказ" in finding.explanation
    assert "майнинг" not in finding.title.lower()


# ---------------------------------------------------------------- оценка компонентов


def test_component_assessment_has_confidence_and_facts() -> None:
    assessments = assess_components(demo_session("dying_hdd"))
    assert assessments
    for item in assessments:
        assert item.state in ("Норма", "Внимание", "Критично", "Не проверено")
        assert item.confidence in CONFIDENCE_LEVELS
        assert item.reason
    disk = next(a for a in assessments if "WDC" in a.name)
    assert disk.state == "Критично" and disk.confidence == "высокий" and disk.facts


def test_not_checked_has_low_confidence() -> None:
    session = demo_session("healthy_gaming_pc")
    session.results = [r for r in session.results if r.name != "ram_quick"]
    assert session.verdict is not None
    session.verdict.findings = [f for f in session.verdict.findings if f.component != "memory"]
    memory = next(a for a in assess_components(session) if a.name == "Оперативная память")
    assert memory.state == "Не проверено" and memory.confidence == "низкий"
    assert memory.not_checked


def test_unmeasured_temperature_caps_confidence() -> None:
    """Ручная проверка rc1: «Процессор — Норма, высокий», хотя температура не измерена."""
    session = demo_session("healthy_gaming_pc")
    cpu_result = next(r for r in session.results if r.name == "cpu_load")
    cpu_result.metrics.pop("zone_temp_max_c", None)
    session.verdict = decide(session.snapshot, session.results)
    cpu = next(a for a in assess_components(session) if a.name == "Процессор")
    assert cpu.not_checked and cpu.state == "Норма"
    assert cpu.confidence == "средний"


def test_program_flash_drive_is_not_a_component() -> None:
    """Ручная проверка rc1: флешка с программой была «Накопитель: USB DISK 2.0 — Не проверено»."""
    session = demo_session("healthy_gaming_pc")
    session.snapshot.disks.append(
        DiskInfo(model="USB DISK 2.0", bus_type="usb", note="S.M.A.R.T. недоступен")
    )
    session.verdict = decide(session.snapshot, session.results)
    assert all("USB DISK" not in a.name for a in assess_components(session))
    assert all("USB DISK" not in item for item in session.verdict.not_checked)
    html = builder.build_html(session, mode="specialist")
    assert "USB DISK 2.0" in html  # раздел накопителя для специалиста остаётся


def test_tpm_reason_matches_rights() -> None:
    session = demo_session("healthy_gaming_pc")
    for admin, reason in ((True, "Не собирается"), (False, "правами администратора")):
        session.snapshot.is_admin = admin
        html = builder.build_html(session, mode="specialist")
        start = html.index("<td>TPM</td>")
        assert reason in html[start : html.index("</tr>", start)], admin


def test_indirect_rule_lowers_confidence() -> None:
    gpu = next(
        a for a in assess_components(demo_session("mining_gpu")) if a.name.startswith("Видеокарта")
    )
    assert gpu.state == "Внимание"
    assert gpu.confidence == "средний"  # основание — косвенные признаки (rules.yaml: confidence)


def test_missing_sensor_is_not_penalized() -> None:
    """Недоступные датчики не ухудшают вердикт так же, как неисправность."""
    session = run_check(
        FakeBackend("healthy_gaming_pc", time_scale=0.0), "quick", threading.Event()
    )
    assert session.verdict is not None
    with_sensors = session.verdict.decision
    for result in session.results:
        result.samples = []
    without = decide(session.snapshot, session.results)
    assert without.decision == with_sensors


def test_no_single_score_in_reports() -> None:
    """Единого балла 0–100 нет (P2): в отчётах его не показываем."""
    session = demo_session("mining_gpu")
    html = builder.build_html(session)
    print_html, _ = builder.build_print_html(session)
    for text in (html, print_html):
        assert "балл" not in text.lower() and "из 100" not in text


def test_specialist_shows_full_findings_and_assessment() -> None:
    html = builder.build_html(demo_session("mining_gpu"), mode="specialist")
    assert "Влияние на покупку" in html and "Ограничения вывода" in html
    assert "Оценка компонентов" in html and "Уверенность" in html


def test_ok_findings_have_facts_and_dates_are_russian() -> None:
    """Ручная проверка rc2: у «Процессор прошёл проверку» основание было пустым, а дата
    в основании событий — «2026-10-31 23:48»."""
    session = demo_session("healthy_gaming_pc")
    assert session.verdict is not None
    cpu_ok = next(f for f in session.verdict.findings if f.id == "cpu.ok")
    assert "Снижение частоты" in cpu_ok.evidence and "Расхождений" in cpu_ok.evidence
    events = session.snapshot.events
    assert events is not None
    events.counts["disk_removable"] = 3
    events.last_seen["disk_removable"] = "2026-10-31T23:48:23"
    verdict = decide(session.snapshot, session.results)
    found = next(f for f in verdict.findings if f.id == "system.disk_events_removable")
    assert "31.10.2026 23:48" in found.evidence
