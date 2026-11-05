"""Отчёт «Для покупателя» (SPEC_V2_1, этап 47; MVP-спека, 3.1 и 8.2).

Короткий отчёт строится из уже вынесенного вердикта и его находок — логика диагностики
здесь не повторяется. Содержимое: вердикт и объяснение, 3–6 причин по важности, состояние
ключевых компонентов (Норма / Внимание / Критично / Не проверено), проблемы и их практическое
значение, что не удалось проверить, несовпадения с объявлением, что проверить вручную перед
оплатой (`data/buyer_checklist.yaml`), аргументы для торга, дата, длительность и режим.
Графики покупателю не показываются.

Честность: компонент, который не проверяли (тест не запускался или прерван, находок нет),
получает «Не проверено», а не «Норма». Оценка компонентов с уверенностью — общая со
специалистом (`verdict/assessment.py`).
"""

from __future__ import annotations

from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir
from hwcheck.models import CheckSession, Finding, Severity, is_discrete_gpu
from hwcheck.report.specialist import duration_text
from hwcheck.ui import strings
from hwcheck.verdict.assessment import (
    STATE_ATTENTION,
    STATE_CRITICAL,
    STATE_NORMAL,
    STATE_NOT_CHECKED,
    assess_components,
)

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.OK: 3}
STATE_KEYS = {
    STATE_NORMAL: "normal",
    STATE_ATTENTION: "attention",
    STATE_CRITICAL: "critical",
    STATE_NOT_CHECKED: "not_checked",
}
MIN_REASONS, MAX_REASONS = 3, 6


@cache
def _checklist() -> list[dict[str, str]]:
    text = (package_data_dir() / "buyer_checklist.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["items"]


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], -f.weight))


def _finding_dict(finding: Finding) -> dict[str, str]:
    return {
        "title": finding.title,
        "explanation": finding.explanation,
        "advice": finding.advice,
        "impact": finding.impact,
        "severity_key": finding.severity.value,
        "severity": strings.SEVERITY_NAMES.get(finding.severity.value, finding.severity.value),
    }


def reasons(findings: list[Finding]) -> list[dict[str, str]]:
    """3–6 главных причин вердикта: сначала проблемы, затем к сведению, затем «в порядке».

    Несовпадение с объявлением — тоже причина (ручная проверка 2.1.0-rc3: «Уходить» из-за не
    той видеокарты, а в причинах — одни «к сведению»). Совпадения с объявлением в причины не
    попадают — они в разделе «Объявление»."""
    ordered = [
        f
        for f in _sorted(findings)
        if f.component != "listing" or f.severity in (Severity.CRITICAL, Severity.WARNING)
    ]
    problems = [f for f in ordered if f.severity in (Severity.CRITICAL, Severity.WARNING)]
    chosen = problems[:MAX_REASONS]
    for finding in ordered:
        if len(chosen) >= MIN_REASONS:
            break
        if finding not in chosen:
            chosen.append(finding)
    return [_finding_dict(f) for f in chosen]


def components(session: CheckSession) -> list[dict[str, str]]:
    """Ключевые компоненты: состояние, причина и уверенность (`verdict/assessment.py`)."""
    return [
        {
            "name": item.name,
            "state": item.state,
            "state_key": STATE_KEYS[item.state],
            "text": item.reason,
            "confidence": item.confidence,
        }
        for item in assess_components(session)
    ]


def manual_checks(session: CheckSession) -> list[str]:
    """Что проверить руками перед оплатой — пункты, подходящие этому компьютеру."""
    snap = session.snapshot
    verdict = session.verdict
    conditions = {
        "always": True,
        "laptop": bool(snap.system and snap.system.is_laptop) or snap.battery is not None,
        "discrete_gpu": any(is_discrete_gpu(gpu) for gpu in snap.gpus),
        "hdd": any(disk.media_type == "hdd" for disk in snap.disks),
        "not_checked": bool(verdict and verdict.not_checked),
        "listing": session.listing is not None,
    }
    return [item["text"] for item in _checklist() if conditions.get(item["when"], False)]


def buyer_context(session: CheckSession) -> dict[str, Any]:
    """Всё для короткого отчёта покупателя."""
    verdict = session.verdict
    decision = verdict.decision.value if verdict else "negotiate"
    findings = verdict.findings if verdict else []
    problems = [
        _finding_dict(f)
        for f in _sorted(findings)
        if f.severity in (Severity.CRITICAL, Severity.WARNING) and f.component != "listing"
    ]
    mismatches = [
        _finding_dict(f)
        for f in _sorted(findings)
        if f.component == "listing" and f.severity in (Severity.CRITICAL, Severity.WARNING)
    ]
    return {
        "decision": decision,
        "decision_title": strings.DECISION_TITLES[decision],
        "summary": verdict.summary if verdict else "",
        "reasons": reasons(findings),
        "components": components(session),
        "problems": problems,
        "not_checked": verdict.not_checked if verdict else [],
        "listing_mismatches": mismatches,
        "manual_checks": manual_checks(session),
        "bargaining": verdict.bargaining_points if verdict else [],
        "mode": strings.MODE_TITLES.get(session.mode, session.mode),
        "duration": duration_text(session.started_at, session.finished_at) or "—",
    }
