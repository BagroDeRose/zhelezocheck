"""Справочник видеокарт и проверка «та ли это карта, за которую её выдают».

Как ловится подделка (перемаркированная карта):
1. По коду устройства PCI (его нельзя поменять наклейкой) находим реальную модель в
   справочнике `data/gpu_db.json` и название чипа в базе PCI ID.
2. По имени, которое показывает Windows, находим заявленную модель.
3. Если заявленной модели нет среди реальных — это подделка или перепрошитая карта.
4. Объём видеопамяти сверяется с допустимыми вариантами модели.

Если карту определить не удалось (нет в справочнике, ноутбучная версия, встроенная графика),
результат — «не удалось определить», а не ложная тревога.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache

from hwcheck.config import package_data_dir
from hwcheck.knowledge import pci_ids
from hwcheck.models import GpuInfo


class IdentStatus(StrEnum):
    MATCH = "match"  # заявленная модель совпадает с реальной
    FAKE = "fake"  # не совпадает: подделка, перепрошивка или не тот объём памяти
    UNKNOWN = "unknown"  # не удалось определить


@dataclass(frozen=True)
class GpuCard:
    """Запись справочника видеокарт."""

    model: str
    vendor: str
    device_ids: tuple[str, ...]
    chip: str
    vram_gb: tuple[float, ...]
    memory_type: str
    bus_width_bits: int
    base_clock_mhz: int
    boost_clock_mhz: int
    tdp_w: float
    typical_max_temp_c: float
    mining_popular: bool
    source_url: str
    verified: bool


@dataclass
class Identification:
    """Результат проверки видеокарты."""

    status: IdentStatus
    claimed: GpuCard | None = None  # что заявлено (по имени в Windows)
    real: list[GpuCard] = field(default_factory=list)  # что на самом деле (по коду устройства)
    real_chip: str = ""  # название из базы PCI ID, например «GA106 [GeForce RTX 3060]»
    vram_ok: bool | None = None
    reasons: list[str] = field(default_factory=list)


_VENDOR_IDS = {"NVIDIA": "10de", "AMD": "1002"}
# Слова, которые не влияют на модель.
_NOISE = {"nvidia", "amd", "ati", "(tm)", "(r)", "series", "graphics", "corporation"}
# Слова, отличающие модели друг от друга: если в имени есть такое слово, а в модели нет —
# это другая модель (RTX 3060 Ti ≠ RTX 3060, RX 6700 XT ≠ RX 6700, ноутбучные версии и т.д.).
_VARIANTS = {
    "ti", "super", "xt", "xtx", "gre", "laptop", "mobile", "max-q", "2048sp", "lhr", "d",
}  # fmt: skip


def _tokens(name: str) -> list[str]:
    text = name.lower().replace("(tm)", " ").replace("(r)", " ")
    return [t for t in re.split(r"[\s/,]+", text) if t and t not in _NOISE]


@cache
def load_cards() -> tuple[GpuCard, ...]:
    """Загружает справочник видеокарт (один раз)."""
    data = json.loads((package_data_dir() / "gpu_db.json").read_text(encoding="utf-8"))
    return tuple(
        GpuCard(
            model=item["model"],
            vendor=item["vendor"],
            device_ids=tuple(d.lower() for d in item["device_ids"]),
            chip=item["chip"],
            vram_gb=tuple(float(v) for v in item["vram_gb"]),
            memory_type=item["memory_type"],
            bus_width_bits=int(item["bus_width_bits"]),
            base_clock_mhz=int(item["base_clock_mhz"]),
            boost_clock_mhz=int(item["boost_clock_mhz"]),
            tdp_w=float(item["tdp_w"]),
            typical_max_temp_c=float(item["typical_max_temp_c"]),
            mining_popular=bool(item["mining_popular"]),
            source_url=item["source_url"],
            verified=bool(item["verified"]),
        )
        for item in data["cards"]
    )


def find_by_device(vendor_id: str, device_id: str) -> list[GpuCard]:
    """Все модели справочника с этим кодом устройства (у AMD их бывает несколько)."""
    vendor_id, device_id = vendor_id.lower(), device_id.lower()
    return [
        card
        for card in load_cards()
        if _VENDOR_IDS.get(card.vendor) == vendor_id and device_id in card.device_ids
    ]


def find_by_name(name: str) -> GpuCard | None:
    """Модель справочника по имени из Windows/драйвера. Не нашлась → None."""
    name_tokens = _tokens(name)
    best: GpuCard | None = None
    for card in load_cards():
        model_tokens = _tokens(card.model)
        if not all(token in name_tokens for token in model_tokens):
            continue
        extra = [t for t in name_tokens if t not in model_tokens]
        if any(token in _VARIANTS for token in extra):
            continue
        if best is None or len(model_tokens) > len(_tokens(best.model)):
            best = card
    return best


def vram_matches(vram_mb: int, variants: tuple[float, ...] | list[float]) -> bool:
    """Подходит ли объём памяти к одному из вариантов (с допуском на округления драйвера)."""
    vram_gb = vram_mb / 1024
    return any(abs(vram_gb - v) <= max(0.5, v * 0.1) for v in variants)


def _numbers(model: str) -> list[str]:
    return re.findall(r"\d{3,4}", model)


def identify(gpu: GpuInfo) -> Identification:
    """Сверяет заявленную модель видеокарты с реальной (по коду устройства и объёму памяти)."""
    chip = pci_ids.lookup(gpu.pci_vendor_id, gpu.pci_device_id)
    real = find_by_device(gpu.pci_vendor_id, gpu.pci_device_id)
    claimed = find_by_name(gpu.name)
    ident = Identification(
        status=IdentStatus.UNKNOWN, claimed=claimed, real=real, real_chip=chip.name if chip else ""
    )
    real_names = " / ".join(card.model for card in real) or (chip.name if chip else "")

    if claimed is None:
        ident.reasons.append(
            f"Модель «{gpu.name}» не найдена в справочнике — сверка не проводилась."
            + (f" По коду устройства это {real_names}." if real_names else "")
        )
    elif real:
        if claimed in real:
            ident.status = IdentStatus.MATCH
        else:
            ident.status = IdentStatus.FAKE
            ident.reasons.append(
                f"Windows показывает «{gpu.name}», но по коду устройства это {real_names}. "
                "Видеокарту перемаркировали или перепрошили."
            )
    elif chip is not None:
        if all(number in chip.name for number in _numbers(claimed.model)):
            ident.reasons.append(
                f"Код устройства относится к «{chip.name}», точной записи в справочнике нет."
            )
        else:
            ident.status = IdentStatus.FAKE
            ident.reasons.append(
                f"Windows показывает «{gpu.name}», но по коду устройства это «{chip.name}». "
                "Видеокарту перемаркировали или перепрошили."
            )
    else:
        ident.reasons.append("Код устройства неизвестен — определить реальную модель не удалось.")

    if real and gpu.vram_mb:
        variants = sorted({v for card in real for v in card.vram_gb})
        ident.vram_ok = vram_matches(gpu.vram_mb, variants)
        if not ident.vram_ok:
            ident.status = IdentStatus.FAKE
            expected = ", ".join(f"{v:g}" for v in variants)
            ident.reasons.append(
                f"Объём видеопамяти {gpu.vram_mb / 1024:.1f} ГБ не бывает у этой модели "
                f"(бывает: {expected} ГБ)."
            )
    return ident


# ---------------------------------------------------------------------------
# Поиск модели в свободном тексте (объявления)
# ---------------------------------------------------------------------------

_BRAND_WORDS = {"geforce", "radeon", "nvidia", "amd"}
_MEMORY_TOKEN = re.compile(r"^\d+gb$")


def normalize_text(text: str) -> list[str]:
    """Текст объявления → слова: «RTX3060 12 Гб» → ['rtx', '3060', '12gb']."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"(\d+)\s*(?:gb|гб|g|г)\b", r"\1gb", text)
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)  # rtx3060 → rtx 3060
    text = re.sub(r"(\d)(ti|super|xt|xtx)\b", r"\1 \2", text)  # 3060ti → 3060 ti
    return [t for t in re.split(r"[^0-9a-zа-я+-]+", text) if t]


def _model_key(card: GpuCard) -> list[str]:
    return [t for t in _tokens(card.model) if t not in _BRAND_WORDS and not _MEMORY_TOKEN.match(t)]


def _find_sequence(words: list[str], key: list[str]) -> int:
    """Позиция, где слова `key` идут подряд в `words`; -1 — не найдено."""
    for start in range(len(words) - len(key) + 1):
        if words[start : start + len(key)] == key:
            return start
    return -1


def find_in_text(text: str) -> GpuCard | None:
    """Ищет модель видеокарты в тексте объявления. Не нашлась или неоднозначно → None."""
    words = normalize_text(text)
    matches: list[tuple[int, GpuCard]] = []
    for card in load_cards():
        key = _model_key(card)
        position = _find_sequence(words, key)
        if position < 0:
            continue
        following = words[position + len(key) : position + len(key) + 1]
        if following and following[0] in _VARIANTS:
            continue  # «RTX 3060 Ti» — это не «RTX 3060»
        matches.append((len(key), card))
    if not matches:
        return None
    best_len = max(length for length, _ in matches)
    best = [card for length, card in matches if length == best_len]
    if len(best) > 1:
        # Одна модель в разных объёмах памяти (GTX 1060 3GB/6GB): выбираем по объёму из текста.
        sizes = {f"{v:g}gb" for v in (vram_in_text(text) or [])}
        by_memory = [c for c in best if any(t in sizes for t in _tokens(c.model))]
        best = by_memory or best
    return best[0]


def vram_in_text(text: str) -> list[float]:
    """Все упоминания объёма «N ГБ» в тексте (для выбора варианта модели)."""
    return [float(n) for n in re.findall(r"(\d+)\s*(?:gb|гб|g|г)\b", text.lower())]
