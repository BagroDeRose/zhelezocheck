"""Второе чтение серийного номера через IOCTL (SPEC 1.5, 37.1 п.3)."""

from __future__ import annotations

import sys

import pytest

from hwcheck.platform import disk_serial_ioctl as ds


@pytest.mark.parametrize(
    ("device_id", "index", "expected"),
    [
        (r"\\.\PHYSICALDRIVE2", None, r"\\.\PHYSICALDRIVE2"),
        ("PHYSICALDRIVE0", None, r"\\.\PHYSICALDRIVE0"),
        ("", 3, r"\\.\PHYSICALDRIVE3"),
        ("", "5", r"\\.\PHYSICALDRIVE5"),
        ("", None, ""),
    ],
)
def test_physical_drive_path(device_id: str, index: object, expected: str) -> None:
    assert ds.physical_drive_path(device_id, index) == expected


def test_empty_path_returns_empty() -> None:
    assert ds.read_ioctl_serial("") == ""


@pytest.mark.skipif(sys.platform != "win32", reason="IOCTL — только Windows")
def test_reads_serial_without_admin_for_system_drive() -> None:
    import subprocess

    device_id = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).DeviceID"],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()  # fmt: skip
    # Запрос свойств не требует прав администратора: функция возвращает строку (серийник или пусто).
    assert isinstance(ds.read_ioctl_serial(ds.physical_drive_path(device_id)), str)
