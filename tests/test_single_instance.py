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


def test_held_by_other_sees_new_copy(tmp_path: Path) -> None:
    """Перезапуск с правами: старая копия отпустила замок и видит, что новая его заняла."""
    old = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    new = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    assert old.acquire(timeout_ms=0) and old.active
    assert not old.held_by_other()  # замок у неё самой
    old.release()
    assert not old.active and not old.held_by_other()  # замок свободен
    assert new.acquire(timeout_ms=0)
    assert old.held_by_other()  # новая копия запустилась
    new.release()
    assert not old.held_by_other()
    assert old.acquire(timeout_ms=0)  # проверка не оставила свой замок
    old.release()


def test_ready_mark_tells_old_copy_the_new_one_works(tmp_path: Path) -> None:
    """Копия с правами отмечает «готова» (окно открыто, сведения собраны) ключом от старого окна."""
    old = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    new = InstanceLock(tmp_path / "data" / "hwcheck.lock")
    old.clear_ready()
    assert old.ready_token() is None
    new.mark_ready("abc123")
    assert old.ready_token() == "abc123"
    old.clear_ready()
    assert old.ready_token() is None
    (tmp_path / "data" / "relaunch.ready").write_bytes(b"\xff\xfe\x00")
    assert old.ready_token() is None  # испорченная отметка — не «готова»


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
