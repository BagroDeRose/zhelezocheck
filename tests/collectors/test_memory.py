"""Тесты сборщика сведений об оперативной памяти."""

from hwcheck.collectors import memory
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_two_modules() -> None:
    info = memory.parse(fixture_json("powershell", "memory_two_modules.json"))
    assert len(info.modules) == 2
    assert info.total_mb == 32768
    assert info.slots_total == 4
    first = info.modules[0]
    assert first.capacity_mb == 16384
    assert first.speed_mhz == 3200
    assert first.part_number == "KF3200C16D4/16GX"
    assert first.slot == "DIMM_A2"


def test_one_module_single_object() -> None:
    info = memory.parse(fixture_json("powershell", "memory_one_module.json"))
    assert len(info.modules) == 1
    assert info.total_mb == 8192
    assert info.modules[0].configured_speed_mhz == 2400
    assert info.slots_total == 2


def test_mixed_modules() -> None:
    info = memory.parse(fixture_json("powershell", "memory_mixed.json"))
    assert len(info.modules) == 3
    assert info.total_mb == 8192 + 8192 + 4096
    assert {m.speed_mhz for m in info.modules} == {2400, 2666, 3200}
    assert memory.is_mixed(info)


def test_not_mixed() -> None:
    assert not memory.is_mixed(memory.parse(fixture_json("powershell", "memory_two_modules.json")))


def test_available_from_psutil() -> None:
    info = memory.parse(None, psutil_total_mb=16000, psutil_available_mb=9000)
    assert info.modules == []
    assert info.total_mb == 16000
    assert info.available_mb == 9000


def test_collect() -> None:
    fake = FakeRun(fixture_text("powershell", "memory_two_modules.json"))
    info = memory.collect(run_fn=fake)
    assert info.total_mb == 32768
    assert info.available_mb is not None
