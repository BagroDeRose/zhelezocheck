"""Фейковый бэкенд: «компьютер понарошку» для тестов и демо-режима.

Данные берутся из готовых сценариев `hwcheck/data/scenarios/*.json`
(исправный ПК, майнинговая видеокарта, перемаркированная карта, умирающий HDD и т.д.).
Нагрузочные тесты не грузят железо: они воспроизводят записанный в сценарии
график датчиков и итог теста.

Формат сценария:
    name, title, description — имя и описание для людей;
    snapshot — HardwareSnapshot в виде JSON;
    stress — для каждого теста: status, component, metrics, notes и
             series (component + points: значение → список опорных точек графика).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from hwcheck.backends.base import (
    ALL_STRESS_TESTS,
    HardwareBackend,
    ProgressCallback,
    SampleCallback,
)
from hwcheck.config import package_data_dir
from hwcheck.models import HardwareSnapshot, SensorSample, TestResult, TestStatus


def scenarios_dir() -> Path:
    """Папка со сценариями демо-режима."""
    return package_data_dir() / "scenarios"


@dataclass
class StressSpec:
    """Описание одного нагрузочного теста в сценарии."""

    status: TestStatus
    component: str
    metrics: dict[str, Any]
    notes: list[str]
    series_component: str = ""
    series_points: dict[str, list[float | None]] = field(default_factory=dict)


@dataclass
class Scenario:
    """Сценарий демо-режима: снимок железа и итоги нагрузочных тестов."""

    name: str
    title: str
    description: str
    snapshot: HardwareSnapshot
    stress: dict[str, StressSpec]


def list_scenarios() -> list[str]:
    """Имена всех доступных сценариев (по именам файлов)."""
    return sorted(path.stem for path in scenarios_dir().glob("*.json"))


@cache
def _read_scenario_file(name: str) -> dict[str, Any]:
    path = scenarios_dir() / f"{name}.json"
    if not path.is_file():
        raise KeyError(f"Сценарий «{name}» не найден")
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenario(name: str) -> Scenario:
    """Загружает сценарий по имени. Неизвестное имя → KeyError."""
    raw = _read_scenario_file(name)
    stress: dict[str, StressSpec] = {}
    for test_name, spec in raw.get("stress", {}).items():
        series = spec.get("series") or {}
        stress[test_name] = StressSpec(
            status=TestStatus(spec.get("status", "passed")),
            component=spec.get("component", ""),
            metrics=dict(spec.get("metrics", {})),
            notes=list(spec.get("notes", [])),
            series_component=series.get("component", ""),
            series_points={key: list(values) for key, values in series.get("points", {}).items()},
        )
    return Scenario(
        name=raw.get("name", name),
        title=raw.get("title", name),
        description=raw.get("description", ""),
        snapshot=HardwareSnapshot.from_dict(raw["snapshot"]),
        stress=stress,
    )


def interpolate(points: list[float | None], position: float) -> float | None:
    """Значение графика в точке `position` (0.0 — начало, 1.0 — конец) по опорным точкам."""
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    scaled = min(max(position, 0.0), 1.0) * (len(points) - 1)
    left = int(scaled)
    if left >= len(points) - 1:
        return points[-1]
    a, b = points[left], points[left + 1]
    if a is None or b is None:
        return None
    return round(a + (b - a) * (scaled - left), 2)


class FakeBackend(HardwareBackend):
    """Бэкенд, воспроизводящий сценарий.

    `time_scale` — сколько реальных секунд длится одна «секунда» теста:
    1.0 — как настоящий тест, 0.05 — в 20 раз быстрее (демо), 0.0 — мгновенно (тесты).
    """

    def __init__(self, scenario: str, time_scale: float = 0.0, sample_interval: float = 1.0):
        self.scenario = load_scenario(scenario)
        self.time_scale = time_scale
        self.sample_interval = sample_interval

    def collect(self) -> HardwareSnapshot:
        # Возвращаем копию, чтобы изменения у получателя не портили сценарий.
        return HardwareSnapshot.from_dict(self.scenario.snapshot.to_dict())

    def available_stress_tests(self) -> list[str]:
        return [name for name in ALL_STRESS_TESTS if name in self.scenario.stress]

    def run_stress(
        self,
        name: str,
        duration: float,
        cancel_event: threading.Event,
        on_progress: ProgressCallback | None = None,
        on_sample: SampleCallback | None = None,
    ) -> TestResult:
        spec = self.scenario.stress.get(name)
        if spec is None:
            return TestResult(
                name=name,
                status=TestStatus.SKIPPED,
                notes=["Этот тест недоступен в демо-сценарии."],
            )

        steps = max(1, int(duration / self.sample_interval))
        samples: list[SensorSample] = []
        for index in range(steps):
            wait = self.sample_interval * self.time_scale
            if cancel_event.wait(wait) if wait > 0 else cancel_event.is_set():
                return TestResult(
                    name=name,
                    status=TestStatus.SKIPPED,
                    component=spec.component,
                    duration_s=index * self.sample_interval,
                    metrics={"cancelled": True},
                    samples=samples,
                    notes=["Тест остановлен пользователем."],
                )
            if spec.series_points:
                position = index / (steps - 1) if steps > 1 else 1.0
                sample = SensorSample(
                    t=index * self.sample_interval,
                    component=spec.series_component,
                    values={
                        key: interpolate(points, position)
                        for key, points in spec.series_points.items()
                    },
                )
                samples.append(sample)
                if on_sample:
                    on_sample(sample)
            if on_progress:
                on_progress((index + 1) / steps)

        return TestResult(
            name=name,
            status=spec.status,
            component=spec.component,
            duration_s=float(duration),
            metrics=dict(spec.metrics),
            samples=samples,
            notes=list(spec.notes),
        )
