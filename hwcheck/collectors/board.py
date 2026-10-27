"""Сборщик сведений о материнской плате (WMI `Win32_BaseBoard`). Серийный номер не читаем."""

from __future__ import annotations

from typing import Any

from hwcheck.collectors._util import as_list, clean
from hwcheck.models import BoardInfo
from hwcheck.platform import runner
from hwcheck.platform.powershell import RunFn, ps_json

SCRIPT = "Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,Version"


def parse(data: Any) -> BoardInfo:
    """Превращает вывод `SCRIPT` в BoardInfo."""
    items = as_list(data)
    raw: dict[str, Any] = items[0] if items else {}
    return BoardInfo(
        manufacturer=clean(raw.get("Manufacturer")),
        product=clean(raw.get("Product")),
        version=clean(raw.get("Version")),
    )


def collect(run_fn: RunFn = runner.run) -> BoardInfo:
    """Читает сведения о материнской плате через PowerShell."""
    return parse(ps_json(SCRIPT, run_fn=run_fn))
