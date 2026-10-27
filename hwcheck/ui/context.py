"""Общие объекты интерфейса: бэкенд, пути, настройки, история.

Страницы получают этот контекст и не создают такие объекты сами — так их легко
подменять в тестах. Программа бесплатная и открытая: все функции доступны всем,
никаких ключей и разделения Free/Pro больше нет (версия 2.0).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from hwcheck.backends.base import HardwareBackend
from hwcheck.config import AppPaths
from hwcheck.models import Finding
from hwcheck.platform.elevation import is_admin, relaunch_elevated
from hwcheck.storage.history import History
from hwcheck.storage.listings import ListingStore
from hwcheck.storage.settings import Settings, load_settings, save_settings


def open_url_with_system(url: str) -> None:
    """Открывает ссылку в браузере по умолчанию — только по нажатию пользователя."""
    QDesktopServices.openUrl(QUrl(url))


def open_with_system(path: Path) -> None:
    """Открывает файл программой по умолчанию (браузер для HTML, просмотрщик для PDF)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


@dataclass
class AppContext:
    backend: HardwareBackend
    paths: AppPaths
    demo_scenario: str = ""
    read_only: bool = False  # в папку программы нельзя писать (флешка защищена от записи)
    admin_check: Callable[[], bool] = is_admin
    relaunch: Callable[[], bool] = relaunch_elevated
    open_path: Callable[[Path], None] = open_with_system
    open_url: Callable[[str], None] = open_url_with_system
    settings: Settings = field(default_factory=Settings)
    # Результаты ручных проверок ноутбука: «screen»/«keyboard» → (находка, аргумент для торга).
    manual_findings: dict[str, tuple[Finding, str | None]] = field(default_factory=dict)
    _history: History | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        backend: HardwareBackend,
        paths: AppPaths,
        demo_scenario: str = "",
    ) -> AppContext:
        writable = paths.ensure()
        return cls(
            backend=backend,
            paths=paths,
            demo_scenario=demo_scenario,
            settings=load_settings(paths.settings_file),
            read_only=not writable,
        )

    @property
    def is_demo(self) -> bool:
        """Запущен демо-сценарий (`--demo`): данные из образца, а не с реального железа."""
        return bool(self.demo_scenario)

    @property
    def history(self) -> History:
        if self._history is None:
            self._history = History(self.paths.history_db)
        return self._history

    @property
    def listings(self) -> ListingStore:
        return ListingStore(self.paths.listings)

    def save_settings(self) -> None:
        save_settings(self.paths.settings_file, self.settings)
