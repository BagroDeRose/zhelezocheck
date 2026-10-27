"""Интерфейс бэкенда — «откуда программа берёт данные о железе».

Есть два бэкенда с одинаковым интерфейсом:
- `windows.py` — настоящий: спрашивает Windows и запускает нагрузочные тесты;
- `fake.py` — фейковый: отдаёт заранее записанные сценарии (для тестов и демо-режима).

Остальная программа (движок тестов, интерфейс) работает только через этот интерфейс
и не знает, какой бэкенд под ним.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

from hwcheck.models import HardwareSnapshot, SensorSample, TestResult

# Имена нагрузочных тестов (одинаковые для всех бэкендов).
STRESS_VRAM = "vram"
STRESS_GPU_LOAD = "gpu_load"
STRESS_CPU_LOAD = "cpu_load"
STRESS_RAM_QUICK = "ram_quick"
STRESS_DISK_READ = "disk_read"

ALL_STRESS_TESTS = [
    STRESS_VRAM,
    STRESS_GPU_LOAD,
    STRESS_CPU_LOAD,
    STRESS_RAM_QUICK,
    STRESS_DISK_READ,
]

ProgressCallback = Callable[[float], None]
"""Сообщает долю выполнения теста от 0.0 до 1.0."""

SampleCallback = Callable[[SensorSample], None]
"""Сообщает очередной замер датчиков."""


class HardwareBackend(ABC):
    """Общий интерфейс всех бэкендов."""

    # Сколько реальных секунд длится одна плановая «секунда» теста (демо-бэкенд ускоряет время).
    time_scale: float = 1.0

    @abstractmethod
    def collect(self) -> HardwareSnapshot:
        """Собирает сведения о железе без нагрузки (только чтение)."""

    @abstractmethod
    def available_stress_tests(self) -> list[str]:
        """Какие нагрузочные тесты можно запустить на этом компьютере."""

    @abstractmethod
    def run_stress(
        self,
        name: str,
        duration: float,
        cancel_event: threading.Event,
        on_progress: ProgressCallback | None = None,
        on_sample: SampleCallback | None = None,
    ) -> TestResult:
        """Запускает нагрузочный тест `name` на `duration` секунд.

        Тест должен проверять `cancel_event` и завершаться не позже чем через 3 секунды
        после его установки.
        """
