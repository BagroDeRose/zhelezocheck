"""Подписи «Основания» и метрик тестов (этап 50 v2.1, по ручной проверке 2.1.0-rc1):
в отчёте нет технических ключей вида «model=…» и «clock_drop_pct = 0.8»."""

import re
import threading

import pytest

from hwcheck.backends.fake import FakeBackend, list_scenarios
from hwcheck.report import builder
from hwcheck.report.labels import format_evidence, metric_rows, readable_evidence
from hwcheck.report.specialist import specialist_context
from hwcheck.session import run_check

RAW_KEY = re.compile(r"\b[a-z]+_[a-z_0-9]+\b|\b[a-z_]+=")


def test_format_evidence_is_human_readable() -> None:
    text = format_evidence(
        {"component": "gpu", "model": "GTX 1660", "temp_text": ", под нагрузкой не выше 74 °C"}
    )
    assert text == "Модель: GTX 1660; под нагрузкой не выше 74 °C"
    assert format_evidence({"tested_gb": 7.96875}) == "Проверено: 8,0 ГБ"
    assert format_evidence({"model": "X", "wear_text": ""}) == "Модель: X"


def test_old_evidence_strings_are_converted() -> None:
    assert readable_evidence("model=WDC WD10EZEX, wear_text=") == "Модель: WDC WD10EZEX"
    assert readable_evidence("model=ARDOR 256Gb, wear_text=, износ 17%") == (
        "Модель: ARDOR 256Gb; износ 17%"
    )
    assert readable_evidence("tested_gb=7.96875") == "Проверено: 8,0 ГБ"
    assert readable_evidence("Модель: X") == "Модель: X"  # новое основание не трогаем


def test_metric_rows() -> None:
    rows = metric_rows({"clock_stable": True, "clock_drop_pct": 0.8, "mystery": 5})
    assert rows == [
        ("Снижение частоты", "0,8 %"),
        ("Частота стабильна", "да"),
        ("mystery", "5"),  # неизвестную метрику показываем как есть
    ]


@pytest.mark.parametrize("name", list_scenarios())
def test_reports_have_no_raw_keys(name: str) -> None:
    session = run_check(FakeBackend(name), "quick", threading.Event())
    assert session.verdict is not None
    for finding in session.verdict.findings:
        assert not RAW_KEY.search(finding.evidence), (finding.id, finding.evidence)
    for result in session.results:
        for label, _value in metric_rows(result.metrics):
            assert not RAW_KEY.fullmatch(label), (result.name, label)
    context = specialist_context(session)
    for row in context["findings"]:
        assert not RAW_KEY.search(row["evidence"]), row
    for test in context["tests"]:
        for label, _value in test["metrics"]:
            assert not RAW_KEY.fullmatch(label), (test["name"], label)
    for item in context["assessments"]:
        for fact in item.facts:
            assert not RAW_KEY.search(fact), fact


def test_old_check_evidence_is_readable_in_report() -> None:
    session = run_check(FakeBackend("healthy_gaming_pc"), "quick", threading.Event())
    assert session.verdict is not None
    for finding in session.verdict.findings:
        finding.evidence = "model=WDC WD10EZEX, wear_text="  # как сохраняла 2.1.0-rc1
    rows = specialist_context(session)["findings"]
    assert {row["evidence"] for row in rows} == {"Модель: WDC WD10EZEX"}
    html = builder.build_html(session, mode="specialist")
    assert "model=" not in html
