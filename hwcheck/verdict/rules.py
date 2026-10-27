"""Правила вердикта: из сведений о железе и итогов тестов — список находок (Finding).

Каждое правило — функция `check_<имя>` с тем же id, что в `data/rules.yaml`.
Функция получает контекст (снимок, итоги тестов, пороги, заявленное в объявлении) и
возвращает список «улик» — словарей со значениями для подстановки в текст правила.
Пустой список — правило не сработало. Одно правило может сработать несколько раз
(например, для каждого из дисков).

Тексты, важность и веса берутся из `rules.yaml`, числовые пороги — из `thresholds.json`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import yaml

from hwcheck.backends.base import (
    STRESS_CPU_LOAD,
    STRESS_DISK_READ,
    STRESS_GPU_LOAD,
    STRESS_RAM_QUICK,
    STRESS_VRAM,
)
from hwcheck.collectors.memory import is_mixed
from hwcheck.config import package_data_dir
from hwcheck.knowledge.gpu_db import Identification, IdentStatus, identify
from hwcheck.models import (
    DiskInfo,
    Finding,
    GpuInfo,
    HardwareSnapshot,
    Severity,
    TestResult,
    TestStatus,
    is_discrete_gpu,
)
from hwcheck.thresholds import Thresholds, load_thresholds

Evidence = dict[str, Any]


@dataclass
class RuleContext:
    """Всё, на что смотрят правила."""

    snapshot: HardwareSnapshot
    results: dict[str, TestResult] = field(default_factory=dict)
    thresholds: Thresholds = field(default_factory=load_thresholds)
    claimed_ram_gb: float | None = None  # из объявления (этап 8)

    def result(self, name: str) -> TestResult | None:
        return self.results.get(name)

    def metric(self, name: str, key: str) -> Any:
        result = self.results.get(name)
        return None if result is None else result.metrics.get(key)

    _identifications: dict[int, Identification] = field(default_factory=dict, repr=False)

    def identification(self, index: int) -> Identification:
        """Проверка видеокарты на подделку (считается один раз на видеокарту)."""
        if index not in self._identifications:
            self._identifications[index] = identify(self.snapshot.gpus[index])
        return self._identifications[index]


@dataclass(frozen=True)
class RuleText:
    """Описание правила из rules.yaml."""

    id: str
    component: str
    severity: Severity
    weight: float
    title: str
    explanation: str
    advice: str
    bargain: str | None


@cache
def load_rule_texts() -> tuple[dict[str, RuleText], float]:
    """Тексты правил и минимальный суммарный вес для «Торговаться»."""
    data = yaml.safe_load((package_data_dir() / "rules.yaml").read_text(encoding="utf-8"))
    texts = {
        rule_id: RuleText(
            id=rule_id,
            component=item["component"],
            severity=Severity(item["severity"]),
            weight=float(item.get("weight", 0)),
            title=item["title"],
            explanation=item.get("explanation", ""),
            advice=item.get("advice", ""),
            bargain=item.get("bargain"),
        )
        for rule_id, item in data["rules"].items()
    }
    return texts, float(data.get("negotiate_min_weight", 1.0))


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def main_gpu_index(snapshot: HardwareSnapshot) -> int | None:
    """Индекс видеокарты, которую нагружали тесты: дискретная с наибольшей памятью."""
    discrete = [i for i, g in enumerate(snapshot.gpus) if is_discrete_gpu(g)]
    candidates = discrete or list(range(len(snapshot.gpus)))
    if not candidates:
        return None
    return max(candidates, key=lambda i: snapshot.gpus[i].vram_mb or 0)


def _gpu_label(gpu: GpuInfo) -> str:
    return f"gpu:{gpu.name}"


def _disk_label(disk: DiskInfo) -> str:
    return f"disk:{disk.model}"


def _sectors(disk: DiskInfo) -> int:
    smart = disk.smart
    if smart is None:
        return 0
    return (smart.reallocated_sectors or 0) + (smart.pending_sectors or 0)


def _gpu_load_metrics(ctx: RuleContext) -> dict[str, Any]:
    result = ctx.result(STRESS_GPU_LOAD)
    return result.metrics if result is not None and result.status != TestStatus.SKIPPED else {}


def _main_gpu(ctx: RuleContext) -> GpuInfo | None:
    index = main_gpu_index(ctx.snapshot)
    return None if index is None else ctx.snapshot.gpus[index]


def _typical_temp(ctx: RuleContext) -> float:
    index = main_gpu_index(ctx.snapshot)
    if index is not None:
        claimed = ctx.identification(index).claimed
        if claimed is not None:
            return claimed.typical_max_temp_c
    return ctx.thresholds.get("gpu.warning_c")


# ---------------------------------------------------------------------------
# Видеокарта
# ---------------------------------------------------------------------------


def check_gpu_fake(ctx: RuleContext) -> list[Evidence]:
    found = []
    for index, gpu in enumerate(ctx.snapshot.gpus):
        ident = ctx.identification(index)
        if ident.status is IdentStatus.FAKE:
            found.append({"component": _gpu_label(gpu), "reasons": " ".join(ident.reasons)})
    return found


def check_gpu_vram_errors(ctx: RuleContext) -> list[Evidence]:
    errors = ctx.metric(STRESS_VRAM, "errors") or 0
    gpu = _main_gpu(ctx)
    if errors > 0 and gpu is not None:
        return [{"component": _gpu_label(gpu), "errors": errors}]
    return []


def _max_gpu_temp(ctx: RuleContext) -> float | None:
    temps = [ctx.metric(STRESS_GPU_LOAD, "max_temp_c")]
    for name in (STRESS_GPU_LOAD, STRESS_VRAM):
        result = ctx.result(name)
        if result is not None:
            temps += [
                s.values.get("temp_c") for s in result.samples if s.component.startswith("gpu")
            ]
    known = [t for t in temps if t is not None]
    return max(known) if known else None


def check_gpu_emergency_stop(ctx: RuleContext) -> list[Evidence]:
    stopped = any(
        (ctx.metric(name, "emergency_stop") is True) for name in (STRESS_GPU_LOAD, STRESS_VRAM)
    )
    gpu = _main_gpu(ctx)
    if stopped and gpu is not None:
        temp = _max_gpu_temp(ctx) or ctx.thresholds.get("gpu.emergency_stop_c")
        return [{"component": _gpu_label(gpu), "temp": temp}]
    return []


def check_gpu_overheat(ctx: RuleContext) -> list[Evidence]:
    if check_gpu_emergency_stop(ctx):
        return []  # аварийная остановка уже описывает перегрев
    temp = _gpu_load_metrics(ctx).get("max_temp_c")
    gpu = _main_gpu(ctx)
    if gpu is not None and temp is not None and temp >= ctx.thresholds.get("gpu.warning_c"):
        return [{"component": _gpu_label(gpu), "temp": temp, "typical": _typical_temp(ctx)}]
    return []


def check_gpu_thermal_throttle(ctx: RuleContext) -> list[Evidence]:
    metrics = _gpu_load_metrics(ctx)
    drop = metrics.get("clock_drop_pct") or 0.0
    gpu = _main_gpu(ctx)
    if gpu is None:
        return []
    if metrics.get("thermal_throttle") or drop > ctx.thresholds.get("gpu.clock_drop_pct"):
        return [{"component": _gpu_label(gpu), "drop": drop}]
    return []


def check_gpu_fan_worn(ctx: RuleContext) -> list[Evidence]:
    metrics = _gpu_load_metrics(ctx)
    gpu = _main_gpu(ctx)
    fan, temp = metrics.get("max_fan_pct"), metrics.get("max_temp_c")
    if gpu is None or fan is None or temp is None:
        return []
    explicit = metrics.get("fan_high_at_moderate_temp")
    computed = fan >= ctx.thresholds.get("gpu.fan_high_pct") and temp < ctx.thresholds.get(
        "gpu.fan_moderate_temp_c"
    )
    if explicit or (explicit is None and computed):
        return [{"component": _gpu_label(gpu), "fan": fan, "temp": temp}]
    return []


def check_gpu_fan_not_spinning(ctx: RuleContext) -> list[Evidence]:
    metrics = _gpu_load_metrics(ctx)
    gpu = _main_gpu(ctx)
    if gpu is not None and metrics.get("fan_not_spinning"):
        return [{"component": _gpu_label(gpu), "temp": metrics.get("max_temp_c") or 0.0}]
    return []


def check_gpu_mining_bios(ctx: RuleContext) -> list[Evidence]:
    found = []
    power_ratio = ctx.thresholds.get("gpu.power_limit_low_ratio")
    clock_ratio = ctx.thresholds.get("gpu.core_clock_low_ratio")
    for index, gpu in enumerate(ctx.snapshot.gpus):
        ident = ctx.identification(index)
        card = ident.claimed
        if ident.status is not IdentStatus.MATCH or card is None:
            continue
        details = []
        limit = gpu.default_power_limit_w
        if limit is not None and limit < card.tdp_w * power_ratio:
            details.append(
                f"Лимит мощности по умолчанию {limit:.0f} Вт, а у этой модели должен быть "
                f"около {card.tdp_w:.0f} Вт."
            )
        max_core = gpu.max_clocks.get("graphics")
        if max_core and max_core < card.boost_clock_mhz * clock_ratio:
            details.append(
                f"Максимальная частота ядра {max_core} МГц, а у этой модели — от "
                f"{card.boost_clock_mhz} МГц."
            )
        if details:
            found.append({"component": _gpu_label(gpu), "details": " ".join(details)})
    return found


def check_gpu_pcie_reduced(ctx: RuleContext) -> list[Evidence]:
    ratio = ctx.thresholds.get("gpu.pcie_width_ratio")
    found = []
    for gpu in ctx.snapshot.gpus:
        current, maximum = gpu.pcie_width_current, gpu.pcie_width_max
        if current and maximum and current < maximum * ratio:
            found.append({"component": _gpu_label(gpu), "current": current, "maximum": maximum})
    return found


def check_gpu_mining_popular(ctx: RuleContext) -> list[Evidence]:
    found = []
    for index, gpu in enumerate(ctx.snapshot.gpus):
        ident = ctx.identification(index)
        if ident.status is IdentStatus.MATCH and ident.claimed and ident.claimed.mining_popular:
            found.append({"component": _gpu_label(gpu), "model": ident.claimed.model})
    return found


def check_gpu_unknown_model(ctx: RuleContext) -> list[Evidence]:
    found = []
    for index, gpu in enumerate(ctx.snapshot.gpus):
        if not is_discrete_gpu(gpu):
            continue  # встроенную графику не сверяем
        ident = ctx.identification(index)
        if ident.status is IdentStatus.UNKNOWN:
            found.append({"component": _gpu_label(gpu), "reasons": " ".join(ident.reasons)})
    return found


def check_gpu_ok(ctx: RuleContext) -> list[Evidence]:
    gpu = _main_gpu(ctx)
    vram = ctx.result(STRESS_VRAM)
    if gpu is None or vram is None or vram.status is not TestStatus.PASSED:
        return []
    problems = [
        check_gpu_fake,
        check_gpu_emergency_stop,
        check_gpu_overheat,
        check_gpu_thermal_throttle,
        check_gpu_fan_worn,
        check_gpu_fan_not_spinning,
        check_gpu_mining_bios,
    ]
    if any(rule(ctx) for rule in problems):
        return []
    temp = _gpu_load_metrics(ctx).get("max_temp_c")
    temp_text = f", под нагрузкой не выше {temp:.0f} °C" if temp is not None else ""
    return [{"component": _gpu_label(gpu), "model": gpu.name, "temp_text": temp_text}]


# ---------------------------------------------------------------------------
# Процессор
# ---------------------------------------------------------------------------


def check_cpu_instability(ctx: RuleContext) -> list[Evidence]:
    result = ctx.result(STRESS_CPU_LOAD)
    if result is None:
        return []
    mismatches = result.metrics.get("mismatches")
    if result.metrics.get("checksum_ok") is False or (mismatches or 0) > 0:
        return [{"component": "cpu", "mismatches": mismatches or 1}]
    return []


def check_cpu_clock_drop(ctx: RuleContext) -> list[Evidence]:
    result = ctx.result(STRESS_CPU_LOAD)
    if result is None or result.status is TestStatus.SKIPPED:
        return []
    drop = result.metrics.get("clock_drop_pct")
    if drop is not None and drop > ctx.thresholds.get("cpu.clock_drop_pct"):
        start = result.metrics.get("start_clock_mhz") or 0.0
        end = result.metrics.get("end_clock_mhz") or start * (1 - drop / 100)
        return [{"component": "cpu", "start": start, "end": end, "drop": drop}]
    return []


def check_cpu_ok(ctx: RuleContext) -> list[Evidence]:
    result = ctx.result(STRESS_CPU_LOAD)
    if result is None or result.status is not TestStatus.PASSED:
        return []
    if check_cpu_instability(ctx) or check_cpu_clock_drop(ctx):
        return []
    return [{"component": "cpu"}]


def _cpu_load_done(ctx: RuleContext) -> TestResult | None:
    result = ctx.result(STRESS_CPU_LOAD)
    if result is None or result.status in (TestStatus.SKIPPED, TestStatus.ERROR):
        return None
    return result


def check_cpu_temp_zone(ctx: RuleContext) -> list[Evidence]:
    """25.3: температура тепловой зоны ACPI (примерно), если датчик дал правдоподобные числа."""
    result = _cpu_load_done(ctx)
    zone = result.metrics.get("zone_temp_max_c") if result is not None else None
    return [{"component": "cpu", "zone": zone}] if zone is not None else []


def check_cpu_temp_unmeasured(ctx: RuleContext) -> list[Evidence]:
    """25.3: температуры нет, но частота под нагрузкой измерена — спокойная пометка."""
    result = _cpu_load_done(ctx)
    if result is None or result.metrics.get("zone_temp_max_c") is not None:
        return []
    if "start_clock_mhz" not in result.metrics:
        return []  # без частоты утверждать нечего — это попадёт в «что не проверено»
    return [{"component": "cpu"}]


# ---------------------------------------------------------------------------
# Оперативная память
# ---------------------------------------------------------------------------


def check_ram_errors(ctx: RuleContext) -> list[Evidence]:
    errors = ctx.metric(STRESS_RAM_QUICK, "errors") or 0
    return [{"component": "memory", "errors": errors}] if errors > 0 else []


def check_ram_less_than_claimed(ctx: RuleContext) -> list[Evidence]:
    memory = ctx.snapshot.memory
    if ctx.claimed_ram_gb is None or memory is None or memory.total_mb <= 0:
        return []
    actual = round(memory.total_mb / 1024, 1)
    if actual + 0.5 < ctx.claimed_ram_gb:
        return [{"component": "memory", "claimed": ctx.claimed_ram_gb, "actual": actual}]
    return []


def check_ram_mixed(ctx: RuleContext) -> list[Evidence]:
    memory = ctx.snapshot.memory
    if memory is None or not is_mixed(memory):
        return []
    details = "; ".join(
        f"{m.slot or 'слот'}: {m.manufacturer} {m.part_number} {m.speed_mhz or '?'} МГц"
        for m in memory.modules
    )
    return [{"component": "memory", "details": details}]


def check_ram_ok(ctx: RuleContext) -> list[Evidence]:
    result = ctx.result(STRESS_RAM_QUICK)
    if result is None or result.status is not TestStatus.PASSED:
        return []
    return [{"component": "memory", "tested_gb": (result.metrics.get("tested_mb") or 0) / 1024}]


# ---------------------------------------------------------------------------
# Накопители
# ---------------------------------------------------------------------------


def check_disk_smart_failed(ctx: RuleContext) -> list[Evidence]:
    return [
        {"component": _disk_label(d), "model": d.model}
        for d in ctx.snapshot.disks
        if d.smart is not None and d.smart.health_passed is False
    ]


def check_disk_sectors_critical(ctx: RuleContext) -> list[Evidence]:
    limit = ctx.thresholds.get("disk.sectors_critical")
    return [
        {"component": _disk_label(d), "model": d.model, "count": _sectors(d)}
        for d in ctx.snapshot.disks
        if _sectors(d) > limit
    ]


def check_disk_sectors_warning(ctx: RuleContext) -> list[Evidence]:
    low = ctx.thresholds.get("disk.sectors_warning")
    high = ctx.thresholds.get("disk.sectors_critical")
    return [
        {"component": _disk_label(d), "model": d.model, "count": _sectors(d)}
        for d in ctx.snapshot.disks
        if low <= _sectors(d) <= high
    ]


def _wear(disk: DiskInfo) -> float | None:
    if disk.smart is None or disk.media_type == "hdd":
        return None
    return disk.smart.wear_percent


def check_disk_ssd_wear_critical(ctx: RuleContext) -> list[Evidence]:
    limit = ctx.thresholds.get("ssd.wear_critical_pct")
    return [
        {"component": _disk_label(d), "model": d.model, "wear": wear}
        for d in ctx.snapshot.disks
        if (wear := _wear(d)) is not None and wear > limit
    ]


def check_disk_ssd_wear_warning(ctx: RuleContext) -> list[Evidence]:
    low = ctx.thresholds.get("ssd.wear_warning_pct")
    high = ctx.thresholds.get("ssd.wear_critical_pct")
    return [
        {"component": _disk_label(d), "model": d.model, "wear": wear}
        for d in ctx.snapshot.disks
        if (wear := _wear(d)) is not None and low < wear <= high
    ]


def check_disk_crc(ctx: RuleContext) -> list[Evidence]:
    limit = ctx.thresholds.get("disk.crc_warning")
    return [
        {"component": _disk_label(d), "model": d.model, "count": d.smart.crc_errors}
        for d in ctx.snapshot.disks
        if d.smart is not None and (d.smart.crc_errors or 0) >= limit
    ]


def check_disk_read_errors(ctx: RuleContext) -> list[Evidence]:
    count = ctx.metric(STRESS_DISK_READ, "read_errors") or 0
    return [{"component": "disk:system", "count": count}] if count > 0 else []


def check_disk_hdd_old(ctx: RuleContext) -> list[Evidence]:
    limit = ctx.thresholds.get("hdd.power_on_hours_info")
    found = []
    for disk in ctx.snapshot.disks:
        hours = disk.smart.power_on_hours if disk.smart else None
        if disk.media_type == "hdd" and hours is not None and hours > limit:
            found.append(
                {
                    "component": _disk_label(disk),
                    "model": disk.model,
                    "hours": hours,
                    "years": hours / 8766,
                }
            )
    return found


def check_disk_ok(ctx: RuleContext) -> list[Evidence]:
    bad_rules = [
        check_disk_smart_failed,
        check_disk_sectors_critical,
        check_disk_sectors_warning,
        check_disk_ssd_wear_critical,
        check_disk_ssd_wear_warning,
        check_disk_crc,
    ]
    bad = {e["component"] for rule in bad_rules for e in rule(ctx)}
    found = []
    for disk in ctx.snapshot.disks:
        if disk.smart is None or _disk_label(disk) in bad:
            continue
        wear = _wear(disk)
        wear_text = f", износ {wear:.0f}%" if wear is not None else ""
        found.append({"component": _disk_label(disk), "model": disk.model, "wear_text": wear_text})
    return found


# ---------------------------------------------------------------------------
# Система и ноутбук
# ---------------------------------------------------------------------------


def _event(ctx: RuleContext, key: str) -> tuple[int, str, int]:
    events = ctx.snapshot.events
    if events is None:
        return 0, "", 30
    last = events.last_seen.get(key, "")
    return events.counts.get(key, 0), last.replace("T", " ")[:16], events.days


def check_system_whea(ctx: RuleContext) -> list[Evidence]:
    count, last, days = _event(ctx, "whea")
    if count >= ctx.thresholds.get("events.whea_warning"):
        return [
            {"component": "system", "count": count, "last": last or "дата неизвестна", "days": days}
        ]
    return []


def check_system_disk_events(ctx: RuleContext) -> list[Evidence]:
    count, last, days = _event(ctx, "disk")
    if count > 0:
        return [
            {"component": "system", "count": count, "last": last or "дата неизвестна", "days": days}
        ]
    return []


def check_system_disk_events_removable(ctx: RuleContext) -> list[Evidence]:
    count, last, days = _event(ctx, "disk_removable")
    if count > 0:
        return [
            {"component": "system", "count": count, "last": last or "дата неизвестна", "days": days}
        ]
    return []


def check_system_crashes(ctx: RuleContext) -> list[Evidence]:
    bsod, _, days = _event(ctx, "bugcheck")
    power, _, _ = _event(ctx, "kernel_power_41")
    if bsod or power:
        return [{"component": "system", "bsod": bsod, "power": power, "days": days}]
    return []


def _battery(ctx: RuleContext) -> Evidence | None:
    battery = ctx.snapshot.battery
    if battery is None or battery.wear_percent is None:
        return None
    wear = battery.wear_percent
    cycles = battery.cycle_count if battery.cycle_count is not None else "неизвестно"
    # Оценка автономности: полная ёмкость (Вт·ч) / мощность при лёгкой работе (Вт).
    hours = battery.full_charge_capacity_mwh / 1000 / ctx.thresholds.get("battery.light_load_w")
    return {
        "component": "battery",
        "wear": wear,
        "left": 100 - wear,
        "cycles": cycles,
        "hours": hours,
    }


def check_battery_wear_bargain(ctx: RuleContext) -> list[Evidence]:
    info = _battery(ctx)
    if info and info["wear"] > ctx.thresholds.get("battery.wear_bargain_pct"):
        return [info]
    return []


def check_battery_wear_warning(ctx: RuleContext) -> list[Evidence]:
    info = _battery(ctx)
    low = ctx.thresholds.get("battery.wear_warning_pct")
    high = ctx.thresholds.get("battery.wear_bargain_pct")
    if info and low < info["wear"] <= high:
        return [info]
    return []


def check_battery_cycles_high(ctx: RuleContext) -> list[Evidence]:
    info = _battery(ctx)
    if info is None or not isinstance(info["cycles"], int):
        return []
    return [info] if info["cycles"] > ctx.thresholds.get("battery.cycles_info") else []


def check_battery_ok(ctx: RuleContext) -> list[Evidence]:
    info = _battery(ctx)
    if info and info["wear"] <= ctx.thresholds.get("battery.wear_warning_pct"):
        return [info]
    return []


# ---------------------------------------------------------------------------
# Реестр правил и применение
# ---------------------------------------------------------------------------

RULES: dict[str, Callable[[RuleContext], list[Evidence]]] = {
    "gpu.fake": check_gpu_fake,
    "gpu.vram_errors": check_gpu_vram_errors,
    "gpu.emergency_stop": check_gpu_emergency_stop,
    "gpu.overheat": check_gpu_overheat,
    "gpu.thermal_throttle": check_gpu_thermal_throttle,
    "gpu.fan_worn": check_gpu_fan_worn,
    "gpu.fan_not_spinning": check_gpu_fan_not_spinning,
    "gpu.mining_bios": check_gpu_mining_bios,
    "gpu.pcie_reduced": check_gpu_pcie_reduced,
    "gpu.mining_popular": check_gpu_mining_popular,
    "gpu.unknown_model": check_gpu_unknown_model,
    "gpu.ok": check_gpu_ok,
    "cpu.instability": check_cpu_instability,
    "cpu.clock_drop": check_cpu_clock_drop,
    "cpu.ok": check_cpu_ok,
    "cpu.temp_zone": check_cpu_temp_zone,
    "cpu.temp_unmeasured": check_cpu_temp_unmeasured,
    "ram.errors": check_ram_errors,
    "ram.less_than_claimed": check_ram_less_than_claimed,
    "ram.mixed": check_ram_mixed,
    "ram.ok": check_ram_ok,
    "disk.smart_failed": check_disk_smart_failed,
    "disk.sectors_critical": check_disk_sectors_critical,
    "disk.sectors_warning": check_disk_sectors_warning,
    "disk.ssd_wear_critical": check_disk_ssd_wear_critical,
    "disk.ssd_wear_warning": check_disk_ssd_wear_warning,
    "disk.crc": check_disk_crc,
    "disk.read_errors": check_disk_read_errors,
    "disk.hdd_old": check_disk_hdd_old,
    "disk.ok": check_disk_ok,
    "system.whea": check_system_whea,
    "system.disk_events": check_system_disk_events,
    "system.disk_events_removable": check_system_disk_events_removable,
    "system.crashes": check_system_crashes,
    "battery.wear_bargain": check_battery_wear_bargain,
    "battery.wear_warning": check_battery_wear_warning,
    "battery.cycles_high": check_battery_cycles_high,
    "battery.ok": check_battery_ok,
}


def make_finding(rule_id: str, evidence: Evidence) -> Finding:
    """Превращает сработавшее правило и его улики в находку с готовыми текстами."""
    texts, _ = load_rule_texts()
    text = texts[rule_id]
    values = {key: value for key, value in evidence.items() if key != "component"}
    shown = ", ".join(
        f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}"
        for k, v in values.items()
        if not isinstance(v, str) or len(v) < 40
    )
    return Finding(
        id=rule_id,
        severity=text.severity,
        component=evidence.get("component", text.component),
        title=text.title.format(**values),
        explanation=text.explanation.format(**values),
        advice=text.advice.format(**values),
        evidence=shown,
        weight=text.weight,
    )


def bargain_text(finding: Finding, evidence: Evidence) -> str | None:
    """Аргумент для торга по сработавшему правилу (если он предусмотрен)."""
    texts, _ = load_rule_texts()
    template = texts[finding.id].bargain
    if not template:
        return None
    values = {key: value for key, value in evidence.items() if key != "component"}
    return template.format(**values)


def evaluate_rules(ctx: RuleContext) -> list[tuple[Finding, Evidence]]:
    """Применяет все правила. Возвращает находки вместе с уликами."""
    found: list[tuple[Finding, Evidence]] = []
    for rule_id, check in RULES.items():
        for evidence in check(ctx):
            found.append((make_finding(rule_id, evidence), evidence))
    return found
