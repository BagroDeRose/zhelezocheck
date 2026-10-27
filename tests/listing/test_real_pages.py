"""Разбор настоящих сохранённых страниц Авито (обезличены, задача 22.2)."""

from pathlib import Path

import pytest

from hwcheck.listing.analyze import analyze_page
from hwcheck.ui.pages.listing import saved_page_url

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "avito"

CASES = {
    "real_gpu_rtx3090.html": {"price_rub": 115000, "gpu_model": "GeForce RTX 3090"},
    "real_gpu_rtx4080.html": {"price_rub": 120000, "gpu_model": "GeForce RTX 4080"},
    "real_gpu_tesla_p100.html": {"price_rub": 11920},
    "real_cpu_ryzen5600_new.html": {"price_rub": 10190, "cpu_model": "Ryzen 5 5600"},
    "real_cpu_ryzen5600_oem.html": {"price_rub": 9990, "cpu_model": "Ryzen 5 5600"},
    "real_ram_xpg_32gb.html": {"price_rub": 44970, "ram_gb": 32.0},
    "real_ram_ddr5_2x8gb.html": {"price_rub": 26000, "ram_gb": 16.0},
}


@pytest.mark.parametrize(("name", "expected"), CASES.items())
def test_real_page(name: str, expected: dict[str, object]) -> None:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    url = saved_page_url(html, "file:///x")
    claims = analyze_page(html, url)
    assert claims.site == "avito" and claims.title
    assert url.startswith("https://www.avito.ru/") and "?" not in url  # без меток отслеживания
    for field, value in expected.items():
        assert getattr(claims, field) == value, field


def test_real_pages_have_no_seller_data() -> None:
    for path in FIXTURES.glob("real_*.html"):
        text = path.read_text(encoding="utf-8")
        assert "/user/" not in text and "/brands/" not in text, path.name
        assert "<script" not in text.lower(), path.name


def test_saved_from_comment_and_canonical_any_attribute_order() -> None:
    html = '<link data-rh="true" href="https://www.avito.ru/a/b_1" rel="canonical"/>'
    assert saved_page_url(html, "f") == "https://www.avito.ru/a/b_1"
    meta = '<meta content="https://www.avito.ru/a/c_2" property="og:url"/>'
    assert saved_page_url(meta, "f") == "https://www.avito.ru/a/c_2"
    comment = "<!-- saved from url=(0040)https://www.avito.ru/a/d_3?context=xyz -->"
    assert saved_page_url(comment, "f") == "https://www.avito.ru/a/d_3"


def test_ram_kit_from_params_without_title_hint() -> None:
    """Объём комплекта берётся из параметров, даже если в заголовке объёма нет."""
    from hwcheck.listing.extract import ram_in_claims
    from hwcheck.models import ListingClaims

    claims = ListingClaims(
        title="Память Kingston Fury",
        params={"Объём одного модуля, ГБ": "8", "Количество модулей в комплекте": "4"},
    )
    assert ram_in_claims(claims) == 32.0
