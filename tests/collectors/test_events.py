"""Тесты сводки журнала событий Windows."""

from hwcheck.collectors import events
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_with_events() -> None:
    summary = events.parse(fixture_json("powershell", "events_with.json"))
    assert summary.counts == {"whea": 4, "kernel_power_41": 2, "bugcheck": 3, "disk": 17}
    assert summary.last_seen["bugcheck"] == "2026-10-02T22:15:31"
    assert summary.partial is False
    assert summary.days == 30


def test_no_events() -> None:
    summary = events.parse(fixture_json("powershell", "events_none.json"))
    assert summary.counts == {"whea": 0, "kernel_power_41": 0, "bugcheck": 0, "disk": 0}
    assert summary.last_seen == {}
    assert not summary.partial


def test_partial_without_admin() -> None:
    summary = events.parse(fixture_json("powershell", "events_partial_noadmin.json"))
    assert summary.partial is True
    assert "администратор" in summary.note
    assert summary.counts == {"kernel_power_41": 1, "bugcheck": 0}
    assert "whea" not in summary.counts  # неизвестно, а не «ноль»


def test_collect_powershell_failure_gives_partial() -> None:
    fake = FakeRun("", returncode=1, stderr="Отказано в доступе")
    summary = events.collect(run_fn=fake)
    assert summary.partial and summary.counts == {}


def test_collect_ok_and_script_is_read_only() -> None:
    fake = FakeRun(fixture_text("powershell", "events_with.json"))
    assert events.collect(run_fn=fake).counts["disk"] == 17
    script = fake.commands[0][-1]
    assert "Get-WinEvent" in script and "AddDays(-30)" in script
    for forbidden in ("Clear-EventLog", "wevtutil", "Remove-", "Limit-EventLog"):
        assert forbidden not in script


def test_removable_disk_errors_counted_separately() -> None:
    """15.8: ошибки флешек (USB/SD или уже отключённых дисков) не смешиваются с внутренними."""
    summary = events.parse(fixture_json("powershell", "events_disk_usb.json"))
    assert summary.counts["disk"] == 1  # только NVMe — внутренний диск
    assert summary.counts["disk_removable"] == 8


def test_script_maps_disk_events_to_bus() -> None:
    script = events.build_script()
    assert "Harddisk" in script and "Get-PhysicalDisk" in script and "BusType" in script
