"""Тесты поиска чипа по кодам PCI в сохранённом справочнике."""

import pytest

from hwcheck.knowledge import pci_ids
from scripts.update_pci_ids import filter_pci_ids


def test_rtx_3090() -> None:
    chip = pci_ids.lookup("10de", "2204")
    assert chip is not None
    assert chip.vendor == "NVIDIA Corporation"
    assert chip.chip == "GA102"
    assert chip.marketing == "GeForce RTX 3090"


@pytest.mark.parametrize(
    ("vendor", "device", "chip", "marketing_part"),
    [
        ("10de", "1287", "GK208B", "GT 730"),
        ("10DE", "1C03", "GP106", "GTX 1060 6GB"),
        ("1002", "73df", "Navi 22", "RX 6700"),
        ("10de", "2184", "TU116", "GTX 1660"),
    ],
)
def test_known_ids(vendor: str, device: str, chip: str, marketing_part: str) -> None:
    found = pci_ids.lookup(vendor, device)
    assert found is not None
    assert found.chip == chip
    assert marketing_part in found.marketing


def test_unknown() -> None:
    assert pci_ids.lookup("10de", "ffff") is None
    assert pci_ids.lookup("1234", "5678") is None
    assert pci_ids.lookup("", "") is None


def test_vendor_scoping() -> None:
    # 2484 есть и у NVIDIA (RTX 3070), и у Intel (USB-контроллер) — нельзя перепутать.
    nvidia = pci_ids.lookup("10de", "2484")
    intel = pci_ids.lookup("8086", "2484")
    assert nvidia is not None and "RTX 3070" in nvidia.marketing
    assert intel is not None and "USB" in intel.name


def test_name_without_brackets() -> None:
    chip = pci_ids.parse_device_name("AD102GL")
    assert chip == ("AD102GL", "")


def test_filter_keeps_only_vendors_and_drops_subsystems() -> None:
    raw = (
        "# comment\n"
        "1234  Other\n\t0001  Foo\n"
        "10de  NVIDIA Corporation\n\t2204  GA102 [GeForce RTX 3090]\n\t\t1043 87b3  Sub\n"
        "C 00  Unclassified\n\t00  Non-VGA\n"
    )
    assert filter_pci_ids(raw) == "10de  NVIDIA Corporation\n\t2204  GA102 [GeForce RTX 3090]\n"


def test_data_file_has_license_header() -> None:
    head = pci_ids.data_file().read_text(encoding="utf-8")[:800]
    assert "BSD" in head and "pci-ids.ucw.cz" in head
