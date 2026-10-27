"""Быстрый тест оперативной памяти из Windows (без перезагрузки).

Программа занимает до 70% свободной памяти блоками и много раз записывает в неё узоры,
каждый раз проверяя, что прочитано ровно то, что записано:
- все нули и все единицы;
- шахматка 0xAA / 0x55 (соседние биты в разных состояниях);
- «бегущая единица» (в каждой ячейке единица в своём разряде);
- «адрес в ячейке» (в каждой ячейке её номер — ловит перепутанные адреса).

Это БЫСТРЫЙ тест: часть памяти занята Windows и не проверяется. Он не заменяет
многочасовой MemTest86, о чём честно пишется в результате.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import psutil

from hwcheck.backends.base import STRESS_RAM_QUICK, ProgressCallback, SampleCallback
from hwcheck.models import TestResult, TestStatus
from hwcheck.thresholds import load_thresholds

log = logging.getLogger(__name__)

QUICK_NOTE = "Быстрый тест, не заменяет MemTest86."
PATTERNS = ["zeros", "ones", "checker_aa", "checker_55", "walking_ones", "address"]
_CHUNK_WORDS = 4 * 1024 * 1024  # 32 МБ за раз при проверке, чтобы не тратить лишнюю память
_MB = 1024 * 1024

_CONSTANTS = {
    "zeros": np.uint64(0),
    "ones": np.uint64(0xFFFF_FFFF_FFFF_FFFF),
    "checker_aa": np.uint64(0xAAAA_AAAA_AAAA_AAAA),
    "checker_55": np.uint64(0x5555_5555_5555_5555),
}


def expected_chunk(pattern: str, start_word: int, count: int) -> np.ndarray | np.uint64:
    """Какие значения должны лежать в словах [start_word, start_word + count)."""
    if pattern in _CONSTANTS:
        return _CONSTANTS[pattern]
    index = np.arange(start_word, start_word + count, dtype=np.uint64)
    if pattern == "walking_ones":
        return np.left_shift(np.uint64(1), index % np.uint64(64))
    if pattern == "address":
        return index ^ np.uint64(0x9E37_79B9_7F4A_7C15)  # номер ячейки, «перемешанный» константой
    raise ValueError(f"Неизвестный узор {pattern}")


def fill_block(block: np.ndarray, pattern: str, base_word: int) -> None:
    """Записывает узор в блок памяти."""
    for offset in range(0, block.size, _CHUNK_WORDS):
        count = min(_CHUNK_WORDS, block.size - offset)
        block[offset : offset + count] = expected_chunk(pattern, base_word + offset, count)


def verify_block(block: np.ndarray, pattern: str, base_word: int) -> tuple[int, int | None]:
    """Проверяет блок. Возвращает (число ошибочных слов, номер первого ошибочного слова)."""
    errors = 0
    first: int | None = None
    for offset in range(0, block.size, _CHUNK_WORDS):
        count = min(_CHUNK_WORDS, block.size - offset)
        bad = np.flatnonzero(
            block[offset : offset + count] != expected_chunk(pattern, base_word + offset, count)
        )
        if bad.size:
            errors += int(bad.size)
            if first is None:
                first = base_word + offset + int(bad[0])
    return errors, first


def allocate_blocks(total_mb: int, block_mb: int) -> list[np.ndarray]:
    """Выделяет память блоками; если памяти не хватило — останавливается на том, что есть."""
    blocks: list[np.ndarray] = []
    words = block_mb * _MB // 8
    remaining = total_mb
    while remaining > 0:
        size = min(block_mb, remaining)
        try:
            blocks.append(np.empty(words if size == block_mb else size * _MB // 8, dtype=np.uint64))
        except MemoryError:
            log.info("Памяти хватило только на %d МБ", (total_mb - remaining))
            break
        remaining -= size
    return blocks


def run_ram_test(
    duration: float,
    cancel_event: threading.Event,
    on_progress: ProgressCallback | None = None,
    on_sample: SampleCallback | None = None,
    total_mb: int | None = None,
    block_mb: int = 256,
    corrupt: Callable[[list[np.ndarray], str], None] | None = None,
) -> TestResult:
    """Тестирует память не дольше `duration` секунд (минимум — один узор целиком).

    `corrupt` — только для тестов: портит память после записи, чтобы проверить, что ошибка
    будет найдена.
    """
    if total_mb is None:
        fraction = load_thresholds().get("ram.test_fraction")
        total_mb = int(psutil.virtual_memory().available / _MB * fraction)
    start = time.monotonic()
    blocks = allocate_blocks(total_mb, block_mb)
    tested_mb = sum(block.nbytes for block in blocks) // _MB
    errors = 0
    first_error: str | None = None
    patterns_done = 0

    def time_is_up() -> bool:
        # Первый узор проверяется целиком; дальше останавливаемся, как только вышло время
        # (проверяем после каждого блока, чтобы не превышать отведённое время).
        return patterns_done >= 1 and time.monotonic() - start >= duration

    def stop_now() -> bool:
        return cancel_event.is_set() or time_is_up()

    try:
        while not stop_now():
            for pattern in PATTERNS:
                base = 0
                for block in blocks:
                    if stop_now():
                        break  # недописанный узор не проверяем
                    fill_block(block, pattern, base)
                    base += block.size
                if stop_now():
                    break
                if corrupt is not None:
                    corrupt(blocks, pattern)
                base = 0
                for block in blocks:
                    found, first = verify_block(block, pattern, base)
                    if found and first_error is None and first is not None:
                        first_error = f"узор {pattern}, ячейка {first * 8:#x}"
                    errors += found
                    base += block.size
                    if stop_now():
                        break
                patterns_done += 1
                elapsed = time.monotonic() - start
                if on_progress:
                    on_progress(min(elapsed / duration, 1.0) if duration > 0 else 1.0)
                if stop_now():
                    break
    finally:
        blocks.clear()  # освобождаем память сразу, не дожидаясь сборщика мусора

    elapsed = time.monotonic() - start
    metrics: dict[str, Any] = {
        "tested_mb": tested_mb,
        "errors": errors,
        "patterns_done": patterns_done,
        "passes": patterns_done // len(PATTERNS),
    }
    if first_error:
        metrics["first_error"] = first_error
    if cancel_event.is_set() and errors == 0:
        metrics["cancelled"] = True
        return TestResult(
            name=STRESS_RAM_QUICK,
            status=TestStatus.SKIPPED,
            component="memory",
            duration_s=elapsed,
            metrics=metrics,
            notes=["Тест остановлен пользователем."],
        )
    result = TestResult(
        name=STRESS_RAM_QUICK,
        status=TestStatus.FAILED if errors else TestStatus.PASSED,
        component="memory",
        duration_s=elapsed,
        metrics=metrics,
        notes=[QUICK_NOTE],
    )
    if errors:
        result.notes.append(f"Найдены ошибки памяти: {errors} (первая — {first_error}).")
    if tested_mb == 0:
        result.status = TestStatus.ERROR
        result.notes.append("Не удалось выделить память для теста.")
    if on_progress:
        on_progress(1.0)
    return result
