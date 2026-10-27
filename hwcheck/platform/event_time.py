"""Время самого нового события журнала Windows «Система» (только чтение).

Нужно детектору отката времени (`hwcheck/license/clock.py`): Windows пишет в журнал
события постоянно, поэтому если часы перевели назад, в журнале останутся записи «из будущего».
"""

from __future__ import annotations

import logging
from datetime import datetime

from hwcheck.platform import runner
from hwcheck.platform.powershell import PowerShellError, parse_ps_date, ps_json
from hwcheck.platform.runner import RunFn

log = logging.getLogger(__name__)

SCRIPT = (
    "Get-WinEvent -LogName System -MaxEvents 1 -ErrorAction Stop | "
    "Select-Object @{Name='Time'; Expression={$_.TimeCreated.ToString('s')}}"
)


def newest_system_event(run_fn: RunFn = runner.run) -> datetime | None:
    """Время последнего события журнала «Система»; недоступно → None."""
    try:
        data = ps_json(SCRIPT, timeout=30.0, run_fn=run_fn)
    except PowerShellError as error:
        log.info("Журнал Windows недоступен для проверки часов: %s", error)
        return None
    if isinstance(data, list) and data:
        data = data[0]
    text = parse_ps_date(data.get("Time")) if isinstance(data, dict) else None
    try:
        moment = datetime.fromisoformat(text) if text else None
    except ValueError:
        return None
    if moment is not None and moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)  # к местному времени, как часы
    return moment
