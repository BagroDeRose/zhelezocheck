"""Сохранённая страница объявления: адрес, с которого её сохранили (задачи 15.13, 22.2).

Порядок поиска:
1. `<link rel="canonical" href="…">` — постоянный адрес объявления (атрибуты в любом порядке);
2. `<meta property="og:url" content="…">`;
3. пометка браузера `<!-- saved from url=(…)… -->` (там бывают метки отслеживания).
Метки после «?» и «#» отбрасываются: для разбора нужен только адрес объявления.
"""

from __future__ import annotations

import re

_TAG = re.compile(r"<(?:link|meta)\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
_SAVED_FROM = re.compile(r"saved from url=\(\d+\)(https?://[^\s>]+)", re.IGNORECASE)


def _attributes(tag: str) -> dict[str, str]:
    return {name.lower(): value for name, value in _ATTR.findall(tag)}


def _clean(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0]


def saved_page_url(html: str, fallback: str) -> str:
    """Адрес объявления, с которого сохранена страница (или `fallback`)."""
    canonical = og_url = ""
    for tag in _TAG.findall(html[:300_000]):  # теги адреса — в начале страницы
        attrs = _attributes(tag)
        if attrs.get("rel", "").lower() == "canonical" and attrs.get("href", "").startswith("http"):
            canonical = canonical or attrs["href"]
        if attrs.get("property", "").lower() == "og:url" and attrs.get("content", "").startswith(
            "http"
        ):
            og_url = og_url or attrs["content"]
    saved = _SAVED_FROM.search(html)
    for candidate in (canonical, og_url, saved.group(1) if saved else ""):
        if candidate:
            return _clean(candidate)
    return fallback
