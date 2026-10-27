"""Тесты разбора XML nvidia-smi (разные поколения драйверов) и объединения с данными WMI."""

from hwcheck.collectors import gpu_nvidia
from hwcheck.models import GpuInfo
from tests.helpers import FakeRun, fixture_text


def _parse(name: str) -> list[GpuInfo]:
    return gpu_nvidia.parse(fixture_text("nvidia_smi", name))


def test_real_turing_new_tags() -> None:
    (gpu,) = _parse("gtx1660_turing_drv617_real.xml")
    assert gpu.name == "NVIDIA GeForce GTX 1660"
    assert (gpu.pci_vendor_id, gpu.pci_device_id, gpu.subsystem_id) == ("10de", "2184", "136610de")
    assert gpu.vbios_version == "90.16.34.00.63"
    assert gpu.driver_version == "617.14"
    assert gpu.vram_mb == 6144
    assert gpu.default_power_limit_w == 120.0
    assert gpu.enforced_power_limit_w == 120.0
    assert gpu.max_power_limit_w == 120.0
    assert gpu.max_clocks == {"graphics": 2115, "sm": 2115, "memory": 4001, "video": 1950}
    assert (gpu.pcie_gen_current, gpu.pcie_gen_max) == (3, 3)
    assert (gpu.pcie_width_current, gpu.pcie_width_max) == (16, 16)
    assert gpu.fan_speed_percent == 0.0
    assert gpu.throttle_reasons == ["gpu_idle"]
    assert gpu.source == "nvidia-smi"


def test_pascal_old_tags() -> None:
    (gpu,) = _parse("gtx1060_pascal_drv472_old_tags.xml")
    assert gpu.pci_device_id == "1c03"
    assert gpu.enforced_power_limit_w == 120.0
    assert gpu.max_power_limit_w == 140.0
    assert gpu.throttle_reasons == ["gpu_idle"]
    assert gpu.fan_speed_percent == 34.0
    assert gpu.driver_version == "472.12"


def test_ampere_active_reasons_and_reduced_width() -> None:
    (gpu,) = _parse("rtx3060_ampere_drv560.xml")
    assert set(gpu.throttle_reasons) == {"sw_power_cap", "sw_thermal_slowdown"}
    assert gpu.pcie_width_current == 8 and gpu.pcie_width_max == 16
    assert gpu.max_power_limit_w == 212.0


def test_two_gpus_and_na_fan() -> None:
    first, second = _parse("two_gpus_ada_ampere_drv566.xml")
    assert first.name == "NVIDIA GeForce RTX 4070"
    assert first.fan_speed_percent is None
    assert second.pci_device_id == "2484"
    assert second.pcie_width_current == 1
    assert second.default_power_limit_w == 130.0


def test_garbage_xml() -> None:
    assert gpu_nvidia.parse("это не xml") == []
    assert gpu_nvidia.parse("") == []


def test_collect_not_found_is_not_error() -> None:
    fake = FakeRun("", returncode=None, not_found=True, stderr="not found")
    assert gpu_nvidia.collect(run_fn=fake) == []


def test_collect_timeout_is_not_error() -> None:
    fake = FakeRun("", returncode=None, timed_out=True)
    assert gpu_nvidia.collect(run_fn=fake) == []


def test_collect_ok() -> None:
    fake = FakeRun(fixture_text("nvidia_smi", "rtx3060_ampere_drv560.xml"))
    (gpu,) = gpu_nvidia.collect(run_fn=fake)
    assert gpu.vram_mb == 12288
    assert fake.commands[0][1:] == ["-q", "-x"]


def test_merge_fills_wmi_entry() -> None:
    wmi = [
        GpuInfo(vendor="Intel", name="Intel UHD 770", pci_vendor_id="8086", pci_device_id="4680"),
        GpuInfo(
            vendor="NVIDIA",
            name="NVIDIA GeForce RTX 3070",
            pci_vendor_id="10de",
            pci_device_id="2484",
            subsystem_id="146b10de",
            vram_mb=8192,
            driver_version="566.36",
            pnp_device_id=r"PCI\VEN_10DE&DEV_2484",
            source="wmi",
        ),
    ]
    merged = gpu_nvidia.merge(wmi, _parse("two_gpus_ada_ampere_drv566.xml"))
    assert len(merged) == 3  # RTX 4070 не было в WMI — добавлена в конец
    intel, rtx3070, rtx4070 = merged
    assert intel.vbios_version == ""
    assert rtx3070.vbios_version == "94.04.3A.00.7C"
    assert rtx3070.pnp_device_id == r"PCI\VEN_10DE&DEV_2484"
    assert rtx3070.default_power_limit_w == 130.0
    assert rtx3070.source == "wmi+nvidia-smi"
    assert rtx4070.name == "NVIDIA GeForce RTX 4070"
