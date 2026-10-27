"""Лёгкий «рабочий процесс» для теста очереди сообщений CpuWorkers (без настоящей нагрузки).

Модуль отдельный, чтобы его можно было импортировать в дочернем процессе (spawn).
"""

from typing import Any

MESSAGES = 3000


def flood_worker(stop: Any, queue: Any, seed: int, reference: int, max_seconds: float) -> None:
    """Шлёт много сообщений подряд (переполняет канал), затем «done» и ждёт остановки."""
    for index in range(1, MESSAGES + 1):
        queue.put({"seed": seed, "iterations": index, "mismatches": 0, "pad": "x" * 40})
    queue.put({"seed": seed, "iterations": MESSAGES, "mismatches": 0, "done": True})
    stop.wait(max_seconds)
