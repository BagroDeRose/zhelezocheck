"""Тесты быстрого теста ОЗУ на малом объёме памяти."""

import threading

import numpy as np
import pytest

from hwcheck.models import TestStatus
from hwcheck.stress import ram_quick


@pytest.mark.parametrize("pattern", ram_quick.PATTERNS)
def test_fill_and_verify_each_pattern(pattern: str) -> None:
    block = np.empty(10_000, dtype=np.uint64)
    ram_quick.fill_block(block, pattern, base_word=123)
    assert ram_quick.verify_block(block, pattern, base_word=123) == (0, None)


def test_patterns_differ() -> None:
    a = np.empty(64, dtype=np.uint64)
    b = np.empty(64, dtype=np.uint64)
    ram_quick.fill_block(a, "walking_ones", 0)
    ram_quick.fill_block(b, "address", 0)
    assert int(a[3]) == 8
    assert not np.array_equal(a, b)


def test_small_run_passes() -> None:
    result = ram_quick.run_ram_test(0.0, threading.Event(), total_mb=8, block_mb=2)
    assert result.status is TestStatus.PASSED
    assert result.metrics["tested_mb"] == 8
    assert result.metrics["errors"] == 0
    assert result.metrics["patterns_done"] >= 1
    assert ram_quick.QUICK_NOTE in result.notes


def test_injected_error_is_found() -> None:
    def flip_one_bit(blocks: list[np.ndarray], pattern: str) -> None:
        if pattern == "checker_aa":
            blocks[1][777] ^= np.uint64(1 << 13)

    result = ram_quick.run_ram_test(
        5.0, threading.Event(), total_mb=6, block_mb=2, corrupt=flip_one_bit
    )
    assert result.status is TestStatus.FAILED
    assert result.metrics["errors"] >= 1
    first = result.metrics["first_error"]
    assert "checker_aa" in first
    assert hex((2 * 1024 * 1024 // 8 + 777) * 8) in first


def test_cancel() -> None:
    cancel = threading.Event()
    cancel.set()
    result = ram_quick.run_ram_test(60, cancel, total_mb=4, block_mb=2)
    assert result.status is TestStatus.SKIPPED


def test_allocation_limited_by_block() -> None:
    blocks = ram_quick.allocate_blocks(5, 2)
    assert [b.nbytes // (1024 * 1024) for b in blocks] == [2, 2, 1]
