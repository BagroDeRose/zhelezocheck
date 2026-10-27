"""Тесты извлечения данных объявления на синтетических HTML-фикстурах."""

import pytest

from hwcheck.listing import extract
from hwcheck.models import ListingClaims
from tests.helpers import fixture_text

AVITO = "https://www.avito.ru/moskva/tovary_dlya_kompyutera/videokarta_1234567890"


def _item(name: str, url: str = AVITO) -> ListingClaims:
    return extract.extract(fixture_text("avito", name), url)


def test_gpu_listing_fields() -> None:
    claims = _item("item_gpu_rtx3060.html")
    assert claims.site == "avito"
    assert claims.title == "Видеокарта MSI GeForce RTX 3060 Ventus 2X 12G"
    assert claims.price_rub == 23500
    assert "Майнингом не занимался" in claims.description
    assert claims.params["Объём видеопамяти"] == "12 ГБ"
    assert claims.params["Производитель"] == "MSI"
    assert claims.seller_name == "Игорь"
    assert claims.seller_since == "На Авито с марта 2019"
    assert claims.seller_listings == 3
    assert claims.city == "Москва, м. Тёплый Стан"
    assert claims.gpu_model == "GeForce RTX 3060"
    assert claims.gpu_vram_gb == 12
    assert claims.analyzed_at


def test_mining_listing() -> None:
    claims = _item("item_gpu_mining.html")
    assert claims.price_rub == 19000
    assert claims.gpu_model == "GeForce RTX 3070"
    assert claims.gpu_vram_gb == 8
    assert claims.seller_listings == 48
    assert claims.params == {}


def test_pc_listing_recognizes_cpu_ram_gpu() -> None:
    claims = _item("item_pc_gaming.html")
    assert claims.gpu_model == "GeForce RTX 3060"
    assert claims.gpu_vram_gb == 12
    assert claims.cpu_model == "Ryzen 5 5600"
    assert claims.ram_gb == 32
    assert claims.price_rub == 58000


def test_generic_site_uses_open_graph() -> None:
    claims = _item("item_minimal_og.html", url="https://shop.example.com/p/1")
    assert claims.site == "generic"
    assert claims.title == "Radeon RX 580 8GB"
    assert "на запчасти" in claims.description
    assert claims.price_rub is None
    assert claims.gpu_model == "Radeon RX 580"
    assert claims.seller_name == ""


def test_missing_fields_do_not_crash() -> None:
    claims = extract.extract("<html><body><p>пусто</p></body></html>", AVITO)
    assert claims.title == "" and claims.price_rub is None and claims.params == {}
    assert not extract.has_data(claims)
    assert not extract.has_data(extract.extract("", AVITO))


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.avito.ru/x", "avito"),
        ("https://m.avito.ru/x", "avito"),
        ("https://avito.ru.evil.com/x", "generic"),
        ("https://example.com/", "generic"),
    ],
)
def test_detect_site(url: str, site: str) -> None:
    assert extract.detect_site(url) == site


@pytest.mark.parametrize(
    ("text", "cpu"),
    [
        ("Intel Core i5-12400F", "i5-12400F"),
        ("i7 8700k", "i7-8700K"),
        ("AMD Ryzen 7 5800X3D", "Ryzen 7 5800X3D"),
        ("ryzen5 3600", "Ryzen 5 3600"),
        ("без процессора", ""),
    ],
)
def test_cpu_in_text(text: str, cpu: str) -> None:
    assert extract.cpu_in_text(text) == cpu


@pytest.mark.parametrize(
    ("text", "price"), [("23 500 ₽", 23500), ("23500.00", 23500), ("", None), ("договорная", None)]
)
def test_parse_price(text: str, price: int | None) -> None:
    assert extract.parse_price(text) == price


def test_selectors_file_has_both_sites() -> None:
    sites = extract.load_selectors()
    assert {"avito", "generic"} <= set(sites)


def test_absurd_price_from_hostile_page() -> None:
    assert extract.parse_price("9" * 400) is None
    assert extract.parse_price("9" * 12) is None
    assert extract.parse_price("2 000 000 000 ₽") is None  # больше разумного предела
    assert extract.parse_price("950 000 ₽") == 950000
