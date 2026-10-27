"""Тесты чтения диска: только чтение, расчёт скорости, ошибки чтения, отмена."""

import builtins
import threading
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from hwcheck.models import TestStatus
from hwcheck.stress import disk_read


def _make_files(folder: Path, sizes_mb: list[int]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index, size in enumerate(sizes_mb):
        (folder / f"f{index}.dll").write_bytes(b"\x5a" * size * 1024 * 1024)
    (folder / "small.txt").write_bytes(b"tiny")


def test_never_opens_for_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_files(tmp_path / "sys", [2, 1])
    modes: list[str] = []
    real_open = builtins.open

    def spy_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        modes.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    result = disk_read.run_disk_read(30, threading.Event(), roots=[tmp_path / "sys"])
    assert result.status is TestStatus.PASSED
    assert modes and all(mode == "rb" for mode in modes)
    assert result.metrics["read_mb"] == 3
    assert result.metrics["files"] == 2  # маленький файл не берётся


def test_source_has_no_write_modes() -> None:
    source = Path(disk_read.__file__).read_text(encoding="utf-8")
    for mode in ('"wb"', '"ab"', '"w"', '"r+b"', '"a"', "O_WRONLY", "O_RDWR"):
        assert mode not in source


def test_speed_calculation() -> None:
    assert disk_read.speed_mbps(1024 * 1024 * 500, 2.0) == 250.0
    assert disk_read.speed_mbps(100, 0) == 0.0


def test_pick_files_limit(tmp_path: Path) -> None:
    _make_files(tmp_path, [3, 2, 1])
    chosen = disk_read.pick_files([tmp_path, tmp_path / "missing"], max_bytes=4 * 1024 * 1024)
    assert [p.name for p in chosen] == ["f0.dll", "f1.dll"]


class BadDisk:
    """Имитация файла на повреждённом диске: чтение падает с ошибкой ввода-вывода."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "BadDisk":
        return self

    def __exit__(self, *exc: object) -> None: ...

    def read(self, size: int) -> bytes:
        if self.path.name == "f0.dll":
            raise OSError(23, "Ошибка в данных (CRC)")
        return b""


def test_read_error_is_failed(tmp_path: Path) -> None:
    _make_files(tmp_path, [1, 1])

    def opener(path: Path) -> BinaryIO:
        return BadDisk(path)  # type: ignore[return-value]  # утиная типизация для теста

    result = disk_read.run_disk_read(30, threading.Event(), roots=[tmp_path], opener=opener)
    assert result.status is TestStatus.FAILED
    assert result.metrics["read_errors"] == 1
    assert "CRC" in result.notes[0]


def test_locked_file_is_not_disk_error(tmp_path: Path) -> None:
    _make_files(tmp_path, [1])

    def opener(path: Path) -> BinaryIO:
        raise PermissionError("занят")

    result = disk_read.run_disk_read(30, threading.Event(), roots=[tmp_path], opener=opener)
    assert result.metrics["read_errors"] == 0
    assert result.metrics["skipped_files"] == 1


def test_cancel(tmp_path: Path) -> None:
    _make_files(tmp_path, [1])
    cancel = threading.Event()
    cancel.set()
    result = disk_read.run_disk_read(30, cancel, roots=[tmp_path])
    assert result.status is TestStatus.SKIPPED
