"""Проанализированное объявление хранится на флешке (`data/listings/current.json`)
и автоматически подставляется в следующую проверку."""

from __future__ import annotations

import logging
from pathlib import Path

from hwcheck.models import ListingClaims

log = logging.getLogger(__name__)


class ListingStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    @property
    def path(self) -> Path:
        return self.folder / "current.json"

    def save(self, claims: ListingClaims) -> Path:
        """Сохраняет объявление. Ошибка записи (флешка только для чтения) → OSError."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path.write_text(claims.to_json(), encoding="utf-8")
        return self.path

    def load(self) -> ListingClaims | None:
        """Текущее объявление; нет файла, нет доступа или файл испорчен → None."""
        try:
            if not self.path.is_file():
                return None
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            log.warning("Файл объявления не читается: %s", type(error).__name__)
            return None
        try:
            claims = ListingClaims.from_json(text)
            claims.to_json()  # проверка, что внутри данные ожидаемых типов
            return claims
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            log.warning("Файл объявления испорчен и будет проигнорирован: %s", error)
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
