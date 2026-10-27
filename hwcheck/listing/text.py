"""Разбор объявления из вставленного текста (SPEC 1.3, задача 25.4).

Основной способ «Проверки объявления»: пользователь копирует в любом браузере название,
цену и описание объявления (или всю страницу — Ctrl+A, Ctrl+C) и вставляет сюда. Разбор —
обычный Python, без встроенного браузера: не зависит от вёрстки сайта и его защиты.

Что извлекается:
- заголовок — первая строка, где упомянуто железо (модель видеокарты, процессор, память);
  если такой нет — первая содержательная строка. Так меню сайта в копии всей страницы
  не принимается за заголовок;
- цена — первое «45 000 ₽» / «45000 руб.» после заголовка (платежи рассрочки не в счёт);
- характеристики — строки вида «Ключ: значение»;
- продавец — «На Авито с …», «N объявлений»;
- всё остальное — описание.
Затем распознаётся заявленное железо и ищутся тревожные признаки — как и раньше.

Цена на рынке — по тексту страницы поиска: каждая цена относится к ближайшему выше
названию видеокарты; учитываются только объявления той же модели.
"""

from __future__ import annotations

import re
from datetime import datetime

from hwcheck.knowledge.gpu_db import find_in_text
from hwcheck.listing.extract import cpu_in_text, parse_price, recognize_hardware
from hwcheck.listing.price import MarketPrice, market_from_prices
from hwcheck.models import ListingClaims

MAX_TEXT_CHARS = 200_000  # вставка больше — это уже не объявление
TITLE_MAX_CHARS = 150

_PRICE_RE = re.compile(r"(\d[\d ]{0,12}\d|\d)\s*(?:₽|руб\.?|р\.)", re.IGNORECASE)
_PARAM_RE = re.compile(r"^([^:]{2,40}):\s*(.{1,200})$")
_SELLER_SINCE_RE = re.compile(r"на\s+\S+\s+с\s+(.+)$|с\s+нами\s+с\s+(.+)$", re.IGNORECASE)
_SELLER_LISTINGS_RE = re.compile(r"(\d+)\s+(?:активн\w+\s+)?объявлен", re.IGNORECASE)
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
        if since := _SELLER_SINCE_RE.search(line):
            claims.seller_since = (since.group(1) or since.group(2) or "").strip()
            continue
        if (listings := _SELLER_LISTINGS_RE.search(line)) and len(line) < 40:
            claims.seller_listings = int(listings.group(1))
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


def market_from_text(text: str, model: str) -> MarketPrice:
    """Цена на рынке по тексту страницы поиска для модели `model` (из справочника).

    Каждая цена относится к ближайшему выше названию видеокарты; объявления других
    моделей и строки без названия не учитываются. Выбросы отбрасываются, как и раньше.
    """
    if not model:
        return MarketPrice()
    prices: list[int] = []
    current = ""
    for raw in (text or "")[:MAX_TEXT_CHARS].splitlines():
        line = _clean(raw)
        if not line:
            continue
        card = find_in_text(line)
        if card is not None:
            current = card.model
        if (match := _PRICE_RE.search(line)) and current:
            value = parse_price(match.group(1))
            if value and current == model:
                prices.append(value)
            current = ""  # цена «закрывает» карточку объявления
    return market_from_prices(prices)
