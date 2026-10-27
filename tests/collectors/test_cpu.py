"""Тесты сборщика сведений о процессоре."""

from hwcheck.collectors import cpu
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_parse_intel() -> None:
    info = cpu.parse(fixture_json("powershell", "cpu_intel.json"))
    assert info.name == "Intel(R) Core(TM) i5-9400F CPU @ 2.90GHz"
    assert info.manufacturer == "GenuineIntel"
    assert (info.cores, info.threads) == (6, 6)
    assert info.max_clock_mhz == 2904
    assert info.socket == "LGA1151"


def test_parse_amd_list_and_trailing_spaces() -> None:
    info = cpu.parse(fixture_json("powershell", "cpu_amd.json"))
    assert info.name == "AMD Ryzen 7 5800X3D 8-Core Processor"
    assert (info.cores, info.threads) == (8, 16)


def test_parse_empty_uses_fallback() -> None:
    info = cpu.parse(None, fallback_threads=12, fallback_cores=6, fallback_max_mhz=3600.0)
    assert (info.cores, info.threads, info.max_clock_mhz) == (6, 12, 3600)


def test_collect_falls_back_to_psutil_on_error() -> None:
    fake = FakeRun("", returncode=1, stderr="Get-CimInstance : Отказано в доступе.")
    info = cpu.collect(run_fn=fake)
    assert info.threads >= 1


def test_collect_ok() -> None:
    fake = FakeRun(fixture_text("powershell", "cpu_amd.json"))
    assert cpu.collect(run_fn=fake).cores == 8
