"""Распознавание заявленного в объявлении железа (с 2.1 — только для сверки с проверкой).

Из заголовка, характеристик и описания объявления распознаются модель и объём памяти
видеокарты, процессор и объём оперативной памяти. Эти значения программа сверяет с тем,
что нашла на компьютере (`listing/match.py`, правило вердикта `ram.less_than_claimed`).

До 2.1 здесь же разбирались сохранённые страницы сайтов (HTML и селекторы) — это убрано
вместе с ценой по рынку и «тревожными словами»: объявление теперь только вставляется
текстом на экране выбора режима.
"""

from __future__ import annotations

import re

from hwcheck.knowledge.gpu_db import find_in_text
from hwcheck.models import ListingClaims

MAX_PRICE_RUB = 10_000_000  # дороже домашнее железо не бывает; больше — мусор в тексте


def parse_price(text: str) -> int | None:
    """«23 500 ₽» или «23500.00» → 23500. Неразумные числа → None."""
    if not text:
        return None
    digits = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    if not digits or len(digits) > 15:
        return None
    try:
        value = int(float(digits))
    except (ValueError, OverflowError):
        return None
    return value if 0 < value <= MAX_PRICE_RUB else None


_INTEL_RE = re.compile(r"\b(?:core\s*)?(i[3579])[\s-]?(\d{4,5})([a-z]{0,2})\b", re.IGNORECASE)
_RYZEN_RE = re.compile(r"\bryzen\s*([3579])\s*(\d{4})([a-z0-9]{0,3})\b", re.IGNORECASE)
_GB_RE = re.compile(r"(\d+)\s*(?:gb|гб|g|г)\b", re.IGNORECASE)
_RAM_HINT_RE = re.compile(
    r"(\d+)\s*(?:gb|гб|g|г)\s*(?:ddr\d|озу|оперативн|ram)|(?:озу|оперативн\w*|ram)\s*:?\s*(\d+)\s*(?:gb|гб|g|г)",
    re.IGNORECASE,
)
_KIT_RE = re.compile(r"\b(\d)\s*[xх×*]\s*(\d{1,3})\s*(?:gb|гб|g|г)\b", re.IGNORECASE)
_RAM_AD_RE = re.compile(r"^\s*(?:озу|оперативн\w*\s+памят\w*|память\s+ddr\d|ddr\d)", re.IGNORECASE)


def ram_in_claims(claims: ListingClaims) -> float | None:
    """Объём памяти в объявлении (компьютера или комплекта планок), ГБ.

    Источники по порядку: параметр «Оперативная память»; у объявлений о планках —
    «Объём одного модуля» × «Количество модулей в комплекте» (так Авито пишет комплекты);
    в тексте — «2x8gb», «16 ГБ DDR4», «ОЗУ: 16 ГБ», а в заголовке объявления о памяти —
    любое «32Gb».
    """
    ram_param = _param(claims.params, "оперативн", "озу")
    if ram_param:
        return _gb(ram_param)
    # В названии параметра уже стоит «ГБ», значение — просто число.
    module = _number(_param(claims.params, "объём одного модуля", "объем одного модуля"))
    if module:
        count = _number(_param(claims.params, "количество модулей"))
        return module * (count or 1)
    for text in (claims.title, claims.description):
        if kit := _KIT_RE.search(text):
            return float(int(kit.group(1)) * int(kit.group(2)))
        if match := _RAM_HINT_RE.search(text):
            return float(match.group(1) or match.group(2))
    if _RAM_AD_RE.search(claims.title) and (size := _GB_RE.search(claims.title)):
        return float(size.group(1))
    return None


def cpu_in_text(text: str) -> str:
    """Модель процессора в тексте: «i5 12400f» → «i5-12400F», «ryzen 5 5600» → «Ryzen 5 5600»."""
    if match := _RYZEN_RE.search(text):
        return f"Ryzen {match.group(1)} {match.group(2)}{match.group(3).upper()}"
    if match := _INTEL_RE.search(text):
        return f"{match.group(1).lower()}-{match.group(2)}{match.group(3).upper()}"
    return ""


def _param(params: dict[str, str], *words: str) -> str:
    for key, value in params.items():
        if any(word in key.lower() for word in words):
            return value
    return ""


def _number(text: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", text)
    return float(match.group(0).replace(",", ".")) if match else None


def _gb(text: str) -> float | None:
    match = _GB_RE.search(text)
    return float(match.group(1)) if match else None


def recognize_hardware(claims: ListingClaims) -> None:
    """Заполняет заявленные модели и объёмы по тексту объявления."""
    params_text = " ".join(f"{k}: {v}" for k, v in claims.params.items())
    gpu_param = _param(claims.params, "видеокарт", "модель")
    texts = [claims.title, gpu_param, params_text, claims.description]
    for text in texts:
        card = find_in_text(text) if text else None
        if card is not None:
            claims.gpu_model = card.model
            break
    vram_param = _param(claims.params, "видеопамят")
    claims.gpu_vram_gb = _gb(vram_param) if vram_param else None
    if claims.gpu_vram_gb is None and claims.gpu_model:
        # «RTX 3060 12gb» — объём сразу после модели в заголовке.
        number = re.search(r"\d{3,4}", claims.gpu_model)
        if number:
            after = re.search(
                number.group(0) + r"[^/|,]{0,20}?(\d+)\s*(?:gb|гб|g|г)\b", claims.title, re.I
            )
            if after:
                claims.gpu_vram_gb = float(after.group(1))
        if claims.gpu_vram_gb is None:
            card_memory = re.search(r"(\d+)GB$", claims.gpu_model)
            claims.gpu_vram_gb = float(card_memory.group(1)) if card_memory else None
    claims.cpu_model = cpu_in_text(
        " ".join([_param(claims.params, "процессор"), claims.title, claims.description])
    )
    claims.ram_gb = ram_in_claims(claims)


def has_claims(claims: ListingClaims) -> bool:
    """Есть ли что сверять: распознана видеокарта, процессор или объём памяти."""
    return bool(claims.gpu_model or claims.cpu_model or claims.ram_gb)
