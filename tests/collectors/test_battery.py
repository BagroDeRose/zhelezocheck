"""Тесты сборщика сведений о батарее (powercfg /batteryreport)."""

from pathlib import Path
from typing import Any

from hwcheck.collectors import battery
from hwcheck.platform.runner import RunResult
from tests.helpers import fixture_text


def test_parse_laptop() -> None:
    info = battery.parse(fixture_text("battery", "laptop.xml"))
    assert info is not None
    assert info.design_capacity_mwh == 80000
    assert info.full_charge_capacity_mwh == 44000
    assert info.cycle_count == 640
    assert info.manufacturer == "Celxpert"
    assert info.chemistry == "LiP"
    assert info.wear_percent == 45.0


def test_parse_two_batteries_summed() -> None:
    info = battery.parse(fixture_text("battery", "thinkpad_two_batteries.xml"))
    assert info is not None
    assert info.design_capacity_mwh == 23480 + 23200
    assert info.full_charge_capacity_mwh == 18210 + 9870
    assert info.cycle_count == 310
    assert info.manufacturer == "SMP, SANYO"


def test_parse_no_batteries() -> None:
    assert battery.parse(fixture_text("battery", "no_batteries_section.xml")) is None
    assert battery.parse("") is None
    assert battery.parse("<broken") is None


class PowercfgFake:
    """Подмена запуска powercfg: пишет XML-фикстуру туда, куда просили (как настоящий)."""

    def __init__(self, fixture: str | None, returncode: int = 0, stderr: str = "") -> None:
        self.fixture = fixture
        self.returncode = returncode
        self.stderr = stderr
        self.cmd: list[str] = []

    def __call__(self, cmd: list[str], timeout: float = 60.0, **kwargs: Any) -> RunResult:
        self.cmd = cmd
        if self.fixture:
            Path(cmd[-1]).write_text(fixture_text("battery", self.fixture), encoding="utf-8")
        return RunResult(self.returncode, "", self.stderr, 0.5)


def test_collect_laptop_and_temp_cleaned() -> None:
    fake = PowercfgFake("laptop.xml")
    info = battery.collect(run_fn=fake)
    assert info is not None and info.cycle_count == 640
    assert fake.cmd[:4] == ["powercfg", "/batteryreport", "/xml", "/output"]
    assert not Path(fake.cmd[-1]).exists(), "временный отчёт должен удаляться"


def test_collect_desktop_without_battery() -> None:
    fake = PowercfgFake(
        None,
        returncode=1,
        stderr="Не удалось выполнить операцию. Произошла непредвиденная ошибка (0x10d2)",
    )
    assert battery.collect(run_fn=fake) is None


def test_runtime_estimates() -> None:
    """15.12: время работы от полной зарядки — сейчас и у новой батареи."""
    info = battery.parse(fixture_text("battery", "laptop.xml"))
    assert info is not None
    assert info.runtime_minutes == 192
    assert info.design_runtime_minutes == 349


def test_iso_duration() -> None:
    assert battery.iso_minutes("PT3H12M") == 192
    assert battery.iso_minutes("PT45M30S") == 45
    assert battery.iso_minutes("PT0S") is None
    assert battery.iso_minutes("") is None
