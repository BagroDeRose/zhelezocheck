"""Тесты рыночной цены по странице поиска: фильтр по модели, выбросы, медиана."""

import pytest

from hwcheck.listing import price
from tests.helpers import fixture_text

SEARCH = "https://www.avito.ru/moskva?q=rtx+3060"


def test_search_items_extracted() -> None:
    items = price.search_items(fixture_text("avito", "search_rtx3060.html"), SEARCH)
    assert len(items) == 11
    assert items[0] == ("MSI RTX 3060 Ventus 12GB", 24000)


def test_market_for_model_filters_other_models_and_outliers() -> None:
    items = price.search_items(fixture_text("avito", "search_rtx3060.html"), SEARCH)
    market = price.market_for_model(items, "GeForce RTX 3060")
    assert market.count == 6  # без Ti, 3070, кулера и двух выбросов
    assert market.outliers == 2  # 3 000 ₽ «на запчасти» и 75 000 ₽
    assert market.median == 23500
    assert (market.low, market.high) == (21000, 25000)


def test_median_and_outliers() -> None:
    market = price.market_from_prices([100, 10000, 10500, 11000, 12000, 50000])
    assert market.median == 10750
    assert market.outliers == 2


def test_too_few_prices() -> None:
    market = price.market_from_prices([10000])
    assert market.count == 1 and market.median == 10000
    assert price.market_from_prices([]).median is None


def test_unknown_model_uses_nothing() -> None:
    items = [("RTX 3060", 20000)]
    assert price.market_for_model(items, "").count == 0


@pytest.mark.parametrize("model", ["GeForce RTX 3070"])
def test_other_model(model: str) -> None:
    items = price.search_items(fixture_text("avito", "search_rtx3060.html"), SEARCH)
    assert price.market_for_model(items, model).median == 30000
