"""Объявление из вставленного текста (с 2.1 — необязательное поле на странице режима):
распознаётся только заявленное железо для сверки; цены по рынку, продавца и «тревожных
слов» больше нет."""

import threading
from pathlib import Path

import pytest

from hwcheck.backends.fake import FakeBackend
from hwcheck.listing.recognize import cpu_in_text, parse_price
from hwcheck.listing.text import (
    claims_from_text,
    claims_summary,
    listing_from_text,
    normalize_lines,
)
from hwcheck.report.builder import build_html
from hwcheck.session import run_check

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "listing_text"

SHORT = """Видеокарта RTX 3060 12GB MSI Ventus
25 000 ₽
Состояние: Б/у
Продаю видеокарту, использовалась для игр. В майнинге не была.
"""


def test_short_paste_is_parsed() -> None:
    claims = claims_from_text(SHORT)
    assert claims.title == "Видеокарта RTX 3060 12GB MSI Ventus"
    assert claims.price_rub == 25000
    assert claims.params == {"Состояние": "Б/у"}
    assert claims.gpu_model == "GeForce RTX 3060" and claims.gpu_vram_gb == 12
    assert "использовалась для игр" in claims.description
    assert claims.flags == []  # «тревожных слов» больше нет (2.1)


def test_installments_are_not_the_price() -> None:
    claims = claims_from_text("Ryzen 5 5600\n2 500 ₽ × 4 платежа\nЦена: 10 000 руб.\n")
    assert claims.price_rub == 10000 and claims.cpu_model == "Ryzen 5 5600"


def test_split_lines_are_joined() -> None:
    lines = normalize_lines("115 000\n₽\nСостояние\n:\nБ/у\n")
    assert lines == ["115 000 ₽", "Состояние: Б/у"]


@pytest.mark.parametrize("text", ["", "   \n\n", "Продаю компьютер, звоните.\n"])
def test_nothing_to_compare_gives_none(text: str) -> None:
    assert listing_from_text(text) is None


REAL = {
    "real_gpu_rtx3090": {"price_rub": 115000, "gpu_model": "GeForce RTX 3090"},
    "real_gpu_rtx4080": {"price_rub": 120000, "gpu_model": "GeForce RTX 4080"},
    "real_gpu_tesla_p100": {"price_rub": 11920, "gpu_model": ""},  # нет в справочнике
    "real_cpu_ryzen5600_new": {"price_rub": 10190, "cpu_model": "Ryzen 5 5600"},
    "real_cpu_ryzen5600_oem": {"price_rub": 9990, "cpu_model": "Ryzen 5 5600"},
    "real_ram_xpg_32gb": {"price_rub": 44970, "ram_gb": 32.0},
    "real_ram_ddr5_2x8gb": {"price_rub": 26000, "ram_gb": 16.0},
    "item_pc_gaming": {
        "price_rub": 58000,
        "gpu_model": "GeForce RTX 3060",
        "gpu_vram_gb": 12.0,
        "cpu_model": "Ryzen 5 5600",
        "ram_gb": 32.0,
    },
    "item_gpu_rtx3060": {"price_rub": 23500, "gpu_model": "GeForce RTX 3060"},
}


@pytest.mark.parametrize(("name", "expected"), REAL.items())
def test_full_page_copy_of_real_listing(name: str, expected: dict[str, object]) -> None:
    """Копия всей страницы (меню, крошки, похожие объявления) — распознаётся заявленное."""
    claims = claims_from_text((FIXTURES / f"{name}.txt").read_text(encoding="utf-8"))
    for field, value in expected.items():
        assert getattr(claims, field) == value, field


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


def test_summary_line() -> None:
    claims = listing_from_text("Игровой ПК: RTX 3070 8GB, Ryzen 5 5600, 32 ГБ ОЗУ\n")
    assert claims_summary(claims) == "GeForce RTX 3070 8 ГБ · Ryzen 5 5600 · ОЗУ 32 ГБ"
    assert claims_summary(None) == ""


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
    assert cpu_in_text(text) == cpu


@pytest.mark.parametrize(
    ("text", "price"),
    [
        ("23 500 ₽", 23500),
        ("23500.00", 23500),
        ("", None),
        ("договорная", None),
        ("9" * 400, None),
        ("2 000 000 000 ₽", None),  # больше разумного предела
        ("950 000 ₽", 950000),
    ],
)
def test_parse_price(text: str, price: int | None) -> None:
    assert parse_price(text) == price


def test_listing_enters_verdict_and_report() -> None:
    """Сверка попадает в вердикт и отчёт; «тревожных слов» среди находок нет."""
    claims = listing_from_text(
        "RTX 3070 8gb после майнинга\n19 000 ₽\nТолько предоплата, не проверял.\n"
    )
    assert claims is not None
    session = run_check(FakeBackend("mining_gpu"), "quick", threading.Event(), listing=claims)
    assert session.listing == claims and session.verdict is not None
    ids = {f.id for f in session.verdict.findings if f.id.startswith("listing.")}
    assert ids == {"listing.gpu_match"}
    html = build_html(session)
    assert "Объявление" in html and "RTX 3070 8gb после майнинга" in html
    assert "19 000" in html


def test_listing_ram_claim_checked() -> None:
    claims = listing_from_text("Игровой ПК: RTX 3060 12GB, Ryzen 5 5600, 64 ГБ ОЗУ\n")
    assert claims is not None and claims.ram_gb == 64
    session = run_check(
        FakeBackend("healthy_gaming_pc"), "quick", threading.Event(), listing=claims
    )
    assert session.verdict is not None
    assert "ram.less_than_claimed" in {f.id for f in session.verdict.findings}


def test_listing_mismatch_is_the_main_reason() -> None:
    """Ручная проверка rc3: «УХОДИТЬ — Найдены серьёзные неисправности», а в «Главных
    причинах» — только «к сведению»; настоящая причина (не та видеокарта) была ниже."""
    from hwcheck.report.buyer import buyer_context

    claims = listing_from_text("Intel Core i5-9400f\nNVIDIA GeForce RTX 2060\n")
    assert claims is not None
    session = run_check(
        FakeBackend("healthy_gaming_pc"), "quick", threading.Event(), listing=claims
    )
    assert session.verdict is not None
    assert session.verdict.summary == "Компьютер не соответствует объявлению."
    buyer = buyer_context(session)
    assert buyer["reasons"][0]["title"].startswith("Заявлена GeForce RTX 2060")
    mismatch = next(f for f in session.verdict.findings if f.id == "listing.gpu_mismatch")
    assert "Заявлено: GeForce RTX 2060" in mismatch.evidence
    assert "GeForce RTX 3060" in mismatch.evidence  # что найдено на самом деле


def test_real_fault_keeps_fault_summary() -> None:
    """Если есть настоящая неисправность, итог говорит о ней, даже при несовпадении."""
    claims = listing_from_text("RTX 3080 10GB\n")
    assert claims is not None
    session = run_check(FakeBackend("dying_hdd"), "quick", threading.Event(), listing=claims)
    assert session.verdict is not None
    assert session.verdict.summary == "Найдены серьёзные неисправности."
