"""Оценка компонентов (SPEC_V2_1, этап 49; MVP-спека, 6.2).

Для каждого ключевого компонента — видеокарт, процессора, памяти, накопителей, батареи:
- состояние: Норма / Внимание / Критично / Не проверено;
- причина (главная находка или итог теста);
- факты, на которых оценка основана (улики правил, состояния тестов);
- уверенность: высокий / средний / низкий;
- что по этому компоненту не проверено.

Правила уверенности (простые и объяснимые, без «балла»):
- «Критично»/«Внимание» — уверенность главного правила из `rules.yaml` (`confidence`, по
  умолчанию «высокий»; у косвенных признаков — «средний» или «низкий»);
- «Норма» — «высокий», если тест компонента пройден, во время него были замеры датчиков и
  по компоненту нет непроверенного (например, температуры процессора); иначе «средний» —
  в том числе когда вывод сделан только по данным без нагрузки (S.M.A.R.T., батарея);
- «Не проверено» — «низкий».
Недоступный датчик не штрафуется: он снижает уверенность, а не состояние.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hwcheck.models import (
    CheckSession,
    CheckState,
    Finding,
    Severity,
    TestResult,
    check_state,
    is_discrete_gpu,
    is_external_usb,
)
from hwcheck.report.labels import readable_evidence
from hwcheck.verdict.rules import load_rule_texts

STATE_NORMAL, STATE_ATTENTION, STATE_CRITICAL, STATE_NOT_CHECKED = (
    "Норма",
    "Внимание",
    "Критично",
    "Не проверено",
)
CONFIDENCE_LEVELS = ("высокий", "средний", "низкий")
STATE_NAMES = {
    CheckState.NOT_CHECKED: "не проверено",
    CheckState.PASSED: "проверено — ошибок нет",
    CheckState.PROBLEMS: "проверено — обнаружены проблемы",
    CheckState.INTERRUPTED: "проверка прервана",
}
_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2, Severity.OK: 3}
TEST_NAMES = {
    "vram": "тест видеопамяти",
    "gpu_load": "нагрузка видеокарты",
    "cpu_load": "нагрузка процессора",
    "ram_quick": "быстрый тест памяти",
    "disk_read": "тест чтения диска",
}


@dataclass
class ComponentAssessment:
    name: str
    state: str
    reason: str
    confidence: str
    facts: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_ORDER[f.severity], -f.weight))


def _rule_confidence(finding: Finding) -> str:
    texts, _ = load_rule_texts()
    rule = texts.get(finding.id)
    return rule.confidence if rule else "средний"  # находки объявления — по словам продавца


def _assess(
    name: str, findings: list[Finding], results: list[TestResult], tests: tuple[str, ...]
) -> ComponentAssessment:
    own_results = [r for r in results if r.name in tests]
    states = {r.name: check_state(r) for r in own_results}
    facts = [f"{f.title}: {readable_evidence(f.evidence)}" for f in _sorted(findings) if f.evidence]
    facts += [f"{TEST_NAMES.get(n, n).capitalize()}: {STATE_NAMES[s]}" for n, s in states.items()]
    not_checked = [
        TEST_NAMES.get(test, test)
        for test in tests
        if states.get(test, CheckState.NOT_CHECKED)
        in (CheckState.NOT_CHECKED, CheckState.INTERRUPTED)
    ]
    not_checked += [f.title for f in findings if f.id.endswith("_unmeasured")]
    if findings:
        worst = _sorted(findings)[0]
        if worst.severity in (Severity.CRITICAL, Severity.WARNING):
            state = STATE_CRITICAL if worst.severity is Severity.CRITICAL else STATE_ATTENTION
            return ComponentAssessment(
                name, state, worst.title, _rule_confidence(worst), facts, not_checked
            )
    tested = [r for r in own_results if states[r.name] in (CheckState.PASSED, CheckState.PROBLEMS)]
    ok = [f for f in findings if f.severity is Severity.OK]
    remarks = [f for f in findings if f.severity is Severity.INFO]
    if not tested and not ok:
        interrupted = any(s is CheckState.INTERRUPTED for s in states.values())
        reason = (
            "Проверка была прервана."
            if interrupted
            else "Тест не проводился, данных для вывода нет."
        )
        return ComponentAssessment(name, STATE_NOT_CHECKED, reason, "низкий", facts, not_checked)
    reason = ok[0].title.rstrip(".") + "." if ok else "Проверено, замечаний нет."
    if remarks:
        reason += f" Есть замечание: {remarks[0].title.rstrip('.')}."
    with_sensors = any(r.samples for r in tested)
    # Ручная проверка 2.1.0-rc1: «Процессор — Норма, высокий» при неизмеренной температуре.
    # Если что-то по компоненту не проверено, уверенность не выше средней.
    confidence = "высокий" if tested and with_sensors and not not_checked else "средний"
    return ComponentAssessment(name, STATE_NORMAL, reason, confidence, facts, not_checked)


def assess_components(session: CheckSession) -> list[ComponentAssessment]:
    """Оценки ключевых компонентов проверки (из находок вердикта и итогов тестов)."""
    snap = session.snapshot
    findings = session.verdict.findings if session.verdict else []
    results = session.results

    def of(*components: str) -> list[Finding]:
        return [f for f in findings if f.component in components]

    assessments: list[ComponentAssessment] = []
    gpus = [gpu for gpu in snap.gpus if is_discrete_gpu(gpu)] or snap.gpus
    for gpu in gpus:
        assessments.append(
            _assess(
                f"Видеокарта: {gpu.name}",
                of(f"gpu:{gpu.name}", "gpu"),
                results,
                ("vram", "gpu_load"),
            )
        )
    assessments.append(_assess("Процессор", of("cpu"), results, ("cpu_load",)))
    assessments.append(_assess("Оперативная память", of("memory"), results, ("ram_quick",)))
    for disk in snap.disks:
        if is_external_usb(disk):
            continue  # флешка с программой — не часть покупаемого компьютера
        assessments.append(
            _assess(f"Накопитель: {disk.model}", of(f"disk:{disk.model}"), results, ())
        )
    if snap.battery is not None:
        assessments.append(_assess("Батарея", of("battery"), results, ()))
    return assessments
