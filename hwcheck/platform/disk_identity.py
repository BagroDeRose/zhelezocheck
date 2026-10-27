r"""Чтение сведений о накопителе для привязки лицензии (только чтение, CIM).

`drive_script("E:")` — по букве диска находит физический накопитель:
Win32_LogicalDisk → Win32_DiskPartition → Win32_DiskDrive (модель, серийный номер, PNPDeviceID,
интерфейс, а также DeviceID `\\.\PHYSICALDRIVEn` и Index — для второго чтения серийника через
IOCTL, SPEC 1.5, 37.1). Ничего не меняет.
"""

from __future__ import annotations

import re
from typing import Any

from hwcheck.platform import runner
from hwcheck.platform.powershell import ps_json
from hwcheck.platform.runner import RunFn

_DRIVE = re.compile(r"^[A-Za-z]:$")


def valid_drive(drive: str) -> bool:
    return bool(_DRIVE.match(drive))


def drive_script(drive: str) -> str:
    """Скрипт PowerShell для буквы диска вида «E:» (буква проверяется заранее)."""
    if not valid_drive(drive):
        raise ValueError(f"недопустимая буква диска: {drive!r}")
    letter = drive.upper()
    return (
        f"$ld = Get-CimInstance -ClassName Win32_LogicalDisk -Filter \"DeviceID='{letter}'\"; "
        "if ($ld) { "
        "$parts = @(Get-CimAssociatedInstance -InputObject $ld "
        "-ResultClassName Win32_DiskPartition); "
        "$drives = @($parts | ForEach-Object { Get-CimAssociatedInstance -InputObject $_ "
        "-ResultClassName Win32_DiskDrive }); "
        "$drives | Select-Object -First 1 "
        "Model,SerialNumber,PNPDeviceID,InterfaceType,MediaType,DeviceID,Index }"
    )


def read_drive(drive: str, run_fn: RunFn = runner.run) -> Any:
    """Сведения о физическом накопителе, на котором находится диск `drive`."""
    return ps_json(drive_script(drive), timeout=30.0, run_fn=run_fn)
