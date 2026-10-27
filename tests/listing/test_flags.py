"""Тесты тревожных признаков объявления."""

from datetime import date

import pytest

from hwcheck.listing import flags
from hwcheck.models import ListingClaims


def _ids(text: str) -> set[str]:
    return {f.id for f, _ in flags.text_flags(text)}


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("Карты с фермы, работали в риге", "listing.mining"),
        ("Без торга", "listing.no_bargain"),
        ("Только доставка, только предоплата", "listing.prepay_only"),
        ("Не тестировал после покупки", "listing.not_tested"),
        ("После ремонта, перепайка памяти", "listing.repaired"),
        ("Продаю на запчасти, не запускается", "listing.for_parts"),
    ],
)
def test_text_flag_fires(text: str, flag: str) -> None:
    assert flag in _ids(text)


def test_normal_text_has_no_flags() -> None:
    assert (
        _ids("Отличная видеокарта, оригинальная коробка, чек, гарантия. Проверка у меня дома.")
        == set()
    )


def test_negated_mining_is_info() -> None:
    assert _ids("Майнингом не занимался, только игры.") == {"listing.mining.denied"}


def test_numeric_flags() -> None:
    claims = ListingClaims(
        price_rub=10000,
        seller_since="На Авито с сентября 2026",
        seller_listings=48,
        description="Есть ещё 4 такие же",
    )
    ids = {f.id for f, _ in flags.numeric_flags(claims, 24000, today=date(2026, 10, 6))}
    assert ids == {"listing.price_low", "listing.new_seller", "listing.many_same"}
    calm = ListingClaims(price_rub=23000, seller_since="На Авито с марта 2019", seller_listings=3)
    assert flags.numeric_flags(calm, 24000, today=date(2026, 10, 6)) == []


def test_parse_seller_since() -> None:
    assert flags.parse_seller_since("На Авито с марта 2019") == date(2019, 3, 1)
    assert flags.parse_seller_since("На Авито с 2015 года") == date(2015, 1, 1)
    assert flags.parse_seller_since("недавно") is None
