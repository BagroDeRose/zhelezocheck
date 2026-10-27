"""Итоговый вердикт: «Брать», «Торговаться» или «Уходить» — с причинами.

Логика простая и прозрачная:
- есть хоть одна серьёзная проблема (critical) → «Уходить»;
- иначе, если суммарный вес недостатков (warning) достиг порога из rules.yaml → «Торговаться»,
  и к вердикту прикладывается список аргументов для торга;
- иначе → «Брать».

Список «что не удалось проверить» формируется всегда: пропущенные и сорвавшиеся тесты,
сборщики с ошибками, неполный журнал событий, диски без S.M.A.R.T., недоступные датчики.
"""

from __future__ import annotations

from hwcheck.backends.base import ALL_STRESS_TESTS, STRESS_CPU_LOAD, STRESS_GPU_LOAD
from hwcheck.models import (
    Decision,
    Finding,
    HardwareSnapshot,
    Severity,
    TestResult,
    TestStatus,
    Verdict,
)
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.ui import strings
from hwcheck.verdict.rules import RuleContext, bargain_text, evaluate_rules, load_rule_texts

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.OK: 3}


def not_checked(
    snapshot: HardwareSnapshot, results: dict[str, TestResult], expected_tests: list[str]
) -> list[str]:
    """Что проверить не удалось — всегда показывается покупателю."""
    items: list[str] = []
    for name in expected_tests:
        title = strings.TEST_NAMES.get(name, name)
        result = results.get(name)
        if result is None:
            items.append(f"{title} — не проводился.")
        elif result.status in (TestStatus.SKIPPED, TestStatus.ERROR):
            reason = result.notes[0] if result.notes else "причина неизвестна"
            items.append(f"{title} — {reason}")
    for name, error in snapshot.errors.items():
        items.append(f"{strings.COLLECTOR_NAMES.get(name, name)} — {error}")
    if snapshot.events is not None and snapshot.events.partial:
        items.append(f"{strings.COLLECTOR_NAMES['events']} — {snapshot.events.note}")
    for disk in snapshot.disks:
        if disk.smart is None:
            items.append(f"Здоровье диска «{disk.model}» — {disk.note or 'данные недоступны.'}")
    gpu_load = results.get(STRESS_GPU_LOAD)
    if gpu_load is not None and gpu_load.status not in (TestStatus.SKIPPED, TestStatus.ERROR):
        if gpu_load.metrics.get("max_temp_c") is None:
            items.append(strings.GPU_TEMPERATURE_NOT_CHECKED)
    cpu_load = results.get(STRESS_CPU_LOAD)
    if cpu_load is not None and cpu_load.status not in (TestStatus.SKIPPED, TestStatus.ERROR):
        if "start_clock_mhz" not in cpu_load.metrics:
            # Без частоты перегрев процессора оценить нечем (25.3: иначе — находка «к сведению»).
            items.append(strings.CPU_OVERHEAT_NOT_CHECKED)
    return items


def decide(
    snapshot: HardwareSnapshot,
    results: list[TestResult] | dict[str, TestResult],
    claimed_ram_gb: float | None = None,
    extra_findings: list[tuple[Finding, str | None]] | None = None,
    expected_tests: list[str] | None = None,
    thresholds: Thresholds | None = None,
) -> Verdict:
    """Выносит вердикт по снимку железа и итогам тестов.

    `extra_findings` — находки из других источников (например, сверка с объявлением),
    вместе с аргументом для торга (или None).
    """
    by_name = results if isinstance(results, dict) else {r.name: r for r in results}
    ctx = RuleContext(
        snapshot=snapshot,
        results=by_name,
        thresholds=thresholds or load_thresholds(),
        claimed_ram_gb=claimed_ram_gb,
    )
    pairs = [
        (finding, bargain_text(finding, evidence)) for finding, evidence in evaluate_rules(ctx)
    ]
    pairs += extra_findings or []
    pairs.sort(key=lambda pair: (_SEVERITY_ORDER[pair[0].severity], -pair[0].weight))
    findings = [finding for finding, _ in pairs]

    _, negotiate_min = load_rule_texts()
    critical = [f for f in findings if f.severity is Severity.CRITICAL]
    warnings = [f for f in findings if f.severity is Severity.WARNING]
    warning_weight = sum(f.weight for f in warnings)
    if critical:
        decision = Decision.WALK_AWAY
    elif warning_weight >= negotiate_min:
        decision = Decision.NEGOTIATE
    else:
        decision = Decision.BUY
    bargaining = [text for finding, text in pairs if finding.severity is Severity.WARNING and text]

    expected = expected_tests if expected_tests is not None else ALL_STRESS_TESTS
    return Verdict(
        decision=decision,
        findings=findings,
        not_checked=not_checked(snapshot, by_name, expected),
        score=round(sum(f.weight for f in critical) + warning_weight, 2),
        bargaining_points=bargaining if decision is Decision.NEGOTIATE else [],
        summary=strings.DECISION_SUMMARIES[decision.value],
    )
