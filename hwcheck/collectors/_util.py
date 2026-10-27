"""Мелкие помощники для разбора сырых данных сборщиков."""

from __future__ import annotations

from typing import Any


def as_list(value: Any) -> list[dict[str, Any]]:
    """PowerShell отдаёт один объект без массива — приводим всё к списку словарей."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def to_int(value: Any) -> int | None:
    """Число из строки/числа; пустое или мусор → None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    """Дробное число из строки/числа; пустое, «[N/A]» или мусор → None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", ".")
    for suffix in (" W", " MHz", " MiB", " %", " C", "W", "MHz", "MiB", "%", "C"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    try:
        return float(text)
    except ValueError:
        return None


def clean(value: Any) -> str:
    """Строка без лишних пробелов; None → пустая строка."""
    if value is None:
        return ""
    return " ".join(str(value).split())
