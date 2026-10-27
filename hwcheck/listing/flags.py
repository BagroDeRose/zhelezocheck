"""Тревожные признаки в объявлении: слова в тексте и подозрительные числа.

Текстовые признаки и их пояснения — в `data/red_flags.yaml`. Если признак упомянут
с отрицанием («майнингом не занимался»), он не срабатывает — вместо этого покупатель
видит пометку «продавец утверждает…, проверим тестом».

Числовые признаки: цена сильно ниже рынка, новый аккаунт продавца, много объявлений
или несколько одинаковых карт.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir
from hwcheck.models import Finding, ListingClaims, Severity

FlagResult = tuple[Finding, str | None]  # находка и аргумент для торга

_NEGATION_BEFORE = re.compile(r"\b(?:не|без|нет|никогда|ни\s+разу)\b[^.!?\n]{0,20}$", re.I)
_NEGATION_AFTER = re.compile(r"^\w*[\s,:-]{0,3}(?:не|нет|никогда)\b", re.I)
_SENTENCE_END = re.compile(r"[.!?\n]")

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
_MANY_SAME_RE = re.compile(
    r"(\d+)\s*(?:шт|штук)|есть\s+ещ[её]|в\s+наличии\s+\d+|несколько\s+(?:штук|карт)", re.I
)


@cache
def load_flags() -> dict[str, Any]:
    return yaml.safe_load((package_data_dir() / "red_flags.yaml").read_text(encoding="utf-8"))


def _finding(flag_id: str, spec: dict[str, Any], **values: Any) -> Finding:
    return Finding(
        id=f"listing.{flag_id}",
        severity=Severity(spec["severity"]),
        component="listing",
        title=spec["title"].format(**values),
        explanation=spec["explanation"].format(**values),
        advice=spec.get("advice", "").format(**values),
        weight=float(spec.get("weight", 0)),
    )


def _is_negated(text: str, start: int, end: int) -> bool:
    sentence_start = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    before = text[sentence_start:start]
    after = text[end : end + 25]
    return bool(_NEGATION_BEFORE.search(before) or _NEGATION_AFTER.search(after))


def text_flags(text: str) -> list[FlagResult]:
    """Текстовые признаки (каждый — не больше одного раза)."""
    results: list[FlagResult] = []
    for flag_id, spec in load_flags()["flags"].items():
        patterns = spec.get("patterns")
        if not patterns:
            continue
        found = negated = False
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if "denied" in spec and _is_negated(text, match.start(), match.end()):
                    negated = True
                else:
                    found = True
        if found:
            results.append((_finding(flag_id, spec), spec.get("bargain")))
        elif negated:
            denied = {**spec, **spec["denied"], "severity": "info", "weight": 0, "advice": ""}
            results.append((_finding(f"{flag_id}.denied", denied), None))
    return results


def parse_seller_since(text: str) -> date | None:
    """«На Авито с марта 2019» → 2019-03-01; «с 2015 года» → 2015-01-01."""
    year = re.search(r"(19|20)\d{2}", text)
    if not year:
        return None
    month = 1
    lowered = text.lower()
    for stem, number in _MONTHS.items():
        if re.search(rf"\b{stem}\w*\s+(?:19|20)\d{{2}}", lowered):
            month = number
            break
    return date(int(year.group(0)), month, 1)


def numeric_flags(
    claims: ListingClaims, median_price: int | None, today: date | None = None
) -> list[FlagResult]:
    data = load_flags()
    limits, specs = data["limits"], data["flags"]
    results: list[FlagResult] = []
    if (
        median_price
        and claims.price_rub
        and claims.price_rub < median_price * limits["price_low_ratio"]
    ):
        percent = claims.price_rub / median_price * 100
        results.append(
            (
                _finding(
                    "price_low",
                    specs["price_low"],
                    price=claims.price_rub,
                    median=median_price,
                    percent=percent,
                ),
                None,
            )
        )
    since = parse_seller_since(claims.seller_since) if claims.seller_since else None
    today = today or datetime.now().date()
    if since is not None:
        months = (today.year - since.year) * 12 + (today.month - since.month)
        if months < limits["new_seller_months"]:
            results.append(
                (_finding("new_seller", specs["new_seller"], since=claims.seller_since), None)
            )
    details: list[str] = []
    if claims.seller_listings is not None and claims.seller_listings >= limits["many_listings"]:
        details.append(f"У продавца {claims.seller_listings} объявлений.")
    if _MANY_SAME_RE.search(f"{claims.title} {claims.description}"):
        details.append("В объявлении говорится о нескольких одинаковых картах.")
    if details:
        results.append((_finding("many_same", specs["many_same"], details=" ".join(details)), None))
    return results


def find_flags(
    claims: ListingClaims, median_price: int | None = None, today: date | None = None
) -> list[FlagResult]:
    """Все тревожные признаки объявления."""
    params = " ".join(f"{k}: {v}" for k, v in claims.params.items())
    text = "\n".join([claims.title, claims.description, params])
    return text_flags(text) + numeric_flags(claims, median_price, today)
