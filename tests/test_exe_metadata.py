"""Свойства exe (SPEC 1.5, 34.7): CompanyName и LegalCopyright — только псевдоним BagroDeRose."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_exe_metadata() -> ModuleType:
    """packaging/ — не пакет Python (его читает PyInstaller), поэтому загружаем файл по пути."""
    spec = importlib.util.spec_from_file_location(
        "exe_metadata", ROOT / "packaging" / "exe_metadata.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exe_metadata = _load_exe_metadata()


def test_strings_use_only_pseudonym() -> None:
    strings = exe_metadata.version_strings("1.5.0-rc1")
    assert strings["CompanyName"] == "BagroDeRose"
    assert strings["LegalCopyright"] == "© 2026 BagroDeRose. MIT License."
    assert strings["ProductName"] == "ЖелезоЧек"
    assert strings["ProductVersion"] == "1.5.0-rc1"
    text = " ".join(strings.values())
    for forbidden in ("ФИО", "ИНН", "паспорт"):
        assert forbidden not in text


@pytest.mark.parametrize(
    ("version", "numbers"),
    [("1.5.0", (1, 5, 0, 0)), ("1.5.0-rc1", (1, 5, 0, 1)), ("2.10.3-rc12", (2, 10, 3, 12))],
)
def test_numeric_version(version: str, numbers: tuple[int, int, int, int]) -> None:
    assert exe_metadata.file_version(version) == numbers


def test_version_info_resource_builds() -> None:
    pytest.importorskip("PyInstaller")
    pytest.importorskip("pefile")  # версионный ресурс Windows собирается через pefile
    info = exe_metadata.version_info("1.5.0-rc1")
    rendered = str(info)
    assert "BagroDeRose" in rendered and "CompanyName" in rendered and "LegalCopyright" in rendered


def test_smoke_reads_exe_properties(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hwcheck.ui import smoke

    assert smoke._check_exe_metadata(None) == ("", True)  # из исходников — не проверяется
    monkeypatch.setattr(
        "hwcheck.platform.file_version.read_version_strings",
        lambda path: {"CompanyName": "BagroDeRose", "LegalCopyright": "© 2026 BagroDeRose."},
    )
    line, ok = smoke._check_exe_metadata(tmp_path)
    assert ok and "BagroDeRose" in line
    monkeypatch.setattr(
        "hwcheck.platform.file_version.read_version_strings",
        lambda path: {"CompanyName": "Кто-то", "LegalCopyright": ""},
    )
    assert smoke._check_exe_metadata(tmp_path)[1] is False


@pytest.mark.skipif(sys.platform != "win32", reason="ресурс версии — только Windows")
def test_reads_real_version_resource() -> None:
    from hwcheck.platform.file_version import read_version_strings

    fields = read_version_strings(Path(sys.executable).resolve())
    assert fields.get("ProductName") == "Python"
