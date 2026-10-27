"""Программа не должна оставлять файлы в профиле пользователя (%APPDATA%, %LOCALAPPDATA%)."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from hwcheck.ui import app as ui_app


@pytest.fixture
def unique_app_name() -> Iterator[str]:
    old = QCoreApplication.applicationName()
    name = f"hwcheck_trace_test_{uuid.uuid4().hex[:8]}"
    QCoreApplication.setApplicationName(name)
    yield name
    QCoreApplication.setApplicationName(old)


def _user_dirs(name: str) -> list[Path]:
    roots = [os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")]
    return [Path(root) / name for root in roots if root]


def test_qt_disk_caches_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ui_app.NO_DISK_CACHE_ENV:
        monkeypatch.delenv(name, raising=False)
    ui_app.configure_qt_environment()
    for name in ui_app.NO_DISK_CACHE_ENV:
        assert os.environ[name] == "1"
