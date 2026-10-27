"""Объявление из вставленного текста (SPEC 1.3, задача 25.4): без браузера, только Python."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from hwcheck.listing.analyze import analyze_page, analyze_text, apply_market_text
from hwcheck.listing.extract import has_data
from hwcheck.listing.text import claims_from_text, market_from_text, normalize_lines

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "avito"

SHORT = """Видеокарта RTX 3060 12GB MSI Ventus
25 000 ₽
Состояние: Б/у
Продаю видеокарту, использовалась для игр. В майнинге не была.
Есть ещё 3 штуки.
На Авито с марта 2025
"""


def test_short_paste_is_parsed() -> None:
    claims = analyze_text(SHORT)
    assert claims.title == "Видеокарта RTX 3060 12GB MSI Ventus"
    assert claims.price_rub == 25000
    assert claims.params == {"Состояние": "Б/у"}
    assert claims.gpu_model == "GeForce RTX 3060" and claims.gpu_vram_gb == 12
    assert claims.seller_since == "марта 2025"
    assert "использовалась для игр" in claims.description
    ids = {finding.id for finding in claims.flags}
    assert "listing.many_same" in ids
    assert "listing.mining" not in ids  # «в майнинге не была» — отрицание


def test_installments_are_not_the_price() -> None:
    claims = claims_from_text("Ryzen 5 5600\n2 500 ₽ × 4 платежа\nЦена: 10 000 руб.\n")
    assert claims.price_rub == 10000 and claims.cpu_model == "Ryzen 5 5600"


def test_split_lines_are_joined() -> None:
    lines = normalize_lines("115 000\n₽\nСостояние\n:\nБ/у\n")
    assert lines == ["115 000 ₽", "Состояние: Б/у"]


def test_empty_text_has_no_data() -> None:
    assert not has_data(analyze_text("   \n\n"))


def _page_copy(name: str) -> str:
    """Текст страницы, как при Ctrl+A → Ctrl+C в браузере (меню, крошки, похожие)."""
    soup = BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    return soup.get_text("\n")


REAL = {
    "real_gpu_rtx3090.html": {"price_rub": 115000, "gpu_model": "GeForce RTX 3090"},
    "real_gpu_rtx4080.html": {"price_rub": 120000, "gpu_model": "GeForce RTX 4080"},
    "real_gpu_tesla_p100.html": {"price_rub": 11920, "gpu_model": ""},  # нет в справочнике
    "real_cpu_ryzen5600_new.html": {"price_rub": 10190, "cpu_model": "Ryzen 5 5600"},
    "real_cpu_ryzen5600_oem.html": {"price_rub": 9990, "cpu_model": "Ryzen 5 5600"},
    "real_ram_xpg_32gb.html": {"price_rub": 44970, "ram_gb": 32.0},
    "real_ram_ddr5_2x8gb.html": {"price_rub": 26000, "ram_gb": 16.0},
}


@pytest.mark.parametrize(("name", "expected"), REAL.items())
def test_full_page_copy_of_real_listing(name: str, expected: dict[str, object]) -> None:
    claims = analyze_text(_page_copy(name))
    html_claims = analyze_page((FIXTURES / name).read_text(encoding="utf-8"), "https://avito.ru/x")
    assert claims.title == html_claims.title  # заголовок, а не меню или «похожие»
    for field, value in expected.items():
        assert getattr(claims, field) == value, field
    assert {f.id for f in claims.flags} == {f.id for f in html_claims.flags}


SEARCH = """Результаты поиска
Видеокарта RTX 3060 12GB
24 000 ₽
RTX 3060 Gaming X
26 000 ₽
RTX 3060 на запчасти
3 000 ₽
RTX 3070 8GB
35 000 ₽
Доставка 500 ₽
GeForce RTX 3060 12 ГБ
25 000 ₽
RTX 3060 Ti
30 000 ₽
"""


def test_market_from_search_text() -> None:
    market = market_from_text(SEARCH, "GeForce RTX 3060")
    # Другие модели (3070, 3060 Ti) и доставка не в счёт; «на запчасти» — выброс.
    assert market.median == 25000 and market.count == 3 and market.outliers == 1


def test_apply_market_text_updates_claims() -> None:
    claims = analyze_text(SHORT)
    market = apply_market_text(claims, SEARCH)
    assert claims.market_median_rub == market.median == 25000
    assert claims.market_count == 3


def test_market_needs_model() -> None:
    assert market_from_text(SEARCH, "").median is None


def test_title_with_colon_and_price_before_description() -> None:
    """Заголовок вида «Игровой ПК: RTX 3070, …» — заголовок, а не характеристика."""
    claims = claims_from_text(
        "Игровой ПК: RTX 3070 8GB, Ryzen 5 5600, 32 ГБ ОЗУ\n65 000 ₽\nСостояние: Б/у\n"
        "Видеокарта полгода работала в майнинге.\n"
    )
    assert claims.title.startswith("Игровой ПК: RTX 3070")
    assert claims.price_rub == 65000 and claims.params == {"Состояние": "Б/у"}
    assert claims.gpu_model == "GeForce RTX 3070" and claims.cpu_model == "Ryzen 5 5600"
    assert claims.ram_gb == 32


def test_price_before_title_is_used_when_nothing_after() -> None:
    claims = claims_from_text("45 000 ₽\nRTX 3060 12GB в хорошем состоянии\n")
    assert claims.price_rub == 45000
