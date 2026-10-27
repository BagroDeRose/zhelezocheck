"""Связка объявления с проверкой: анализ, сохранение на флешку, учёт в вердикте и отчёте."""

import threading
from pathlib import Path

from hwcheck.backends.fake import FakeBackend
from hwcheck.listing import analyze
from hwcheck.report.builder import build_html
from hwcheck.session import run_check
from hwcheck.storage.listings import ListingStore
from tests.helpers import fixture_text

ITEM = "https://www.avito.ru/kazan/tovary_dlya_kompyutera/rtx_3070_1"
SEARCH = "https://www.avito.ru/rossiya?q=rtx+3060"


def test_analyze_page_fills_flags() -> None:
    claims = analyze.analyze_page(fixture_text("avito", "item_gpu_mining.html"), ITEM)
    ids = {f.id for f in claims.flags}
    assert {"listing.mining", "listing.prepay_only", "listing.not_tested"} <= ids
    assert claims.gpu_model == "GeForce RTX 3070"


def test_store_roundtrip(tmp_path: Path) -> None:
    store = ListingStore(tmp_path / "listings")
    assert store.load() is None
    claims = analyze.analyze_page(fixture_text("avito", "item_gpu_rtx3060.html"), ITEM)
    path = store.save(claims)
    assert path.is_file() and path.parent == tmp_path / "listings"
    assert store.load() == claims
    store.clear()
    assert store.load() is None


def test_broken_store_file_is_ignored(tmp_path: Path) -> None:
    store = ListingStore(tmp_path)
    store.path.write_text("{битый", encoding="utf-8")
    assert store.load() is None


def test_market_price_adds_low_price_flag() -> None:
    claims = analyze.analyze_page(fixture_text("avito", "item_gpu_rtx3060.html"), ITEM)
    claims.price_rub = 12000
    market = analyze.apply_market(claims, fixture_text("avito", "search_rtx3060.html"), SEARCH)
    assert market.median == 23500 and claims.market_median_rub == 23500
    assert claims.market_count == 6
    assert "listing.price_low" in {f.id for f in claims.flags}


def test_listing_enters_verdict_and_report() -> None:
    claims = analyze.analyze_page(fixture_text("avito", "item_gpu_mining.html"), ITEM)
    session = run_check(FakeBackend("mining_gpu"), "quick", threading.Event(), listing=claims)
    assert session.listing == claims
    assert session.verdict is not None
    ids = {f.id for f in session.verdict.findings}
    assert {"listing.gpu_match", "listing.mining", "listing.prepay_only"} <= ids
    assert any("предоплат" in p for p in session.verdict.bargaining_points)
    html = build_html(session)
    assert "Объявление" in html and "RTX 3070 8gb после майнинга" in html
    assert "19 000" in html


def test_listing_ram_claim_checked() -> None:
    claims = analyze.analyze_page(fixture_text("avito", "item_pc_gaming.html"), ITEM)
    claims.ram_gb = 64
    session = run_check(
        FakeBackend("healthy_gaming_pc"), "quick", threading.Event(), listing=claims
    )
    assert session.verdict is not None
    assert "ram.less_than_claimed" in {f.id for f in session.verdict.findings}


def test_store_with_wrong_types_is_ignored(tmp_path: Path) -> None:
    store = ListingStore(tmp_path)
    store.path.write_text('{"params": [1], "flags": "x"}', encoding="utf-8")
    assert store.load() is None


def test_store_load_on_readonly_stick(tmp_path: Path) -> None:
    (tmp_path / "data").write_text("файл вместо папки", encoding="utf-8")
    assert ListingStore(tmp_path / "data" / "listings").load() is None
