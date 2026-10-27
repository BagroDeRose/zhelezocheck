"""Проверки служебных скриптов: PowerShell 5.1 читает .ps1 без BOM как ANSI — нужен UTF-8 с BOM."""

from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).parent.parent / "scripts").glob("*.ps1"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_ps1_has_utf8_bom(script: Path) -> None:
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_ps1_never_installs_or_changes_system(script: Path) -> None:
    text = script.read_text(encoding="utf-8-sig").lower()
    for forbidden in (
        "new-service",
        "sc.exe create",
        "reg add",
        "set-itemproperty",
        "bcdedit",
        "pnputil",
        "set-mppreference",
        "powercfg /setactive",
        "start-process -verb runas",
    ):
        assert forbidden not in text, forbidden


def test_setup_vendor_pins_official_checksum() -> None:
    text = (Path(__file__).parent.parent / "scripts" / "setup_vendor.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "09e67704210762ae8d8ad70fe6d71275eefbe815cc2c0658cd5afc8e231d0df6" in text
    checksums = (Path(__file__).parent.parent / "vendor" / "CHECKSUMS.txt").read_text(
        encoding="utf-8-sig"
    )
    official = "09e67704210762ae8d8ad70fe6d71275eefbe815cc2c0658cd5afc8e231d0df6"
    assert f"{official}  memtest_vulkan/memtest_vulkan.exe" in checksums
