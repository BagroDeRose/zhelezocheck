"""Режим «Для покупателя» и переключатель режимов (этап 47 v2.1): короткий отчёт из тех же
находок и вердикта, оба режима из одного снимка, переключение без повторных тестов."""

import re

import pytest

from hwcheck.models import CheckState, Severity, TestStatus
from hwcheck.report import builder
from hwcheck.report.buyer import buyer_context
from tests.report.helpers import demo_session


def test_buyer_has_all_spec_parts() -> None:
    context = buyer_context(demo_session("mining_gpu"))
    assert context["decision_title"] == "Торговаться"
    assert context["summary"]
    assert 3 <= len(context["reasons"]) <= 6
    assert context["components"] and context["manual_checks"]
    assert context["mode"] == "Быстрая проверка" and context["duration"] == "10 мин 0 с"


def test_reasons_sorted_by_importance() -> None:
    reasons = buyer_context(demo_session("dying_hdd"))["reasons"]
    order = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
    keys = [order[r["severity_key"]] for r in reasons]
    assert keys == sorted(keys)
    assert reasons[0]["severity_key"] == "critical"


def test_component_states() -> None:
    components = {c["name"]: c for c in buyer_context(demo_session("dying_hdd"))["components"]}
    disk = next(
        c for name, c in components.items() if name.startswith("Накопитель") and "WDC" in name
    )
    assert disk["state"] == "Критично"
    assert components["Процессор"]["state"] == "Норма"


def test_not_checked_component_is_not_ok() -> None:
    """Не проведённый тест не превращается в «Норма» (принцип честности)."""
    session = demo_session("healthy_gaming_pc")
    for result in session.results:
        if result.name == "ram_quick":
            result.status = TestStatus.SKIPPED
            result.notes = ["Не запускался: проверка остановлена пользователем."]
    assert session.verdict is not None
    session.verdict.findings = [f for f in session.verdict.findings if f.component != "memory"]
    components = {c["name"]: c for c in buyer_context(session)["components"]}
    assert components["Оперативная память"]["state"] == "Не проверено"


def test_listing_mismatches_shown_only_when_relevant() -> None:
    session = demo_session("healthy_gaming_pc")
    assert buyer_context(session)["listing_mismatches"] == []
    assert session.verdict is not None
    from hwcheck.models import Finding

    session.verdict.findings.append(
        Finding(
            id="listing.gpu_mismatch",
            severity=Severity.CRITICAL,
            component="listing",
            title="Видеокарта не та, что в объявлении",
            explanation="Заявлена RTX 3070.",
        )
    )
    mismatches = buyer_context(session)["listing_mismatches"]
    assert [m["title"] for m in mismatches] == ["Видеокарта не та, что в объявлении"]


def test_manual_checks_follow_the_computer() -> None:
    desktop = buyer_context(demo_session("healthy_gaming_pc"))["manual_checks"]
    laptop = buyer_context(demo_session("laptop_worn_battery"))["manual_checks"]
    assert any("видеокарт" in item.lower() for item in desktop)
    assert any("экран" in item.lower() for item in laptop)
    assert not any("экран" in item.lower() for item in desktop)


def test_one_html_two_modes_without_scripts() -> None:
    session = demo_session("mining_gpu")
    html = builder.build_html(session)
    assert "<script" not in html
    assert 'id="mode-buyer"' in html and 'id="mode-specialist"' in html
    assert re.search(r'id="mode-buyer"[^>]*checked', html)  # по умолчанию — покупатель
    assert "Паспорт проверки" in html and "Что проверить перед оплатой" in html
    specialist = builder.build_html(session, mode="specialist")
    assert re.search(r'id="mode-specialist"[^>]*checked', specialist)


def test_buyer_view_has_no_charts() -> None:
    """Графики — только в режиме специалиста (у покупателя по умолчанию скрыты)."""
    html = builder.build_html(demo_session("healthy_gaming_pc"))
    buyer_part = html.split('<div class="view-buyer">')[1].split('<div class="view-specialist">')[0]
    assert "<svg" not in buyer_part
    assert "<svg" in html.split('<div class="view-specialist">')[1]


def test_switching_modes_does_not_run_tests() -> None:
    """Оба режима строятся из одного снимка: результаты тестов не меняются и не дублируются."""
    session = demo_session("healthy_gaming_pc")
    before = session.to_json()
    builder.build_html(session, mode="buyer")
    builder.build_html(session, mode="specialist")
    assert session.to_json() == before


@pytest.mark.parametrize("scenario", ["healthy_gaming_pc", "fake_gpu_relabel", "worn_ssd"])
def test_buyer_states_are_one_of_four(scenario: str) -> None:
    states = {c["state"] for c in buyer_context(demo_session(scenario))["components"]}
    assert states <= {"Норма", "Внимание", "Критично", "Не проверено"}


def test_check_state_names_used() -> None:
    assert CheckState.NOT_CHECKED.value == "not_checked"
