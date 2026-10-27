"""Тесты путей программы: всё лежит внутри папки программы, временные файлы удаляются."""

from pathlib import Path

import pytest

from hwcheck import config


def test_all_paths_inside_root(tmp_path: Path) -> None:
    paths = config.get_paths(tmp_path)
    for p in (
        paths.data,
        paths.reports,
        paths.logs,
        paths.history_db,
        paths.listings,
    ):
        assert p.resolve().is_relative_to(tmp_path.resolve()), p


def test_ensure_creates_dirs(tmp_path: Path) -> None:
    paths = config.get_paths(tmp_path)
    paths.ensure()
    assert paths.reports.is_dir()
    assert paths.logs.is_dir()


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HWCHECK_ROOT", str(tmp_path))
    assert config.app_root() == tmp_path.resolve()


def test_dev_root_is_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HWCHECK_ROOT", raising=False)
    root = config.app_root()
    assert (root / "hwcheck" / "config.py").exists()


def test_frozen_root_is_exe_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HWCHECK_ROOT", raising=False)
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(tmp_path / "app.exe"))
    assert config.app_root() == tmp_path.resolve()


def test_temp_dir_removed_after_context() -> None:
    with config.temp_dir() as tmp:
        (tmp / "x.txt").write_text("1")
        assert tmp.exists()
    assert not tmp.exists()


def test_temp_dir_removed_even_on_error() -> None:
    saved: list[Path] = []
    with pytest.raises(RuntimeError), config.temp_dir() as tmp:
        saved.append(tmp)
        raise RuntimeError("boom")
    assert not saved[0].exists()


def test_vendor_inside_release_archive(tmp_path: Path) -> None:
    """18.1: в архиве релиза сторонние программы лежат в _internal/vendor."""
    from hwcheck.config import get_paths

    assert get_paths(tmp_path).vendor == tmp_path / "vendor"
    (tmp_path / "_internal" / "vendor").mkdir(parents=True)
    assert get_paths(tmp_path).vendor == tmp_path / "_internal" / "vendor"
