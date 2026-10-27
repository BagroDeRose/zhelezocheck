"""Тесты логирования: секреты не попадают в файл лога, файлы ротируются."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from hwcheck import logging_setup
from hwcheck.config import get_paths

KEY = "ABCDE-FGHIJ-KLMNO-PQRST-UVWXY-Z2345"


@pytest.fixture
def log_file(tmp_path: Path) -> Iterator[Path]:
    paths = get_paths(tmp_path)
    handler = logging_setup.setup_logging(paths)
    yield paths.logs / logging_setup.LOG_FILE_NAME
    logging.getLogger().removeHandler(handler)
    handler.close()


def _read(path: Path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return path.read_text(encoding="utf-8")


def test_key_not_written(log_file: Path) -> None:
    log = logging.getLogger("hwcheck.test")
    log.warning("активирован ключ %s", KEY)
    log.warning("ключ в тексте: " + KEY.lower())
    text = _read(log_file)
    assert "активирован ключ" in text
    assert KEY not in text
    assert KEY.lower() not in text
    assert logging_setup.REDACTED in text


def test_key_in_exception_not_written(log_file: Path) -> None:
    log = logging.getLogger("hwcheck.test")
    try:
        raise ValueError(f"плохой ключ {KEY}")
    except ValueError:
        log.exception("ошибка активации")
    text = _read(log_file)
    assert "ошибка активации" in text
    assert KEY not in text


def test_phone_not_written(log_file: Path) -> None:
    logging.getLogger("hwcheck.test").warning("продавец +7 (912) 345-67-89, 89123456789")
    text = _read(log_file)
    assert "345-67-89" not in text
    assert "89123456789" not in text


def test_redact_keeps_normal_text() -> None:
    text = "GPU RTX-3060 температура 71 C, VBIOS 94.06.2F.00.9A"
    assert logging_setup.redact(text) == text


def test_rotation_configured(log_file: Path) -> None:
    handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, logging_setup.RotatingFileHandler)
    ]
    assert handlers and handlers[0].maxBytes > 0 and handlers[0].backupCount > 0
