"""Расшифровка событий журнала Windows (SPEC_V2_1, этап 46).

Тексты — в `hwcheck/data/event_ids.yaml`. Поиск по порядку: точное «источник:код», затем
«источник:*», затем значения группы — у каждого события всегда есть название, компонент и
значимость. Оговорки (например, что Kernel-Power 41 — не доказательство неисправности блока
питания) берутся оттуда же.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir


@dataclass(frozen=True)
class EventInfo:
    title: str
    component: str
    significance: str
    note: str = ""


@cache
def _data() -> dict[str, Any]:
    text = (package_data_dir() / "event_ids.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def group_title(group: str) -> str:
    """Название группы событий для отчёта (неизвестная группа — её ключ)."""
    return _data()["groups"].get(group, {}).get("title", group)


def describe(provider: str, event_id: int, group: str) -> EventInfo:
    """Что значит событие: точная запись, запись источника или значения группы."""
    events: dict[str, dict[str, str]] = _data()["events"]
    entry = events.get(f"{provider}:{event_id}") or events.get(f"{provider}:*") or {}
    defaults = _data()["groups"].get(group, {})
    return EventInfo(
        title=entry.get("title") or defaults.get("title") or f"{provider}, событие {event_id}",
        component=entry.get("component") or defaults.get("component", ""),
        significance=entry.get("significance") or defaults.get("significance", "средняя"),
        note=entry.get("note", ""),
    )
