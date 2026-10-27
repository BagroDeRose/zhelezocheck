"""Пороги проверок (температуры, допуски, износ) и длительности тестов.

Все числа хранятся в `hwcheck/data/thresholds.json` вместе с обоснованием («why»),
чтобы их можно было поправить без изменения кода. Здесь — только загрузка и доступ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from hwcheck.config import package_data_dir


@dataclass(frozen=True)
class Thresholds:
    """Загруженные пороги и длительности тестов по режимам (quick / full / short)."""

    values: dict[str, float]
    reasons: dict[str, str]
    units: dict[str, str]
    durations: dict[str, dict[str, float]]

    def get(self, key: str) -> float:
        """Значение порога. Неизвестный ключ → KeyError (опечатка в коде не пройдёт тихо)."""
        if key not in self.values:
            raise KeyError(f"Порог «{key}» не найден в thresholds.json")
        return self.values[key]

    def why(self, key: str) -> str:
        """Обоснование порога (для экрана настроек)."""
        return self.reasons[key]

    def duration(self, mode: str, test: str) -> float:
        """Длительность теста `test` в режиме `mode`, секунд."""
        return self.durations[mode][test]


def _parse(path: Path) -> Thresholds:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["thresholds"]
    return Thresholds(
        values={key: float(item["value"]) for key, item in items.items()},
        reasons={key: item["why"] for key, item in items.items()},
        units={key: item["unit"] for key, item in items.items()},
        durations={
            mode: {test: float(sec) for test, sec in tests.items()}
            for mode, tests in data["durations_s"].items()
        },
    )


@cache
def _default() -> Thresholds:
    return _parse(package_data_dir() / "thresholds.json")


def load_thresholds(path: Path | None = None) -> Thresholds:
    """Загружает пороги: по умолчанию — из файла программы (результат кэшируется)."""
    return _default() if path is None else _parse(path)
