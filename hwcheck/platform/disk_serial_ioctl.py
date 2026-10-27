r"""Второе, независимое чтение серийного номера накопителя — IOCTL_STORAGE_QUERY_PROPERTY.

Первое чтение идёт через WMI/CIM (`disk_identity.py`). Чтобы серийный номер нельзя было
подменить одним поддельным ответом WMI (фильтр-драйвер, виртуальный диск), программа читает его
второй раз напрямую у устройства: открывает `\\.\PHYSICALDRIVEn` и запрашивает
`StorageDeviceProperty` (SPEC 1.5, 37.1 п.3, 37.2). Только чтение, ничего не меняет; на других ОС
и при ошибке возвращает пустую строку.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
STORAGE_DEVICE_PROPERTY = 0
PROPERTY_STANDARD_QUERY = 0
GENERIC_READ = 0x80000000
FILE_SHARE_READ_WRITE = 0x00000003
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value
_PHYSICAL = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)


def physical_drive_path(device_id: str, index: object = None) -> str:
    r"""`\\.\PHYSICALDRIVE2` из DeviceID накопителя (или из его индекса)."""
    match = _PHYSICAL.search(device_id or "")
    if match:
        return rf"\\.\PHYSICALDRIVE{int(match.group(1))}"
    if isinstance(index, int) or (isinstance(index, str) and index.isdigit()):
        return rf"\\.\PHYSICALDRIVE{int(index)}"
    return ""


class _StoragePropertyQuery(ctypes.Structure):
    _fields_ = [
        ("PropertyId", wintypes.DWORD),
        ("QueryType", wintypes.DWORD),
        ("AdditionalParameters", ctypes.c_byte * 1),
    ]


class _StorageDeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("Size", wintypes.DWORD),
        ("DeviceType", ctypes.c_byte),
        ("DeviceTypeModifier", ctypes.c_byte),
        ("RemovableMedia", ctypes.c_byte),
        ("CommandQueueing", ctypes.c_byte),
        ("VendorIdOffset", wintypes.DWORD),
        ("ProductIdOffset", wintypes.DWORD),
        ("ProductRevisionOffset", wintypes.DWORD),
        ("SerialNumberOffset", wintypes.DWORD),
        ("BusType", wintypes.DWORD),
        ("RawPropertiesLength", wintypes.DWORD),
        ("RawDeviceProperties", ctypes.c_byte * 1),
    ]


def read_ioctl_serial(physical_path: str) -> str:
    """Серийный номер накопителя через IOCTL (пустая строка, если не удалось или не Windows)."""
    if sys.platform != "win32" or not physical_path:
        return ""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]  # fmt: skip
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]  # fmt: skip
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    # Нулевые права доступа: запрос свойств не требует прав администратора (в отличие от чтения).
    handle = kernel32.CreateFileW(
        physical_path, 0, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None
    )
    if handle in (INVALID_HANDLE, 0, None):
        log.info("IOCTL: не удалось открыть %s", physical_path)
        return ""
    try:
        query = _StoragePropertyQuery(STORAGE_DEVICE_PROPERTY, PROPERTY_STANDARD_QUERY, (0,))
        buffer = ctypes.create_string_buffer(1024)
        returned = wintypes.DWORD()
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_STORAGE_QUERY_PROPERTY,
            ctypes.byref(query),
            ctypes.sizeof(query),
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(returned),
            None,
        )
        if not ok:
            log.info("IOCTL: DeviceIoControl не удался для %s", physical_path)
            return ""
        descriptor = ctypes.cast(buffer, ctypes.POINTER(_StorageDeviceDescriptor)).contents
        offset = descriptor.SerialNumberOffset
        if offset == 0 or offset >= returned.value:
            return ""
        raw = ctypes.string_at(ctypes.addressof(buffer) + offset)
        return raw.decode("latin-1", errors="ignore").strip()
    finally:
        kernel32.CloseHandle(handle)
