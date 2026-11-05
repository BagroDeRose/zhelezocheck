"""Объявление из вставленного текста (с 2.1 — необязательное поле на экране выбора режима).

Пользователь копирует в любом браузере название, цену и описание объявления (или всю
страницу — Ctrl+A, Ctrl+C) и вставляет в поле «Сверить с объявлением». Разбор — обычный
Python: не зависит от вёрстки сайта и его защиты.

Что извлекается:
- заголовок — первая строка, где упомянуто железо (модель видеокарты, процессор, память);
  если такой нет — первая содержательная строка. Так меню сайта в копии всей страницы
  не принимается за заголовок;
- цена — первое «45 000 ₽» / «45000 руб.» после заголовка (платежи рассрочки не в счёт);
- характеристики — строки вида «Ключ: значение»;
- всё остальное — описание.
Затем распознаётся заявленное железо (`recognize.py`) — его программа сверит с найденным.
Цены по рынку, продавца и «тревожных слов» больше нет (решение владельца, 2.1).
"""

from __future__ import annotations

import re
from datetime import datetime

from hwcheck.knowledge.gpu_db import find_in_text
from hwcheck.listing.recognize import cpu_in_text, has_claims, parse_price, recognize_hardware
from hwcheck.models import ListingClaims

MAX_TEXT_CHARS = 200_000  # вставка больше — это уже не объявление
TITLE_MAX_CHARS = 150

_PRICE_RE = re.compile(r"(\d[\d ]{0,12}\d|\d)\s*(?:₽|руб\.?|р\.)", re.IGNORECASE)
_PARAM_RE = re.compile(r"^([^:]{2,40}):\s*(.{1,200})$")
# Служебные строки сайтов, которые попадают в копию страницы и не являются заголовком.
_SERVICE_RE = re.compile(
    r"^(?:главная|объявления|избранное|войти|вход|разместить|написать|показать телефон|"
    r"купить|доставка|поделиться|пожаловаться|в избранное|сообщения|мои объявления)\b",
    re.IGNORECASE,
)


_INSTALLMENT_RE = re.compile(r"×|платеж|в\s+месяц|/\s*мес", re.IGNORECASE)
_RAM_WORDS_RE = re.compile(r"\b(?:ddr\d|озу|оперативн\w*)", re.IGNORECASE)
_SIZE_RE = re.compile(r"\d+\s*(?:gb|гб)\b", re.IGNORECASE)  # «16Gb», «32 ГБ»
_LONE_CURRENCY = {"₽", "руб.", "руб", "р."}


def _clean(line: str) -> str:
    """Схлопывает пробелы (split() считает пробелом и неразрывный пробел)."""
    return " ".join(line.split())


def normalize_lines(text: str) -> list[str]:
    """Строки текста без пустых; склеивает то, что браузер разбил при копировании:
    «115 000» + «₽» → «115 000 ₽», «Состояние» + «:» + «Б/у» → «Состояние: Б/у»."""
    lines: list[str] = []
    for raw in (text or "")[:MAX_TEXT_CHARS].splitlines():
        line = _clean(raw)
        if not line:
            continue
        if line in _LONE_CURRENCY and lines and re.fullmatch(r"[\d ]+", lines[-1]):
            lines[-1] = f"{lines[-1]} {line}"
        elif line == ":" and lines:
            lines[-1] = f"{lines[-1]}:"
        elif lines and lines[-1].endswith(":") and not _PARAM_RE.match(lines[-1]):
            lines[-1] = f"{lines[-1]} {line}"
        else:
            lines.append(line)
    return lines


def _mentions_hardware(line: str) -> bool:
    return bool(
        find_in_text(line)
        or cpu_in_text(line)
        or _RAM_WORDS_RE.search(line)
        or _SIZE_RE.search(line)
    )


def _main_price(line: str) -> int | None:
    match = _PRICE_RE.search(line)
    if match is None or _INSTALLMENT_RE.search(line):
        return None
    return parse_price(match.group(1))


def _is_title(line: str, allow_param: bool = False) -> bool:
    return (
        bool(re.search(r"[A-Za-zА-Яа-яЁё]{3}", line))
        and len(line) <= TITLE_MAX_CHARS
        and not _PRICE_RE.fullmatch(line)
        and not _SERVICE_RE.match(line)
        and (allow_param or not _PARAM_RE.match(line))
    )


def _title_index(lines: list[str]) -> int | None:
    """Строка заголовка: с железом и цифрами (модель, объём) → с железом → первая подходящая.

    Хлебные крошки сайта («Видеокарты», «Оперативная память») цифр не содержат, а заголовок
    объявления почти всегда содержит модель или объём."""
    candidates = [i for i, line in enumerate(lines) if _is_title(line)]
    with_hardware = [i for i in candidates if _mentions_hardware(lines[i])]
    # Заголовок с двоеточием («Игровой ПК: RTX 3070, 32 ГБ») — тоже заголовок, если в нём
    # железо с цифрами; характеристики в копии страницы идут уже после настоящего заголовка.
    specific = [
        i
        for i, line in enumerate(lines)
        if _is_title(line, allow_param=True) and _mentions_hardware(line) and re.search(r"\d", line)
    ]
    for group in (specific, with_hardware, candidates):
        if group:
            return group[0]
    return None


def claims_from_text(text: str) -> ListingClaims:
    """Объявление из вставленного текста: заголовок, цена, характеристики, описание."""
    lines = normalize_lines(text)
    claims = ListingClaims(site="text", analyzed_at=datetime.now().isoformat(timespec="seconds"))
    title_at = _title_index(lines)
    if title_at is not None:
        claims.title = lines[title_at]
    rest: list[str] = []
    for index, line in enumerate(lines):
        if index == title_at:
            continue
        after_title = title_at is None or index > title_at
        if claims.price_rub is None and after_title and (price := _main_price(line)):
            claims.price_rub = price
            if _PRICE_RE.fullmatch(line):
                continue
        if param := _PARAM_RE.match(line):
            key, value = param.group(1).strip(), param.group(2).strip()
            if key.lower() not in ("http", "https"):
                claims.params[key] = value
                continue
        if any(ch.isalnum() for ch in line):  # строки из одних знаков («---») — не текст
            rest.append(line)
    if claims.price_rub is None:  # цены после заголовка нет — берём первую в тексте
        claims.price_rub = next((p for line in lines if (p := _main_price(line))), None)
    section = _description_section(lines, title_at)
    claims.description = "\n".join(section if section is not None else rest)
    recognize_hardware(claims)
    return claims


_SECTION_END_RE = re.compile(
    r"^(?:№\s*\d|читать полностью|пожаловаться|похожие объявления|задать вопрос продавцу)",
    re.IGNORECASE,
)


def _description_section(lines: list[str], title_at: int | None) -> list[str] | None:
    """Раздел «Описание» из копии всей страницы — без меню и «похожих объявлений».

    None — раздела нет (вставлен только текст объявления): тогда описание — всё остальное."""
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line.lower() == "описание" and (title_at is None or i > title_at)
        ),
        None,
    )
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if _SECTION_END_RE.match(lines[i])), len(lines)
    )
    return lines[start + 1 : end]


def listing_from_text(text: str) -> ListingClaims | None:
    """Объявление для сверки из вставленного текста; None — поле пустое или в тексте не
    распознано ни видеокарты, ни процессора, ни объёма памяти (сверять нечего)."""
    if not text or not text.strip():
        return None
    claims = claims_from_text(text)
    return claims if has_claims(claims) else None


def claims_summary(claims: ListingClaims | None) -> str:
    """Что распознано, одной строкой: «RTX 3070 8 ГБ · Ryzen 5 5600 · ОЗУ 32 ГБ»."""
    if claims is None:
        return ""
    parts = []
    if claims.gpu_model:
        vram = f" {claims.gpu_vram_gb:g} ГБ" if claims.gpu_vram_gb else ""
        parts.append(f"{claims.gpu_model}{vram}")
    if claims.cpu_model:
        parts.append(claims.cpu_model)
    if claims.ram_gb:
        parts.append(f"ОЗУ {claims.ram_gb:g} ГБ")
    return " · ".join(parts)
