"""Тесты блока «Ноутбук» для вердикта и отчёта (задача 15.12)."""

from hwcheck.laptop.details import laptop_details
from hwcheck.laptop.texts import laptop_finding
from hwcheck.models import BatteryInfo, CheckSession, HardwareSnapshot, SystemInfo, Verdict


def _laptop_session(with_manual: bool) -> CheckSession:
    snapshot = HardwareSnapshot(
        system=SystemInfo(manufacturer="HONOR", model="BMH-WDX9", is_laptop=True),
        battery=BatteryInfo(
            design_capacity_mwh=56000,
            full_charge_capacity_mwh=47000,
            cycle_count=202,
            runtime_minutes=192,
            design_runtime_minutes=349,
        ),
    )
    findings = []
    if with_manual:
        findings = [laptop_finding("screen_ok")[0], laptop_finding("keyboard_missing", keys="W")[0]]
    return CheckSession(snapshot=snapshot, verdict=Verdict(findings=findings))


def test_details_for_laptop() -> None:
    rows = dict(laptop_details(_laptop_session(with_manual=True)))
    assert "износ 16%" in rows["Батарея"] and "циклов зарядки: 202" in rows["Батарея"]
    assert "47 000 из 56 000 мВт·ч" in rows["Батарея"]
    assert (
        rows["Время работы"] == "около 3 ч 12 мин от полной зарядки (у новой батареи — 5 ч 49 мин)"
    )
    assert rows["Экран"] == laptop_finding("screen_ok")[0].title
    assert rows["Клавиатура"] == laptop_finding("keyboard_missing", keys="W")[0].title


def test_details_without_manual_checks() -> None:
    rows = dict(laptop_details(_laptop_session(with_manual=False)))
    assert rows["Экран"] == "не проверялся"
    assert rows["Клавиатура"] == "не проверялась"


def test_no_details_for_desktop() -> None:
    assert laptop_details(CheckSession(snapshot=HardwareSnapshot())) == []
