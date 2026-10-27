"""Реальный бэкенд: собирает сведения о железе этого компьютера и запускает нагрузочные тесты.

Сбор сведений:
- каждый сборщик (система, процессор, память, …) запускается отдельно;
- сборщики работают параллельно, чтобы не ждать каждый PowerShell по очереди;
- если один сборщик упал, остальные продолжают работу, а в снимке появляется
  пометка «не удалось проверить» (`snapshot.errors`);
- на весь сбор есть общий лимит времени (`collect.timeout_s` в thresholds.json): сборщик,
  который не уложился, помечается «не ответил вовремя», остальные данные показываются.

Нагрузочные тесты (`hwcheck/stress/`) подключаются через словарь `stress_runners`:
имя теста → функция запуска. Тест видеопамяти выбирает видеокарту по снимку железа.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from hwcheck.backends.base import (
    STRESS_CPU_LOAD,
    STRESS_DISK_READ,
    STRESS_GPU_LOAD,
    STRESS_RAM_QUICK,
    STRESS_VRAM,
    HardwareBackend,
    ProgressCallback,
    SampleCallback,
)
from hwcheck.collectors import (
    battery,
    board,
    cpu,
    disks,
    events,
    gpu_generic,
    gpu_nvidia,
    memory,
    system,
)
from hwcheck.models import HardwareSnapshot, TestResult, TestStatus, is_discrete_gpu
from hwcheck.platform.elevation import is_admin
from hwcheck.thresholds import load_thresholds

log = logging.getLogger(__name__)

Collector = Callable[[], Any]
StressRunner = Callable[
    [float, threading.Event, ProgressCallback | None, SampleCallback | None], TestResult
]


def collect_gpus() -> list[Any]:
    """Видеокарты: общий список из Windows, дополненный данными nvidia-smi."""
    return gpu_nvidia.merge(gpu_generic.collect(), gpu_nvidia.collect())


def main_gpu_device_id(snapshot: HardwareSnapshot | None) -> str | None:
    """Код устройства «главной» видеокарты: дискретная NVIDIA/AMD с наибольшей памятью."""
    if snapshot is None:
        return None
    discrete = [g for g in snapshot.gpus if is_discrete_gpu(g)]
    if not discrete:
        return None
    return max(discrete, key=lambda g: g.vram_mb or 0).pci_device_id


def default_collectors() -> dict[str, Collector]:
    """Имя поля HardwareSnapshot → функция-сборщик."""
    return {
        "system": system.collect,
        "cpu": cpu.collect,
        "memory": memory.collect,
        "board": board.collect,
        "gpus": collect_gpus,
        "disks": disks.collect,
        "battery": battery.collect,
        "events": events.collect,
    }


class WindowsBackend(HardwareBackend):
    """Бэкенд для настоящего компьютера под Windows."""

    def __init__(
        self,
        collectors: dict[str, Collector] | None = None,
        admin_check: Callable[[], bool] = is_admin,
        stress_runners: dict[str, StressRunner] | None = None,
        collect_timeout: float | None = None,
    ) -> None:
        self.collectors = default_collectors() if collectors is None else collectors
        self.collect_timeout = (
            load_thresholds().get("collect.timeout_s")
            if collect_timeout is None
            else collect_timeout
        )
        self.admin_check = admin_check
        self.stress_runners = (
            self.default_stress_runners() if stress_runners is None else stress_runners
        )
        self.last_snapshot: HardwareSnapshot | None = None

    def default_stress_runners(self) -> dict[str, StressRunner]:
        """Все нагрузочные тесты реального компьютера."""
        from hwcheck.stress import cpu_load, disk_read, gpu_load, ram_quick, vram

        def run_vram(
            duration: float,
            cancel: threading.Event,
            on_progress: ProgressCallback | None,
            on_sample: SampleCallback | None,
        ) -> TestResult:
            target = main_gpu_device_id(self.last_snapshot)
            if target is None and self.last_snapshot is not None and self.last_snapshot.gpus:
                # Есть только встроенная графика — проверять отдельную видеопамять нечего.
                return TestResult(
                    name=STRESS_VRAM, status=TestStatus.SKIPPED, notes=[vram.NO_DISCRETE_GPU_NOTE]
                )
            return vram.run_vram_test(
                duration, cancel, on_progress, on_sample, target_device_id=target
            )

        return {
            STRESS_VRAM: run_vram,
            STRESS_GPU_LOAD: gpu_load.run_gpu_load,
            STRESS_CPU_LOAD: cpu_load.run_cpu_load,
            STRESS_RAM_QUICK: ram_quick.run_ram_test,
            STRESS_DISK_READ: disk_read.run_disk_read,
        }

    def collect(self) -> HardwareSnapshot:
        snapshot = HardwareSnapshot(
            collected_at=datetime.now().isoformat(timespec="seconds"),
            is_admin=self.admin_check(),
        )
        # Каждый сборщик — в своём «фоновом» потоке (daemon): зависший сборщик не задержит
        # ни сводку, ни закрытие программы. Одновременно работают не больше 4 сборщиков.
        limit = threading.Semaphore(4)
        results: dict[str, Any] = {}
        failures: dict[str, BaseException] = {}

        def run(name: str, func: Collector) -> None:
            with limit:
                try:
                    results[name] = func()
                except Exception as error:  # сбой одного сборщика не должен ломать остальные
                    log.exception("Сборщик %s завершился с ошибкой", name)
                    failures[name] = error

        threads = {
            name: threading.Thread(
                target=run, args=(name, func), name=f"collect-{name}", daemon=True
            )
            for name, func in self.collectors.items()
        }
        for thread in threads.values():
            thread.start()
        deadline = time.monotonic() + self.collect_timeout
        for name, thread in threads.items():
            thread.join(max(0.0, deadline - time.monotonic()))
            if name in results:
                setattr(snapshot, name, results[name])
            elif name in failures:
                snapshot.errors[name] = f"не удалось проверить: {failures[name]}"
            else:
                log.warning("Сборщик %s не уложился в %.0f с", name, self.collect_timeout)
                snapshot.errors[name] = "не ответил вовремя — сведения пропущены"
        self.last_snapshot = snapshot
        return snapshot

    def available_stress_tests(self) -> list[str]:
        return list(self.stress_runners)

    def run_stress(
        self,
        name: str,
        duration: float,
        cancel_event: threading.Event,
        on_progress: ProgressCallback | None = None,
        on_sample: SampleCallback | None = None,
    ) -> TestResult:
        runner = self.stress_runners.get(name)
        if runner is None:
            return TestResult(
                name=name,
                status=TestStatus.SKIPPED,
                notes=["Этот тест недоступен на данном компьютере."],
            )
        return runner(duration, cancel_event, on_progress, on_sample)
