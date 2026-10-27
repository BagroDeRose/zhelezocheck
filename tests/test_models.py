"""Тесты моделей: каждая модель переживает путь «объект → JSON → объект» без потерь."""

import json

import pytest

from hwcheck.models import (
    BatteryInfo,
    BoardInfo,
    CheckSession,
    CpuInfo,
    Decision,
    DiskInfo,
    EventSummary,
    Finding,
    GpuInfo,
    HardwareSnapshot,
    JsonModel,
    MemoryInfo,
    MemoryModule,
    SensorSample,
    Severity,
    SmartData,
    SystemInfo,
    TestResult,
    TestStatus,
    Verdict,
)


def _gpu() -> GpuInfo:
    return GpuInfo(
        vendor="NVIDIA",
        name="NVIDIA GeForce RTX 3060",
        pci_vendor_id="10de",
        pci_device_id="2503",
        subsystem_id="397d1462",
        vram_mb=12288,
        vbios_version="94.06.2F.00.9A",
        driver_version="560.94",
        default_power_limit_w=170.0,
        max_clocks={"graphics": 2100, "memory": 7501},
        throttle_reasons=["sw_power_cap"],
    )


def _snapshot() -> HardwareSnapshot:
    return HardwareSnapshot(
        collected_at="2026-10-05T12:00:00",
        is_admin=True,
        system=SystemInfo(os_name="Windows 11 Pro", os_build="22631", is_laptop=False),
        cpu=CpuInfo(name="AMD Ryzen 5 5600", cores=6, threads=12, max_clock_mhz=3500),
        memory=MemoryInfo(
            total_mb=32768,
            modules=[MemoryModule(capacity_mb=16384, speed_mhz=3200, slot="DIMM_A2")] * 2,
        ),
        board=BoardInfo(manufacturer="MSI", product="B550-A PRO"),
        gpus=[_gpu()],
        disks=[
            DiskInfo(
                model="Samsung SSD 980",
                size_gb=1000.2,
                media_type="ssd",
                bus_type="nvme",
                smart=SmartData(power_on_hours=1200, wear_percent=3.0, health_passed=True),
            )
        ],
        battery=None,
        events=EventSummary(counts={"whea": 0}, partial=False),
        errors={"battery": "нет батареи"},
    )


MODELS: list[JsonModel] = [
    SystemInfo(os_name="Windows 10 Pro", bios_date="2021-03-01"),
    CpuInfo(name="Intel Core i5-12400F", cores=6, threads=12),
    MemoryModule(capacity_mb=8192, part_number="KF3200C16D4/8GX"),
    MemoryInfo(total_mb=16384, modules=[MemoryModule(capacity_mb=8192)]),
    BoardInfo(manufacturer="ASUS", product="PRIME B660M-A"),
    _gpu(),
    SmartData(reallocated_sectors=12, crc_errors=0),
    DiskInfo(model="WDC WD10EZEX", media_type="hdd", smart=SmartData(power_on_hours=41000)),
    BatteryInfo(design_capacity_mwh=50000, full_charge_capacity_mwh=35000, cycle_count=420),
    EventSummary(counts={"whea": 2}, last_seen={"whea": "2026-09-30"}, partial=True),
    _snapshot(),
    SensorSample(t=1.5, component="gpu0", values={"temp_c": 71.0, "fan_pct": None}),
    TestResult(
        name="vram",
        status=TestStatus.FAILED,
        component="gpu0",
        metrics={"errors": 3, "speed_gbps": 250.5, "note": "ok"},
        samples=[SensorSample(t=0.0, component="gpu0", values={"temp_c": 40.0})],
        notes=["ошибки видеопамяти"],
    ),
    Finding(id="gpu.vram_errors", severity=Severity.CRITICAL, component="gpu0", weight=10.0),
    Verdict(
        decision=Decision.NEGOTIATE,
        findings=[Finding(id="x", severity=Severity.WARNING)],
        not_checked=["Температура процессора"],
        score=3.5,
        bargaining_points=["износ батареи 35%"],
    ),
    CheckSession(
        id="0b8c",
        mode="full",
        snapshot=_snapshot(),
        results=[TestResult(name="cpu_load", status=TestStatus.WARNING)],
        verdict=Verdict(decision=Decision.WALK_AWAY),
    ),
]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: type(m).__name__)
def test_roundtrip_dict_and_json(model: JsonModel) -> None:
    cls = type(model)
    assert cls.from_dict(model.to_dict()) == model
    assert cls.from_json(model.to_json()) == model


@pytest.mark.parametrize("model", MODELS, ids=lambda m: type(m).__name__)
def test_to_dict_is_plain_json(model: JsonModel) -> None:
    # Строка JSON должна строиться стандартным json без особых кодировщиков.
    text = json.dumps(model.to_dict(), ensure_ascii=False)
    assert isinstance(json.loads(text), dict)


def test_enums_serialized_as_strings() -> None:
    data = TestResult(name="cpu", status=TestStatus.PASSED).to_dict()
    assert data["status"] == "passed"
    restored = TestResult.from_dict(data)
    assert restored.status is TestStatus.PASSED


def test_unknown_keys_ignored_and_missing_defaulted() -> None:
    cpu = CpuInfo.from_dict({"name": "X", "future_field": 1})
    assert cpu.name == "X"
    assert cpu.cores == 0


def test_int_promoted_to_float() -> None:
    disk = DiskInfo.from_dict({"size_gb": 500})
    assert isinstance(disk.size_gb, float)


def test_battery_wear_percent() -> None:
    assert (
        BatteryInfo(design_capacity_mwh=50000, full_charge_capacity_mwh=35000).wear_percent == 30.0
    )
    assert BatteryInfo(design_capacity_mwh=0).wear_percent is None
    assert BatteryInfo(design_capacity_mwh=100, full_charge_capacity_mwh=120).wear_percent == 0.0


def test_from_dict_rejects_non_dict() -> None:
    with pytest.raises(TypeError):
        CpuInfo.from_dict([1, 2])  # type: ignore[arg-type]  # проверяем именно неверный ввод


# ---------------------------------------------------------------- 15.7 встроенная графика


def test_integrated_amd_graphics_is_not_discrete() -> None:
    from hwcheck.models import GpuInfo, is_discrete_gpu

    integrated = [
        GpuInfo(vendor="AMD", name="AMD Radeon(TM) Graphics", vram_mb=512),
        GpuInfo(vendor="AMD", name="AMD Radeon(TM) Vega 8 Graphics"),
        GpuInfo(vendor="AMD", name="AMD Radeon 780M Graphics"),
        GpuInfo(vendor="Intel", name="Intel(R) UHD Graphics 620"),
    ]
    discrete = [
        GpuInfo(vendor="AMD", name="AMD Radeon RX 6600"),
        GpuInfo(vendor="AMD", name="Radeon RX 7600M XT Graphics"),
        GpuInfo(vendor="NVIDIA", name="NVIDIA GeForce RTX 3060"),
    ]
    assert not any(is_discrete_gpu(g) for g in integrated)
    assert all(is_discrete_gpu(g) for g in discrete)


def test_vram_text() -> None:
    from hwcheck.models import GpuInfo, vram_text

    assert vram_text(GpuInfo(vendor="NVIDIA", name="RTX", vram_mb=12288)) == "12 ГБ"
    assert vram_text(GpuInfo(vendor="AMD", name="AMD Radeon(TM) Graphics", vram_mb=512)) == (
        "общая с ОЗУ"
    )
    assert vram_text(GpuInfo(vendor="AMD", name="RX 550", vram_mb=512)) == "512 МБ"
    assert vram_text(GpuInfo(vendor="AMD", name="RX 550")) == ""
