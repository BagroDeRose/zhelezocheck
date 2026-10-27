"""Настройка журнала (логов) программы.

Логи пишутся в `data/logs/hwcheck.log` рядом с программой, старые файлы
автоматически сменяются (ротация), чтобы не забить флешку.

Перед записью из сообщения вычищается всё, что похоже на лицензионный ключ
или номер телефона: такие данные в логах хранить нельзя.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from hwcheck.config import AppPaths

__all__ = ["LOG_FILE_NAME", "REDACTED", "RotatingFileHandler", "SecretFilter", "redact"]

LOG_FILE_NAME = "hwcheck.log"
REDACTED = "[скрыто]"
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 5

# Лицензионный ключ: группы по 5 символов base32 через дефис (минимум 4 группы).
_KEY_RE = re.compile(r"\b[A-Z2-7]{5}(?:-[A-Z2-7]{5}){3,}\b", re.IGNORECASE)
# Российские номера телефонов: +7/8, затем 10 цифр с любыми разделителями.
_PHONE_RE = re.compile(r"(?:\+7|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")


def redact(text: str) -> str:
    """Заменяет похожие на ключи и телефоны фрагменты на «[скрыто]»."""
    text = _KEY_RE.sub(REDACTED, text)
    return _PHONE_RE.sub(REDACTED, text)


class SecretFilter(logging.Filter):
    """Фильтр логов: вычищает секреты из сообщения и текста исключения."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info:
            # Форматируем исключение заранее, чтобы вычистить секреты и из него.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def setup_logging(paths: AppPaths, level: int = logging.INFO) -> logging.Handler:
    """Подключает запись логов в файл с ротацией. Возвращает созданный обработчик."""
    handler: logging.Handler
    try:
        paths.logs.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            paths.logs / LOG_FILE_NAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        # Флешка защищена от записи — работаем без журнала, но не падаем.
        handler = logging.NullHandler()
    # [номер процесса] — чтобы в общем журнале на флешке различать копии программы (20.3).
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s")
    )
    handler.addFilter(SecretFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)
    return handler
