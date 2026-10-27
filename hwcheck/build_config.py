r"""Настройки сборки, которые не являются порогами: ссылка на скачивание и контакты автора.

Файл `hwcheck/data/build_config.json` задаёт постоянную ссылку на последнюю версию (публичная
страница GitHub) и публичные контакты автора для раздела «Настройки → Контактная информация»
(ссылки открываются только по нажатию пользователя). Программа ничего не загружает из интернета.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from hwcheck.config import package_data_dir

log = logging.getLogger(__name__)

DEFAULT_DOWNLOAD = "https://github.com/BagroDeRose/zhelezocheck/releases/latest"


@dataclass(frozen=True)
class BuildConfig:
    # Контакты автора для «Настройки → Контактная информация» (SPEC 1.2, 22.1).
    contact_telegram: str = ""
    contact_email: str = ""
    contact_github: str = ""
    feedback_form_url: str = ""
    # Постоянная ссылка на последнюю версию: публичная страница релизов на GitHub.
    download_latest: str = DEFAULT_DOWNLOAD


def load_build_config() -> BuildConfig:
    try:
        data = json.loads((package_data_dir() / "build_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("build_config.json не прочитан — используются значения по умолчанию")
        return BuildConfig()
    contacts = data.get("contacts") or {}
    if not isinstance(contacts, dict):
        contacts = {}
    return BuildConfig(
        contact_telegram=str(contacts.get("telegram") or ""),
        contact_email=str(contacts.get("email") or ""),
        contact_github=str(contacts.get("github") or ""),
        feedback_form_url=str(contacts.get("feedback_form_url") or ""),
        download_latest=str(data.get("download_latest") or DEFAULT_DOWNLOAD),
    )
