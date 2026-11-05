"""Настройки программы (тема оформления и т.п.) в `data/settings.json` на флешке."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Settings:
    theme: str = "light"  # light / dark
    # Скрывать имя компьютера и серийные номера в сохранённых отчётах (2.1, этап 48).
    hide_identifiers: bool = True


def load_settings(path: Path) -> Settings:
    """Читает настройки; испорченный или отсутствующий файл → настройки по умолчанию."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    theme = data.get("theme")
    return Settings(
        theme=theme if theme in ("light", "dark") else "light",
        # Старое поле «listing_scripts» (встроенный браузер, удалён) просто не читается.
        hide_identifiers=data.get("hide_identifiers") is not False,  # нет поля — скрывать
    )


def save_settings(path: Path, settings: Settings) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), ensure_ascii=False), encoding="utf-8")
    except OSError as error:  # например, флешка защищена от записи
        log.warning("Не удалось сохранить настройки: %s", error)
