"""Тесты общего сборщика видеокарт (WMI + реестр, только чтение)."""

import pytest

from hwcheck.collectors import gpu_generic
from hwcheck.models import GpuInfo
from tests.helpers import FakeRun, fixture_json, fixture_text


def _parse(name: str) -> list[GpuInfo]:
    return gpu_generic.parse(fixture_json("powershell", name))


def test_nvidia_vram_over_4gb_from_registry() -> None:
    (gpu,) = _parse("gpu_nvidia.json")
    assert gpu.vendor == "NVIDIA"
    assert (gpu.pci_vendor_id, gpu.pci_device_id, gpu.subsystem_id) == ("10de", "2184", "136610de")
    assert gpu.vram_mb == 6144  # а не 4095 из AdapterRAM
    assert gpu.driver_version == "617.14"
    assert gpu.source == "wmi"


def test_amd_single_object_and_registry_match_with_rev() -> None:
    (gpu,) = _parse("gpu_amd.json")
    assert gpu.vendor == "AMD"
    assert gpu.pci_device_id == "73df"
    assert gpu.vram_mb == 12272
    assert gpu.driver_version == "31.0.24027.1012"


def test_intel_igpu_uses_adapter_ram() -> None:
    (gpu,) = _parse("gpu_intel_igpu.json")
    assert gpu.vendor == "Intel"
    assert gpu.vram_mb == 1024


def test_two_gpus_and_virtual_adapter_skipped() -> None:
    gpus = _parse("gpu_two.json")
    assert [g.vendor for g in gpus] == ["Intel", "NVIDIA"]
    assert gpus[1].vram_mb == 10240
    assert gpus[1].name == "NVIDIA GeForce RTX 3080"


def test_basic_display_adapter_kept_with_real_ids() -> None:
    # Без драйвера Windows показывает «Базовый видеоадаптер», но код устройства настоящий.
    (gpu,) = _parse("gpu_basic_display.json")
    assert gpu.pci_device_id == "1c82"
    assert gpu.vendor == "NVIDIA"
    assert gpu.vram_mb is None


@pytest.mark.parametrize(
    ("pnp", "expected"),
    [
        (r"PCI\VEN_10DE&DEV_2503&SUBSYS_397D1462&REV_A1\4&1", ("10de", "2503", "397d1462")),
        (r"PCI\VEN_8086&DEV_3E92&REV_02\3&1", ("8086", "3e92", "")),
        (r"ROOT\DISPLAY\0000", None),
    ],
)
def test_parse_pnp_id(pnp: str, expected: tuple[str, str, str] | None) -> None:
    assert gpu_generic.parse_pnp_id(pnp) == expected


def test_empty() -> None:
    assert gpu_generic.parse(None) == []


def test_collect_reads_registry_only() -> None:
    fake = FakeRun(fixture_text("powershell", "gpu_two.json"))
    gpus = gpu_generic.collect(run_fn=fake)
    assert len(gpus) == 2
    script = fake.commands[0][-1]
    assert "Get-ItemProperty" in script
    for forbidden in ("Set-ItemProperty", "New-ItemProperty", "Remove-Item", "reg add"):
        assert forbidden not in script
