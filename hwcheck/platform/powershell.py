"""Вызов PowerShell с выводом в JSON.

Сборщики сведений о железе спрашивают Windows через PowerShell (`Get-CimInstance` и т.п.).
Чтобы не разбирать текст «на глаз», результат всегда превращается в JSON
командой `ConvertTo-Json -Depth 5 -Compress`, а здесь — в обычные словари и списки Python.

Особенности PowerShell, которые учитываются:
- один объект превращается в JSON-объект, несколько — в массив (`ps_json_list` всегда даёт список);
- пустой результат даёт пустой вывод;
- даты в старом PowerShell 5.1 выглядят как `/Date(1689811200000)/` (`parse_ps_date`).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from hwcheck.platform import runner
from hwcheck.platform.runner import RunFn

__all__ = ["PowerShellError", "RunFn", "build_command", "parse_ps_date", "ps_json", "ps_json_list"]

POWERSHELL_EXE = "powershell.exe"

# Вывод в UTF-8 и остановка на первой ошибке — чтобы ошибка не терялась в выводе.
_PREAMBLE = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$ProgressPreference = 'SilentlyContinue'; "
    "$ErrorActionPreference = 'Stop'; "
)

_ACCESS_DENIED_MARKERS = ("access denied", "отказано в доступе", "0x80041003", "unauthorized")


class PowerShellError(RuntimeError):
    """PowerShell завершился с ошибкой, по таймауту или не найден."""

    @property
    def access_denied(self) -> bool:
        """Ошибка из-за нехватки прав (нужен запуск от администратора)."""
        text = str(self).lower()
        return any(marker in text for marker in _ACCESS_DENIED_MARKERS)


def build_command(script: str) -> list[str]:
    """Собирает командную строку PowerShell с принудительным выводом в JSON."""
    full_script = f"{_PREAMBLE}@({script}) | ConvertTo-Json -Depth 5 -Compress"
    return [
        POWERSHELL_EXE,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        full_script,
    ]


def ps_json(script: str, *, timeout: float = 60.0, run_fn: RunFn = runner.run) -> Any:
    """Выполняет скрипт PowerShell и возвращает разобранный JSON (словарь, список или None)."""
    result = run_fn(build_command(script), timeout=timeout, encoding_hint="utf-8")
    if result.not_found:
        raise PowerShellError(f"PowerShell не найден: {result.stderr}")
    if result.timed_out:
        raise PowerShellError(f"PowerShell не ответил за {timeout:.0f} с")
    if result.cancelled:
        raise PowerShellError("Команда PowerShell отменена")
    if result.returncode != 0:
        message = _first_error_line(result.stderr) or f"код завершения {result.returncode}"
        raise PowerShellError(message + "\n" + result.stderr)
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise PowerShellError(f"PowerShell вернул не JSON: {text[:200]!r}") from error


def ps_json_list(
    script: str, *, timeout: float = 60.0, run_fn: RunFn = runner.run
) -> list[dict[str, Any]]:
    """То же, что `ps_json`, но всегда возвращает список объектов (возможно, пустой)."""
    data = ps_json(script, timeout=timeout, run_fn=run_fn)
    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _first_error_line(stderr: str) -> str:
    for line in stderr.splitlines():
        if line.strip():
            return line.strip()
    return ""


_MS_DATE_RE = re.compile(r"^/Date\((-?\d+)\)/$")
_CIM_DATE_RE = re.compile(r"^(\d{14})\.\d+[+-]\d+$")


def parse_ps_date(value: Any) -> str | None:
    """Приводит дату из вывода PowerShell/WMI к строке ISO 8601. Неизвестный формат → как есть."""
    if not value or not isinstance(value, str):
        return None
    match = _MS_DATE_RE.match(value.strip())
    if match:
        moment = datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC)
        return moment.isoformat()
    match = _CIM_DATE_RE.match(value.strip())
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").isoformat()
    return value.strip()
