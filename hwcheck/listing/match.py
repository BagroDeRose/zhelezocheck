"""Сверка заявленного в объявлении с реальным железом.

Видеокарта сравнивается по РЕАЛЬНОЙ модели — той, что определена по коду устройства
(knowledge/gpu_db.identify), а не по имени в Windows: так перепрошитая под другую модель
карта не пройдёт сверку. Также сравниваются объём видеопамяти и процессор.
Объём оперативной памяти сверяет правило вердикта `ram.less_than_claimed`.
Тексты находок — в `data/red_flags.yaml`, раздел `match`.
"""

from __future__ import annotations

from typing import Any

from hwcheck.knowledge.gpu_db import IdentStatus, identify, vram_matches
from hwcheck.listing.extract import cpu_in_text
from hwcheck.listing.flags import FlagResult, load_flags
from hwcheck.models import (
    Finding,
    GpuInfo,
    HardwareSnapshot,
    ListingClaims,
    Severity,
    is_discrete_gpu,
)


def cpu_key(name: str) -> str:
    """Короткое имя процессора для сравнения: «AMD Ryzen 5 5600 6-Core» → «Ryzen 5 5600»."""
    return cpu_in_text(name)


def _finding(key: str, **values: Any) -> FlagResult:
    spec = load_flags()["match"][key]
    finding = Finding(
        id=f"listing.{key}",
        severity=Severity(spec["severity"]),
        component="listing",
        title=spec["title"].format(**values),
        explanation=spec["explanation"].format(**values),
        advice=spec.get("advice", "").format(**values),
        weight=float(spec.get("weight", 0)),
    )
    bargain = spec.get("bargain")
    return finding, bargain.format(**values) if bargain else None


def _real_models(gpu: GpuInfo) -> list[str]:
    """Модели, которыми карта является на самом деле (по коду устройства)."""
    ident = identify(gpu)
    if ident.real:
        return [card.model for card in ident.real]
    if ident.status is not IdentStatus.FAKE and ident.claimed is not None:
        return [ident.claimed.model]
    return []


def _match_gpu(claims: ListingClaims, snapshot: HardwareSnapshot) -> list[FlagResult]:
    discrete = [g for g in snapshot.gpus if is_discrete_gpu(g)]
    if not claims.gpu_model or not discrete:
        return []
    for gpu in discrete:
        if claims.gpu_model in _real_models(gpu):
            if (
                claims.gpu_vram_gb
                and gpu.vram_mb
                and not vram_matches(gpu.vram_mb, [claims.gpu_vram_gb])
            ):
                return [
                    _finding(
                        "gpu_vram_mismatch",
                        claimed=claims.gpu_model,
                        claimed_vram=claims.gpu_vram_gb,
                        actual_vram=round(gpu.vram_mb / 1024),
                    )
                ]
            vram_text = f", {gpu.vram_mb / 1024:.0f} ГБ" if gpu.vram_mb else ""
            return [_finding("gpu_match", claimed=claims.gpu_model, vram_text=vram_text)]
    main = max(discrete, key=lambda g: g.vram_mb or 0)
    real = _real_models(main)
    ident = identify(main)
    actual = " / ".join(real) or ident.real_chip or main.name
    return [_finding("gpu_mismatch", claimed=claims.gpu_model, actual=actual)]


def _match_cpu(claims: ListingClaims, snapshot: HardwareSnapshot) -> list[FlagResult]:
    if not claims.cpu_model or snapshot.cpu is None:
        return []
    actual = cpu_key(snapshot.cpu.name)
    if not actual:
        return []
    if actual.lower() == claims.cpu_model.lower():
        return [_finding("cpu_match", claimed=claims.cpu_model)]
    return [_finding("cpu_mismatch", claimed=claims.cpu_model, actual=actual)]


def match_listing(claims: ListingClaims, snapshot: HardwareSnapshot) -> list[FlagResult]:
    """Находки сверки объявления с железом (с аргументами для торга, где они есть)."""
    return _match_gpu(claims, snapshot) + _match_cpu(claims, snapshot)
