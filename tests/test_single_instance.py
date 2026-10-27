"""Тесты защиты от второй копии программы и номера процесса в журнале (задача 20.3)."""

import logging
from pathlib import Path

import pytest

from hwcheck.single_instance import InstanceLock


def test_second_copy_does_not_get_lock(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    second = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    assert first.acquire(timeout_ms=0)
    assert not second.acquire(timeout_ms=100)
    first.release()
    assert second.acquire(timeout_ms=100)  # после закрытия первой копии — можно
    second.release()


def test_read_only_stick_does_not_block_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = InstanceLock(tmp_path / "нет" / "hwcheck.lock")
    monkeypatch.setattr(lock, "_can_write", lambda: False)
    assert lock.acquire(timeout_ms=0)  # писать некуда — работаем без защиты, но запускаемся


def test_log_lines_carry_process_id(tmp_path: Path) -> None:
    from hwcheck.config import get_paths
    from hwcheck.logging_setup import setup_logging

    handler = setup_logging(get_paths(tmp_path))
    try:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "привет", None, None)
        assert f"[{record.process}]" in handler.format(record)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
