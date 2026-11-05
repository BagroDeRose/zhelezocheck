"""Человеческие подписи для «Основания» находок и метрик тестов (этап 50 v2.1).

После ручной проверки 2.1.0-rc1: в отчёте были видны технические ключи («model=…,
wear_text=, tested_gb=7.96875», «clock_drop_pct = 0.8»). Подписи, единицы и точность —
в `hwcheck/data/report_labels.yaml`; здесь только форматирование:
- `format_evidence` — улики правила (словарь) → «Модель: …; Проверено: 8,0 ГБ»;
- `readable_evidence` — то же для старых проверок, где основание сохранено строкой «k=v»;
- `metric_rows` — метрики теста → пары (подпись, значение) по-русски.
Неизвестный ключ показывается как есть: специалисту ничего не прячем.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir

TEXT_LIMIT = 300  # длинный готовый текст правила обрезается, чтобы не раздувать таблицу
_LEGACY = re.compile(r"(?:^|, )([a-z][a-z_0-9]*)=")


@cache
def _labels() -> dict[str, dict[str, dict[str, Any]]]:
    text = (package_data_dir() / "report_labels.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _decimal(value: float, digits: int | None) -> str:
    if digits is None:
        digits = 0 if abs(value) >= 10 or value == int(value) else 1
    return f"{value:.{digits}f}".replace(".", ",")


def format_value(value: Any, spec: dict[str, Any] | None = None) -> str:
    """Одно значение по-русски: да/нет, число с нужной точностью и единицей, список."""
    spec = spec or {}
    if value is None:
        return "нет данных"
    if isinstance(value, bool):
        text = "да" if value else "нет"
    elif isinstance(value, int | float):
        text = _decimal(float(value), spec.get("digits"))
    elif isinstance(value, list | tuple):
        text = ", ".join(str(item) for item in value) or "нет"
    else:
        text = str(value).strip().lstrip(",").strip()
    unit = spec.get("unit")
    if unit and isinstance(value, int | float) and not isinstance(value, bool):
        text = f"{text} {unit}"
    return text


def _pair(key: str, value: Any, table: dict[str, dict[str, Any]]) -> str | None:
    if value is None or value == "":
        return None
    spec = table.get(key)
    if spec is None:
        return f"{key}: {format_value(value)}"  # неизвестный ключ — как есть
    if spec.get("hide"):
        return None
    text = format_value(value, spec)
    if not text:
        return None
    label = spec.get("label")
    if label is None:
        return text[:TEXT_LIMIT]
    return f"{label}: {text}"


def format_evidence(evidence: dict[str, Any]) -> str:
    """Улики правила → «Модель: …; Температура: 74 °C» (без служебного «component»)."""
    table = _labels()["evidence"]
    parts = [_pair(key, value, table) for key, value in evidence.items() if key != "component"]
    return "; ".join(part for part in parts if part)


def _legacy_value(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def readable_evidence(text: str) -> str:
    """Основание из старой проверки («model=X, temp=74») → по-русски; новое — без изменений."""
    if not text or not _LEGACY.match(text):
        return text
    keys = _LEGACY.findall(text)
    values = _LEGACY.split(text)[2::2]  # split даёт [пусто, ключ, значение, ключ, значение…]
    return format_evidence(
        {key: _legacy_value(value) for key, value in zip(keys, values, strict=False)}
    )


def metric_rows(metrics: dict[str, Any]) -> list[tuple[str, str]]:
    """Метрики теста → (подпись, значение); порядок — как в справочнике, затем остальные."""
    table = _labels()["metrics"]
    keys = [key for key in table if key in metrics]
    keys += sorted(key for key in metrics if key not in table)
    rows = []
    for key in keys:
        spec = table.get(key, {})
        if spec.get("hide"):
            continue
        value = metrics[key]
        rows.append((spec.get("label") or key, format_value(value, spec) if value != "" else "—"))
    return rows
