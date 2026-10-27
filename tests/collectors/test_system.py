"""Тесты сборщика сведений о системе и BIOS."""

from hwcheck.collectors import system
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_parse_win10_russian() -> None:
    info = system.parse(fixture_json("powershell", "system_win10.json"))
    assert info.os_name == "Майкрософт Windows 10 Pro"
    assert info.os_build == "19045"
    assert info.architecture == "64-разрядная"
    assert info.bios_version == "3202"
    assert info.bios_date is not None and info.bios_date.startswith("2021-07-13")
    assert info.install_date is not None and info.install_date.startswith("2026")
    assert info.is_laptop is False


def test_parse_win11_laptop_iso_dates() -> None:
    info = system.parse(fixture_json("powershell", "system_win11_laptop.json"))
    assert info.os_name == "Microsoft Windows 11 Home"
    assert info.manufacturer == "LENOVO"
    assert info.is_laptop is True
    assert info.bios_date == "2022-05-10T03:00:00+03:00"


def test_parse_win11_desktop() -> None:
    info = system.parse(fixture_json("powershell", "system_win11_desktop.json"))
    assert info.os_build == "26100"
    assert info.is_laptop is False


def test_parse_laptop_by_chassis_only() -> None:
    data = fixture_json("powershell", "system_win10.json")
    data["CS"]["PCSystemType"] = 0
    data["ChassisTypes"] = [9]  # Laptop
    assert system.parse(data).is_laptop is True


def test_parse_empty() -> None:
    info = system.parse(None)
    assert info.os_name == ""


def test_collect_uses_powershell() -> None:
    fake = FakeRun(fixture_text("powershell", "system_win10.json"))
    info = system.collect(run_fn=fake)
    assert info.os_build == "19045"
    assert "Win32_OperatingSystem" in fake.commands[0][-1]
