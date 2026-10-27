"""Тесты движка вердикта: все демо-сценарии дают ожидаемое решение (expected.yaml)."""

import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from hwcheck.backends.fake import FakeBackend
from hwcheck.models import Decision, Finding, HardwareSnapshot, Severity, TestResult, TestStatus
from hwcheck.session import run_check
from hwcheck.verdict.engine import decide, not_checked

EXPECTED: dict[str, Any] = yaml.safe_load(
    (Path(__file__).parent.parent / "fixtures" / "scenarios" / "expected.yaml").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
def test_scenario_verdict(scenario: str) -> None:
    session = run_check(FakeBackend(scenario), "quick", threading.Event(), demo_scenario=scenario)
    verdict = session.verdict
    assert verdict is not None
    expected = EXPECTED[scenario]
    assert verdict.decision is Decision(expected["decision"]), [f.id for f in verdict.findings]
    ids = {f.id for f in verdict.findings}
    assert set(expected["must_have"]) <= ids
    # 25.3: температура процессора — не «ошибка» в «что не проверено», а находка «к сведению».
    assert not any("PawnIO" in item for item in verdict.not_checked)
    assert ids & {"cpu.temp_unmeasured", "cpu.temp_zone"} or any(
        "Перегрев процессора" in item for item in verdict.not_checked
    )


def test_findings_sorted_by_importance() -> None:
    session = run_check(FakeBackend("dying_hdd"), "quick", threading.Event())
    assert session.verdict is not None
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.OK: 3}
    ranks = [order[f.severity] for f in session.verdict.findings]
    assert ranks == sorted(ranks)


def test_negotiate_has_bargaining_points() -> None:
    session = run_check(FakeBackend("laptop_worn_battery"), "quick", threading.Event())
    assert session.verdict is not None
    assert any("батаре" in point for point in session.verdict.bargaining_points)


def test_light_warning_alone_is_buy() -> None:
    snap = FakeBackend("healthy_gaming_pc").collect()
    snap.gpus[0].pcie_width_current = 4  # вес 0.5 < порога 1.0
    results = list(FakeBackend("healthy_gaming_pc").scenario.stress)
    session_results = [TestResult(name=name, status=TestStatus.PASSED) for name in results]
    verdict = decide(snap, session_results)
    assert verdict.decision is Decision.BUY
    assert "gpu.pcie_reduced" in {f.id for f in verdict.findings}


def test_extra_findings_participate() -> None:
    snap = FakeBackend("healthy_gaming_pc").collect()
    extra = Finding(id="listing.mismatch", severity=Severity.CRITICAL, weight=10, title="x")
    verdict = decide(snap, [], extra_findings=[(extra, None)])
    assert verdict.decision is Decision.WALK_AWAY
    assert verdict.findings[0].id == "listing.mismatch"


def test_not_checked_lists_everything_missing() -> None:
    snap = HardwareSnapshot(errors={"gpus": "не удалось проверить: WMI"})
    results = {
        "vram": TestResult(name="vram", status=TestStatus.SKIPPED, notes=["Vulkan не работает."]),
        "cpu_load": TestResult(name="cpu_load", status=TestStatus.PASSED),
    }
    items = not_checked(snap, results, ["vram", "cpu_load", "disk_read"])
    text = "\n".join(items)
    assert "Тест видеопамяти — Vulkan не работает." in text
    assert "Тест чтения диска — не проводился." in text
    assert "Сведения о видеокартах" in text
    assert "Перегрев процессора" in text  # нет ни температуры, ни частоты
    assert "PawnIO" not in text


def test_cancelled_check_lists_skipped_tests() -> None:
    cancel = threading.Event()
    cancel.set()
    session = run_check(FakeBackend("healthy_gaming_pc"), "quick", cancel)
    assert session.verdict is not None
    assert any("остановлена пользователем" in item for item in session.verdict.not_checked)
