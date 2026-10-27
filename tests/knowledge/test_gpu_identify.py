"""Тесты определения реальной модели видеокарты и поиска подделок."""

import pytest

from hwcheck.backends.fake import load_scenario
from hwcheck.knowledge import gpu_db
from hwcheck.knowledge.gpu_db import IdentStatus
from hwcheck.models import GpuInfo


def _gpu(name: str, vendor_id: str, device_id: str, vram_mb: int | None = None) -> GpuInfo:
    vendor = {"10de": "NVIDIA", "1002": "AMD", "8086": "Intel"}[vendor_id]
    return GpuInfo(
        vendor=vendor, name=name, pci_vendor_id=vendor_id, pci_device_id=device_id, vram_mb=vram_mb
    )


def test_honest_card_matches() -> None:
    gpu = load_scenario("healthy_gaming_pc").snapshot.gpus[0]
    ident = gpu_db.identify(gpu)
    assert ident.status is IdentStatus.MATCH
    assert ident.claimed is not None and ident.claimed.model == "GeForce RTX 3060"
    assert [c.model for c in ident.real] == ["GeForce RTX 3060"]
    assert ident.vram_ok is True
    assert ident.real_chip.startswith("GA106")


def test_fake_relabel_scenario_flagged() -> None:
    gpu = load_scenario("fake_gpu_relabel").snapshot.gpus[0]
    ident = gpu_db.identify(gpu)
    assert ident.status is IdentStatus.FAKE
    assert ident.claimed is not None and ident.claimed.model == "GeForce GTX 1060 6GB"
    assert [c.model for c in ident.real] == ["GeForce GT 730"]
    assert any("GT 730" in reason for reason in ident.reasons)


def test_unknown_id_is_not_alarm() -> None:
    ident = gpu_db.identify(_gpu("NVIDIA GeForce RTX 9999", "10de", "ffff", 8192))
    assert ident.status is IdentStatus.UNKNOWN
    assert ident.reasons  # объяснение, почему не определили


def test_laptop_gpu_not_in_db_is_unknown() -> None:
    ident = gpu_db.identify(_gpu("NVIDIA GeForce RTX 3060 Laptop GPU", "10de", "2520", 6144))
    assert ident.status is IdentStatus.UNKNOWN


def test_intel_igpu_unknown_without_alarm() -> None:
    ident = gpu_db.identify(_gpu("Intel(R) UHD Graphics 630", "8086", "3e92", 1024))
    assert ident.status is IdentStatus.UNKNOWN


def test_amd_shared_id_family_match() -> None:
    ident = gpu_db.identify(_gpu("Radeon RX 580 Series", "1002", "67df", 8192))
    assert ident.status is IdentStatus.MATCH
    assert ident.claimed is not None and ident.claimed.model == "Radeon RX 580"
    assert "Radeon RX 570" in [c.model for c in ident.real]


def test_rx580_2048sp_sold_as_rx580() -> None:
    # Китайская урезанная RX 580 2048SP с именем обычной RX 580.
    ident = gpu_db.identify(_gpu("AMD Radeon RX 580", "1002", "6fdf", 8192))
    assert ident.status is IdentStatus.FAKE
    assert [c.model for c in ident.real] == ["Radeon RX 580 2048SP"]


def test_ti_name_on_non_ti_chip() -> None:
    ident = gpu_db.identify(_gpu("NVIDIA GeForce RTX 3060 Ti", "10de", "2503", 12288))
    assert ident.status is IdentStatus.FAKE


def test_vram_mismatch_flagged() -> None:
    ident = gpu_db.identify(_gpu("NVIDIA GeForce RTX 3060", "10de", "2503", 3072))
    assert ident.status is IdentStatus.FAKE
    assert ident.vram_ok is False
    assert any("памят" in reason for reason in ident.reasons)


def test_vram_variants_accepted() -> None:
    for vram in (8192, 12288, 12282):
        ident = gpu_db.identify(_gpu("NVIDIA GeForce RTX 3060", "10de", "2503", vram))
        assert ident.vram_ok is True, vram


def test_basic_display_adapter_reveals_real_model() -> None:
    ident = gpu_db.identify(_gpu("Базовый видеоадаптер (Майкрософт)", "10de", "1c82"))
    assert ident.status is IdentStatus.UNKNOWN
    assert [c.model for c in ident.real] == ["GeForce GTX 1050 Ti"]
    assert ident.vram_ok is None


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("NVIDIA GeForce RTX 3060", "GeForce RTX 3060"),
        ("NVIDIA GeForce RTX 3060 Ti", "GeForce RTX 3060 Ti"),
        ("NVIDIA GeForce GTX 1660 SUPER", "GeForce GTX 1660 SUPER"),
        ("AMD Radeon(TM) RX 6700 XT", "Radeon RX 6700 XT"),
        ("AMD Radeon RX 7900 XTX", "Radeon RX 7900 XTX"),
        ("NVIDIA GeForce RTX 4090 Laptop GPU", None),
        ("Microsoft Basic Display Adapter", None),
    ],
)
def test_find_by_name(name: str, model: str | None) -> None:
    card = gpu_db.find_by_name(name)
    assert (card.model if card else None) == model


def test_reference_lookup() -> None:
    card = gpu_db.find_by_name("NVIDIA GeForce RTX 3070")
    assert card is not None and card.tdp_w == 220 and card.mining_popular
