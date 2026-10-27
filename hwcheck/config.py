"""Пути программы: где лежат данные, отчёты, логи, история и лицензия.

Программа портативная: всё пишется только в папку `data/` рядом с программой
(на флешке). В `%APPDATA%` ничего не сохраняем. Временные файлы создаются
через `temp_dir()` и гарантированно удаляются после использования.

Корень программы:
- в собранной версии (PyInstaller) — папка с exe;
- при разработке — корень репозитория;
- переменная окружения `HWCHECK_ROOT` переопределяет корень (нужно для тестов).
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT_ENV_VAR = "HWCHECK_ROOT"


def app_root() -> Path:
    """Возвращает корень программы (см. описание модуля)."""
    override = os.environ.get(ROOT_ENV_VAR)
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def package_data_dir() -> Path:
    """Папка со справочными данными внутри пакета (`hwcheck/data`), только для чтения."""
    return Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class AppPaths:
    """Набор путей программы относительно её корня."""

    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def reports(self) -> Path:
        return self.data / "reports"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def history_db(self) -> Path:
        return self.data / "history.sqlite"

    @property
    def listings(self) -> Path:
        return self.data / "listings"

    @property
    def settings_file(self) -> Path:
        return self.data / "settings.json"

    @property
    def vendor(self) -> Path:
        """Сторонние программы: в релизе — `_internal/vendor`, при разработке — `vendor`."""
        bundled = self.root / "_internal" / "vendor"
        return bundled if bundled.is_dir() else self.root / "vendor"

    def ensure(self) -> bool:
        """Создаёт папки данных, если их ещё нет. False — записать нельзя
        (флешка защищена от записи или переполнена): программа работает без сохранения."""
        try:
            for folder in (self.data, self.reports, self.logs, self.listings):
                folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return True


def get_paths(root: Path | None = None) -> AppPaths:
    """Возвращает пути программы. Без аргумента — относительно `app_root()`."""
    return AppPaths(root=(root or app_root()).resolve())


@contextmanager
def temp_dir(prefix: str = "hwcheck_") -> Iterator[Path]:
    """Временная папка, которая удаляется после выхода из блока `with` (даже при ошибке)."""
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as name:
        yield Path(name)
