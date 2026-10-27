r"""Обезличивание сохранённых страниц объявлений перед добавлением в фикстуры (задача 8.3).

Заменяет имя продавца на «Продавец», вычищает телефоны и ссылки на профиль, удаляет скрипты.
Запуск:  .venv\Scripts\python scripts\anonymize_listing.py tests\fixtures\avito\*.html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SELLER_SELECTORS = [
    '[data-marker="seller-info/name"]',
    '[data-marker="seller-link/link"]',
    '[data-marker="seller-info/avatar"]',
]
PROFILE_RE = re.compile(r"(?:https?://(?:www\.)?avito\.ru)?/(?:user|brands)/[^\"'\s<>]*")
PHONE_RE = re.compile(r"(?:\+7|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")


def anonymize(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all(["script", "noscript", "iframe"]):
        script.decompose()
    for selector in SELLER_SELECTORS:
        for element in soup.select(selector):
            element.string = "Продавец"
            if element.has_attr("href"):
                element["href"] = "#"
    # Ссылки на профиль и магазин продавца (по ним продавца можно найти) — убираем (22.2).
    for link in soup.find_all(href=PROFILE_RE):
        link["href"] = "#"
    text = PROFILE_RE.sub("#", str(soup))
    return PHONE_RE.sub("+7 000 000-00-00", text)


def main(paths: list[str]) -> int:
    for name in paths:
        for path in sorted(Path().glob(name)) if any(c in name for c in "*?") else [Path(name)]:
            path.write_text(
                anonymize(path.read_text(encoding="utf-8", errors="replace")), encoding="utf-8"
            )
            print("обезличено:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
