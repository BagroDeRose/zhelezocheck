"""Цена относительно рынка: медиана по странице поиска, которую открыл пользователь.

Берётся ТОЛЬКО текущая страница поиска — программа сама не листает страницы и ничего
не скачивает. Из карточек оставляются объявления той же модели (название приводится
к модели справочника видеокарт), затем отбрасываются выбросы — «на запчасти» за копейки
и «новая в упаковке» втридорога — по правилу межквартильного размаха (Тьюки).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from bs4 import BeautifulSoup

from hwcheck.knowledge.gpu_db import find_in_text
from hwcheck.listing.extract import detect_site, load_selectors, parse_price, select_value

SearchItem = tuple[str, int]  # название, цена в рублях


@dataclass
class MarketPrice:
    """Итог по рынку: медиана и разброс без выбросов."""

    median: int | None = None
    low: int | None = None
    high: int | None = None
    count: int = 0
    outliers: int = 0


def search_items(html: str, url: str) -> list[SearchItem]:
    """Карточки объявлений со страницы поиска: (название, цена). Без цены — пропускаются."""
    selectors = load_selectors()[detect_site(url)]["search"]
    soup = BeautifulSoup(html or "", "html.parser")
    items: list[SearchItem] = []
    for card in soup.select(selectors["card"]):
        title = select_value(card, selectors.get("card_title", []))
        value = parse_price(select_value(card, selectors.get("card_price", [])))
        if title and value:
            items.append((title, value))
    return items


def market_from_prices(prices: list[int]) -> MarketPrice:
    """Медиана и разброс после отбрасывания выбросов (1,5 межквартильного размаха)."""
    if not prices:
        return MarketPrice()
    kept = sorted(prices)
    if len(kept) >= 4:
        q1, _, q3 = statistics.quantiles(kept, n=4, method="inclusive")
        spread = q3 - q1
        kept = [p for p in kept if q1 - 1.5 * spread <= p <= q3 + 1.5 * spread]
    return MarketPrice(
        median=int(statistics.median(kept)),
        low=kept[0],
        high=kept[-1],
        count=len(kept),
        outliers=len(prices) - len(kept),
    )


def market_for_model(items: list[SearchItem], model: str) -> MarketPrice:
    """Рынок только для объявлений модели `model` (название из справочника видеокарт)."""
    if not model:
        return MarketPrice()
    prices = []
    for title, value in items:
        card = find_in_text(title)
        if card is not None and card.model == model:
            prices.append(value)
    return market_from_prices(prices)
