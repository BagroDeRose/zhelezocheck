"""Тесты правил вердикта: каждое правило срабатывает и не срабатывает; тексты без жаргона."""

import re
from collections.abc import Callable
from typing import Any

import pytest

from hwcheck.backends.fake import load_scenario
from hwcheck.models import (
    BatteryInfo,
    DiskInfo,
    EventSummary,
    HardwareSnapshot,
    MemoryInfo,
    MemoryModule,
    SensorSample,
    Severity,
    SmartData,
    TestResult,
    TestStatus,
)
from hwcheck.verdict import rules
from hwcheck.verdict.rules import RuleContext

# ---------------------------------------------------------------- помощники


def healthy() -> HardwareSnapshot:
    return load_scenario("healthy_gaming_pc").snapshot


def results_of(scenario: str) -> dict[str, TestResult]:
    stress = load_scenario(scenario).stress
    return {
        name: TestResult(name=name, status=spec.status, metrics=dict(spec.metrics))
        for name, spec in stress.items()
    }


def cpu_metrics(**metrics: float) -> dict[str, TestResult]:
    """Итоги здорового ПК, у теста процессора — заданные метрики (25.3)."""
    results = results_of("healthy_gaming_pc")
    results["cpu_load"] = TestResult(
        name="cpu_load", status=TestStatus.PASSED, metrics={"mismatches": 0, **metrics}
    )
    return results


def ctx(
    snapshot: HardwareSnapshot | None = None,
    results: dict[str, TestResult] | None = None,
    claimed_ram_gb: float | None = None,
) -> RuleContext:
    return RuleContext(
        snapshot=snapshot or healthy(),
        results=results if results is not None else results_of("healthy_gaming_pc"),
        claimed_ram_gb=claimed_ram_gb,
    )


def with_metrics(
    test: str, status: TestStatus = TestStatus.PASSED, **metrics: object
) -> dict[str, TestResult]:
    results = results_of("healthy_gaming_pc")
    results[test] = TestResult(name=test, status=status, metrics=dict(metrics))
    return results


def snap_with_disk(media: str = "hdd", **smart: Any) -> HardwareSnapshot:
    snap = healthy()
    snap.disks = [DiskInfo(model="Test Disk", media_type=media, smart=SmartData(**smart))]
    return snap


def snap_with_battery(design: int, full: int, cycles: int = 300) -> HardwareSnapshot:
    snap = healthy()
    snap.battery = BatteryInfo(
        design_capacity_mwh=design, full_charge_capacity_mwh=full, cycle_count=cycles
    )
    return snap


def snap_with_events(**counts: int) -> HardwareSnapshot:
    snap = healthy()
    snap.events = EventSummary(
        counts=dict(counts), last_seen={k: "2026-10-01T10:00:00" for k in counts}
    )
    return snap


def mining_gpu_snapshot() -> HardwareSnapshot:
    return load_scenario("mining_gpu").snapshot


# ---------------------------------------------------------------- таблица «срабатывает / нет»

Case = Callable[[], RuleContext]

CASES: dict[str, tuple[Case, Case]] = {
    "gpu.fake": (
        lambda: ctx(load_scenario("fake_gpu_relabel").snapshot),
        lambda: ctx(),
    ),
    "gpu.vram_errors": (
        lambda: ctx(results=with_metrics("vram", TestStatus.FAILED, errors=58)),
        lambda: ctx(),
    ),
    "gpu.emergency_stop": (
        lambda: ctx(
            results=with_metrics(
                "gpu_load", TestStatus.FAILED, emergency_stop=True, max_temp_c=91.0
            )
        ),
        lambda: ctx(),
    ),
    "gpu.overheat": (
        lambda: ctx(results=with_metrics("gpu_load", max_temp_c=86.0)),
        lambda: ctx(results=with_metrics("gpu_load", max_temp_c=79.0)),
    ),
    "gpu.thermal_throttle": (
        lambda: ctx(results=with_metrics("gpu_load", thermal_throttle=True, clock_drop_pct=9.0)),
        lambda: ctx(results=with_metrics("gpu_load", thermal_throttle=False, clock_drop_pct=4.0)),
    ),
    "gpu.fan_worn": (
        lambda: ctx(mining_gpu_snapshot(), results_of("mining_gpu")),
        lambda: ctx(),
    ),
    "gpu.fan_not_spinning": (
        lambda: ctx(results=with_metrics("gpu_load", fan_not_spinning=True, max_temp_c=80.0)),
        lambda: ctx(),
    ),
    "gpu.mining_bios": (
        lambda: ctx(mining_gpu_snapshot(), results_of("mining_gpu")),
        lambda: ctx(),
    ),
    "gpu.pcie_reduced": (
        lambda: ctx(mining_gpu_snapshot(), results_of("mining_gpu")),
        lambda: ctx(),
    ),
    "gpu.mining_popular": (
        lambda: ctx(mining_gpu_snapshot(), results_of("mining_gpu")),
        lambda: ctx(load_scenario("fake_gpu_relabel").snapshot),
    ),
    "gpu.unknown_model": (
        lambda: ctx(load_scenario("laptop_worn_battery").snapshot),
        lambda: ctx(),
    ),
    "gpu.ok": (
        lambda: ctx(),
        lambda: ctx(results=with_metrics("vram", TestStatus.FAILED, errors=3)),
    ),
    "cpu.instability": (
        lambda: ctx(
            results=with_metrics("cpu_load", TestStatus.FAILED, checksum_ok=False, mismatches=2)
        ),
        lambda: ctx(),
    ),
    "cpu.clock_drop": (
        lambda: ctx(results=results_of("overheating_cpu")),
        lambda: ctx(),
    ),
    "cpu.ok": (
        lambda: ctx(),
        lambda: ctx(results=results_of("overheating_cpu")),
    ),
    "cpu.temp_zone": (
        lambda: ctx(results=cpu_metrics(zone_temp_max_c=71.0, start_clock_mhz=4000)),
        lambda: ctx(results=cpu_metrics(start_clock_mhz=4000)),
    ),
    "cpu.temp_unmeasured": (
        lambda: ctx(results=cpu_metrics(start_clock_mhz=4000)),
        lambda: ctx(results=cpu_metrics(zone_temp_max_c=71.0, start_clock_mhz=4000)),
    ),
    "ram.errors": (
        lambda: ctx(results=results_of("ram_errors")),
        lambda: ctx(),
    ),
    "ram.less_than_claimed": (
        lambda: ctx(claimed_ram_gb=64),
        lambda: ctx(claimed_ram_gb=32),
    ),
    "ram.mixed": (
        lambda: ctx(load_scenario("ram_errors").snapshot),
        lambda: ctx(),
    ),
    "ram.ok": (
        lambda: ctx(),
        lambda: ctx(results=results_of("ram_errors")),
    ),
    "disk.smart_failed": (
        lambda: ctx(snap_with_disk(health_passed=False)),
        lambda: ctx(snap_with_disk(health_passed=True)),
    ),
    "disk.sectors_critical": (
        lambda: ctx(snap_with_disk(reallocated_sectors=40, pending_sectors=20)),
        lambda: ctx(snap_with_disk(reallocated_sectors=40, pending_sectors=10)),
    ),
    "disk.sectors_warning": (
        lambda: ctx(snap_with_disk(reallocated_sectors=1, pending_sectors=0)),
        lambda: ctx(snap_with_disk(reallocated_sectors=0, pending_sectors=0)),
    ),
    "disk.ssd_wear_critical": (
        lambda: ctx(snap_with_disk(media="ssd", wear_percent=97.0)),
        lambda: ctx(snap_with_disk(media="ssd", wear_percent=95.0)),
    ),
    "disk.ssd_wear_warning": (
        lambda: ctx(load_scenario("worn_ssd").snapshot),
        lambda: ctx(snap_with_disk(media="ssd", wear_percent=80.0)),
    ),
    "disk.crc": (
        lambda: ctx(snap_with_disk(crc_errors=3)),
        lambda: ctx(snap_with_disk(crc_errors=0)),
    ),
    "disk.read_errors": (
        lambda: ctx(results=results_of("dying_hdd")),
        lambda: ctx(),
    ),
    "disk.hdd_old": (
        lambda: ctx(snap_with_disk(power_on_hours=46800)),
        lambda: ctx(snap_with_disk(power_on_hours=14000)),
    ),
    "disk.ok": (
        lambda: ctx(),
        lambda: ctx(snap_with_disk(reallocated_sectors=5)),
    ),
    "system.whea": (
        lambda: ctx(snap_with_events(whea=2)),
        lambda: ctx(snap_with_events(whea=0)),
    ),
    "system.disk_events": (
        lambda: ctx(load_scenario("dying_hdd").snapshot),
        lambda: ctx(),
    ),
    "system.disk_events_removable": (
        lambda: ctx(snap_with_events(disk_removable=7)),
        lambda: ctx(snap_with_events(disk_removable=0)),
    ),
    "system.crashes": (
        lambda: ctx(snap_with_events(bugcheck=1, kernel_power_41=0)),
        lambda: ctx(snap_with_events(bugcheck=0, kernel_power_41=0)),
    ),
    "battery.wear_bargain": (
        lambda: ctx(snap_with_battery(80000, 39000)),
        lambda: ctx(snap_with_battery(80000, 41000)),
    ),
    "battery.wear_warning": (
        lambda: ctx(snap_with_battery(80000, 52000)),
        lambda: ctx(snap_with_battery(80000, 60000)),
    ),
    "battery.cycles_high": (
        lambda: ctx(snap_with_battery(80000, 70000, cycles=900)),
        lambda: ctx(snap_with_battery(80000, 70000, cycles=300)),
    ),
    "battery.ok": (
        lambda: ctx(snap_with_battery(80000, 70000)),
        lambda: ctx(snap_with_battery(80000, 40000)),
    ),
}


def test_every_rule_has_cases_and_texts() -> None:
    texts, _ = rules.load_rule_texts()
    assert set(CASES) == set(rules.RULES) == set(texts)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_fires(rule_id: str) -> None:
    fires, _ = CASES[rule_id]
    evidence = rules.RULES[rule_id](fires())
    assert evidence, f"{rule_id} должно сработать"
    finding = rules.make_finding(rule_id, evidence[0])
    assert finding.title and finding.explanation
    assert "{" not in finding.explanation + finding.title + finding.advice


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_does_not_fire(rule_id: str) -> None:
    _, quiet = CASES[rule_id]
    assert rules.RULES[rule_id](quiet()) == [], f"{rule_id} не должно срабатывать"


def test_bargain_texts_format() -> None:
    ctx_ = ctx(snap_with_battery(80000, 39000))
    (evidence,) = rules.check_battery_wear_bargain(ctx_)
    finding = rules.make_finding("battery.wear_bargain", evidence)
    text = rules.bargain_text(finding, evidence)
    assert text is not None and "51%" in text


def test_emergency_takes_temperature_from_samples() -> None:
    results = with_metrics("gpu_load", TestStatus.FAILED, emergency_stop=True)
    results["gpu_load"].samples = [SensorSample(t=1, component="gpu0", values={"temp_c": 92.0})]
    (evidence,) = rules.check_gpu_emergency_stop(ctx(results=results))
    assert evidence["temp"] == 92.0
    assert rules.check_gpu_overheat(ctx(results=results)) == []  # не дублируем


def test_per_disk_findings() -> None:
    snap = healthy()
    snap.disks = [
        DiskInfo(model="A", media_type="hdd", smart=SmartData(reallocated_sectors=3)),
        DiskInfo(model="B", media_type="hdd", smart=SmartData(reallocated_sectors=0)),
    ]
    found = rules.check_disk_sectors_warning(ctx(snap))
    assert [e["model"] for e in found] == ["A"]
    assert [e["model"] for e in rules.check_disk_ok(ctx(snap))] == ["B"]


def test_mixed_memory_details() -> None:
    snap = healthy()
    snap.memory = MemoryInfo(
        total_mb=16384,
        modules=[
            MemoryModule(
                capacity_mb=8192, speed_mhz=3200, manufacturer="Kingston", part_number="X"
            ),
            MemoryModule(capacity_mb=8192, speed_mhz=2666, manufacturer="Corsair", part_number="Y"),
        ],
    )
    (evidence,) = rules.check_ram_mixed(ctx(snap))
    assert "2666" in evidence["details"]


def test_evaluate_rules_on_healthy_has_only_ok_and_info() -> None:
    found = rules.evaluate_rules(ctx())
    severities = {finding.severity for finding, _ in found}
    assert severities <= {Severity.OK, Severity.INFO}
    assert {"gpu.ok", "cpu.ok", "ram.ok", "disk.ok"} <= {f.id for f, _ in found}


# ---------------------------------------------------------------- тексты без жаргона

STOP_WORDS = [
    "троттлинг",
    "WHEA",
    "PCIe",
    "CRC",
    "TDP",
    "VRAM",
    "BIOS",
    "S.M.A.R.T",
    "BugCheck",
    "Kernel-Power",
    "throttl",
    "SMART",
]


def test_texts_are_russian_and_explain_jargon() -> None:
    texts, _ = rules.load_rule_texts()
    for rule in texts.values():
        for text in (rule.title, rule.explanation, rule.advice, rule.bargain or ""):
            if not re.sub(r"[{][^}]*[}]", "", text).strip():
                continue  # текст целиком подставляется из других модулей
            assert re.search("[а-яА-Я]", text), f"{rule.id}: текст не на русском"
            for word in STOP_WORDS:
                for match in re.finditer(re.escape(word), text):
                    after = text[match.end() : match.end() + 3]
                    assert "(" in after, f"{rule.id}: «{word}» без пояснения в скобках"


def test_battery_autonomy_estimate() -> None:
    # 44 Вт·ч при лёгкой работе (~11 Вт по порогу) — около 4 часов.
    (evidence,) = rules.check_battery_wear_warning(ctx(snap_with_battery(80000, 44000 + 8000)))
    finding = rules.make_finding("battery.wear_warning", evidence)
    assert "ч " in finding.explanation or "ч)" in finding.explanation
    assert evidence["hours"] == pytest.approx(52000 / 1000 / 11, rel=0.01)


def test_removable_disk_errors_do_not_worsen_verdict() -> None:
    """15.8: ошибки только флешек — к сведению; внутреннего диска — предупреждение."""
    from hwcheck.models import Severity
    from hwcheck.verdict.engine import decide

    usb_only = decide(snap_with_events(disk_removable=7, disk=0), [])
    found = {f.id: f for f in usb_only.findings}
    assert "system.disk_events" not in found
    assert found["system.disk_events_removable"].severity is Severity.INFO
    internal = decide(snap_with_events(disk=2), [])
    assert any(
        f.id == "system.disk_events" and f.severity is Severity.WARNING for f in internal.findings
    )


def test_cpu_temperature_is_information_not_warning() -> None:
    """25.3: без датчика температуры — спокойная находка «к сведению», а не предупреждение."""
    evidence = rules.RULES["cpu.temp_unmeasured"](ctx(results=cpu_metrics(start_clock_mhz=4000)))
    finding = rules.make_finding("cpu.temp_unmeasured", evidence[0])
    assert finding.severity.value == "info" and finding.weight == 0
    assert "напрямую не измеряется" in finding.explanation and "PawnIO" not in finding.explanation
    zone = rules.RULES["cpu.temp_zone"](ctx(results=cpu_metrics(zone_temp_max_c=71.0)))
    assert "примерно" in rules.make_finding("cpu.temp_zone", zone[0]).title
