"""Анализ объявления целиком: извлечь данные → найти тревожные признаки → (рынок) →
находки для вердикта вместе со сверкой с реальным железом.

Источники (SPEC 1.3, 25.4): вставленный текст (основной способ) и файл сохранённой
страницы .html. Встроенного браузера больше нет."""

from __future__ import annotations

from hwcheck.listing.extract import extract
from hwcheck.listing.flags import FlagResult, find_flags
from hwcheck.listing.match import match_listing
from hwcheck.listing.price import MarketPrice, market_for_model, search_items
from hwcheck.listing.text import claims_from_text, market_from_text
from hwcheck.models import HardwareSnapshot, ListingClaims


def refresh_flags(claims: ListingClaims) -> None:
    """Пересчитывает тревожные признаки (например, после того как узнали рыночную цену)."""
    claims.flags = [finding for finding, _ in find_flags(claims, claims.market_median_rub)]


def analyze_page(html: str, url: str) -> ListingClaims:
    """Разбирает страницу объявления, открытую пользователем."""
    claims = extract(html, url)
    refresh_flags(claims)
    return claims


def analyze_text(text: str) -> ListingClaims:
    """Разбирает текст объявления, вставленный пользователем."""
    claims = claims_from_text(text)
    refresh_flags(claims)
    return claims


def apply_market_text(claims: ListingClaims, search_text: str) -> MarketPrice:
    """Рынок по тексту страницы поиска (вставленному пользователем)."""
    market = market_from_text(search_text, claims.gpu_model)
    claims.market_median_rub = market.median
    claims.market_count = market.count
    refresh_flags(claims)
    return market


def apply_market(claims: ListingClaims, search_html: str, search_url: str) -> MarketPrice:
    """Считает рынок по странице поиска для модели из объявления и сохраняет медиану."""
    market = market_for_model(search_items(search_html, search_url), claims.gpu_model)
    claims.market_median_rub = market.median
    claims.market_count = market.count
    refresh_flags(claims)
    return market


def listing_findings(claims: ListingClaims, snapshot: HardwareSnapshot) -> list[FlagResult]:
    """Все находки по объявлению: тревожные признаки и сверка с железом."""
    return find_flags(claims, claims.market_median_rub) + match_listing(claims, snapshot)
