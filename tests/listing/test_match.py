"""Тесты сверки заявленного в объявлении с реальным железом."""

from hwcheck.backends.fake import load_scenario
from hwcheck.listing import match
from hwcheck.models import ListingClaims, Severity


def _ids(claims: ListingClaims, scenario: str) -> dict[str, Severity]:
    snapshot = load_scenario(scenario).snapshot
    return {f.id: f.severity for f, _ in match.match_listing(claims, snapshot)}


def test_gpu_and_cpu_match() -> None:
    claims = ListingClaims(gpu_model="GeForce RTX 3060", gpu_vram_gb=12, cpu_model="Ryzen 5 5600")
    assert _ids(claims, "healthy_gaming_pc") == {
        "listing.gpu_match": Severity.OK,
        "listing.cpu_match": Severity.OK,
    }


def test_vram_mismatch_explained() -> None:
    claims = ListingClaims(gpu_model="GeForce RTX 3060", gpu_vram_gb=12)
    snapshot = load_scenario("healthy_gaming_pc").snapshot
    snapshot.gpus[0].vram_mb = 8192
    (finding, bargain) = match.match_listing(claims, snapshot)[0]
    assert finding.id == "listing.gpu_vram_mismatch"
    assert finding.severity is Severity.CRITICAL
    assert "Заявлена GeForce RTX 3060 12 ГБ, обнаружена GeForce RTX 3060 8 ГБ" in finding.title
    assert bargain is None


def test_other_model_detected() -> None:
    claims = ListingClaims(gpu_model="GeForce RTX 3080", gpu_vram_gb=10)
    ids = _ids(claims, "mining_gpu")
    assert ids == {"listing.gpu_mismatch": Severity.CRITICAL}


def test_fake_card_matches_its_real_chip_not_its_name() -> None:
    # Продавец пишет «GTX 1060 6GB», Windows тоже так показывает, но чип — от GT 730.
    claims = ListingClaims(gpu_model="GeForce GTX 1060 6GB", gpu_vram_gb=6)
    snapshot = load_scenario("fake_gpu_relabel").snapshot
    findings = match.match_listing(claims, snapshot)
    assert findings[0][0].id == "listing.gpu_mismatch"
    assert "GT 730" in findings[0][0].title


def test_cpu_mismatch() -> None:
    claims = ListingClaims(cpu_model="i7-8700K")
    assert _ids(claims, "healthy_gaming_pc") == {"listing.cpu_mismatch": Severity.WARNING}


def test_nothing_claimed_nothing_found() -> None:
    assert match.match_listing(ListingClaims(), load_scenario("healthy_gaming_pc").snapshot) == []


def test_normalize_cpu_name() -> None:
    assert match.cpu_key("AMD Ryzen 5 5600 6-Core Processor") == "Ryzen 5 5600"
    assert match.cpu_key("Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz") == "i7-8700K"
