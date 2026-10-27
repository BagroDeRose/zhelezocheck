"""Тест чтения системного диска — ТОЛЬКО ЧТЕНИЕ, ничего не записывается.

Последовательно читаем крупные системные файлы (например, `C:\\Windows\\System32\\*.dll`,
всего до 2 ГБ) и замеряем скорость. Ошибка чтения (а не «нет доступа») означает проблемы
с поверхностью/памятью диска.

Скорость приблизительная: часть файлов Windows может держать в памяти (кэш).
Файлы открываются только в режиме "rb" (чтение байтов) — это проверяется тестом.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, BinaryIO

from hwcheck.backends.base import STRESS_DISK_READ, ProgressCallback, SampleCallback
from hwcheck.models import TestResult, TestStatus

log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024**3
CHUNK = 4 * 1024 * 1024
MIN_FILE_SIZE = 1024 * 1024
_MB = 1024 * 1024

Opener = Callable[[Path], BinaryIO]


def default_roots() -> list[Path]:
    """Где брать файлы: системные папки Windows (существуют на любом компьютере с Windows)."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return [windir / "System32", windir / "SysWOW64", windir / "WinSxS"]


def open_for_reading(path: Path) -> BinaryIO:
    """Открывает файл ТОЛЬКО для чтения."""
    return open(path, "rb", buffering=0)  # noqa: SIM115 — закрывается вызывающим кодом


def pick_files(roots: Iterable[Path], max_bytes: int = MAX_BYTES) -> list[Path]:
    """Крупные файлы из папок (без обхода вглубь), суммарно до `max_bytes`."""
    candidates: list[tuple[int, Path]] = []
    for root in roots:
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            size = entry.stat(follow_symlinks=False).st_size
                            if size >= MIN_FILE_SIZE:
                                candidates.append((size, Path(entry.path)))
                    except OSError:
                        continue
        except OSError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    chosen: list[Path] = []
    total = 0
    for size, path in candidates:
        if total >= max_bytes:
            break
        chosen.append(path)
        total += size
    return chosen


def speed_mbps(read_bytes: int, seconds: float) -> float:
    """Скорость в МБ/с."""
    return round(read_bytes / _MB / seconds, 1) if seconds > 0 else 0.0


def run_disk_read(
    duration: float,
    cancel_event: threading.Event,
    on_progress: ProgressCallback | None = None,
    on_sample: SampleCallback | None = None,
    roots: list[Path] | None = None,
    max_bytes: int = MAX_BYTES,
    opener: Opener = open_for_reading,
) -> TestResult:
    """Читает файлы, пока не прочитает `max_bytes`, не выйдет время или не отменят."""
    files = pick_files(roots or default_roots(), max_bytes)
    start = time.monotonic()
    read_bytes = 0
    read_errors = 0
    skipped = 0
    done_files = 0
    error_examples: list[str] = []
    cancelled = False
    for path in files:
        if cancel_event.is_set():
            cancelled = True
            break
        if time.monotonic() - start >= duration or read_bytes >= max_bytes:
            break
        try:
            with opener(path) as handle:
                while True:
                    chunk = handle.read(CHUNK)
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    elapsed = time.monotonic() - start
                    if on_progress:
                        progress = (
                            max(elapsed / duration, read_bytes / max_bytes) if duration else 1
                        )
                        on_progress(min(progress, 1.0))
            done_files += 1
        except PermissionError:
            skipped += 1  # файл занят Windows — это не ошибка диска
        except OSError as error:
            read_errors += 1
            error_examples.append(f"{path.name}: {error.strerror or error}")
            log.warning("Ошибка чтения %s: %s", path, error)
        if cancelled:
            break

    elapsed = time.monotonic() - start
    metrics: dict[str, Any] = {
        "read_mb": read_bytes // _MB,
        "speed_mbps": speed_mbps(read_bytes, elapsed),
        "read_errors": read_errors,
        "files": done_files,
        "skipped_files": skipped,
    }
    if cancelled:
        metrics["cancelled"] = True
        return TestResult(
            name=STRESS_DISK_READ,
            status=TestStatus.SKIPPED,
            component="disk",
            duration_s=elapsed,
            metrics=metrics,
            notes=["Тест остановлен пользователем."],
        )
    result = TestResult(
        name=STRESS_DISK_READ, component="disk", duration_s=elapsed, metrics=metrics
    )
    if read_errors:
        result.status = TestStatus.FAILED
        result.notes.append(
            "При чтении системного диска были ошибки: " + "; ".join(error_examples[:3])
        )
    elif read_bytes == 0:
        result.status = TestStatus.SKIPPED
        result.notes.append("Не нашлось файлов для теста чтения.")
    else:
        result.status = TestStatus.PASSED
    if on_progress:
        on_progress(1.0)
    return result
