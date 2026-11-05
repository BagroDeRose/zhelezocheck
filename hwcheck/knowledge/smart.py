"""Расшифровка S.M.A.R.T. для технического отчёта (SPEC_V2_1, этап 45).

Тексты и значимость — в `hwcheck/data/smart_attributes.yaml`; здесь только логика:
- `attribute_status` — нормализованный статус атрибута SATA по Current/Worst/Threshold
  (порог не прочитан — так и говорим, не считаем нулём);
- `interpret_attribute` — что значит атрибут и его Raw (для ключевых — по справочнику,
  для остальных — оговорка, что Raw у производителей разное);
- `nvme_rows` — все поля журнала здоровья NVMe с единицами и пояснениями (неизвестные поля
  тоже показываются — специалисту ничего не прячем).

Это справка, а не вердикт: решения «брать/торговаться/уходить» — в правилах `rules.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir
from hwcheck.models import SmartAttribute

NVME_DATA_UNIT_BYTES = 512_000  # стандарт NVMe: «единица» — 1000 блоков по 512 байт
CRITICAL_WARNING_BITS = {
    0x1: "резерв ячеек ниже порога",
    0x2: "температура вне допуска",
    0x4: "надёжность снижена",
    0x8: "накопитель только для чтения",
    0x10: "сбой резервного питания памяти",
}
STATUS_TEXTS = {
    # Не «в норме»: значение выше порога, а Raw ключевого атрибута может говорить об износе.
    "ok": "нормализованное значение выше порога отказа",
    "no_limit": "порога отказа нет (0) — это счётчик, смотрите Raw",
    "no_threshold": "порог не прочитан (без прав администратора smartctl не всегда его читает)",
    "failing": "НИЖЕ ПОРОГА — накопитель сам считает этот показатель отказом",
    "failed_in_past": "был ниже порога в прошлом",
}


@cache
def _data() -> dict[str, Any]:
    text = (package_data_dir() / "smart_attributes.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def ata_info(attribute_id: int) -> dict[str, str] | None:
    """Справка по ключевому атрибуту SATA или None (атрибут производителя)."""
    return _data()["ata"].get(attribute_id)


def attribute_status(attribute: SmartAttribute) -> tuple[str, str]:
    """(код, текст) нормализованного статуса: ok / no_limit / no_threshold / failing /
    failed_in_past."""
    if attribute.when_failed and attribute.when_failed.upper() != "IN_THE_PAST":
        code = "failing"
    elif attribute.threshold is None:
        code = "no_threshold"
    elif (
        attribute.threshold > 0
        and attribute.value is not None
        and attribute.value <= attribute.threshold
    ):
        code = "failing"
    elif attribute.when_failed:
        code = "failed_in_past"
    elif attribute.threshold == 0:
        code = "no_limit"
    else:
        code = "ok"
    return code, STATUS_TEXTS[code]


def interpret_attribute(attribute: SmartAttribute) -> str:
    """Статус и смысл атрибута простыми словами (для колонки «Пояснение»)."""
    _code, status = attribute_status(attribute)
    info = ata_info(attribute.id)
    if info is None:
        return f"{status}. {_data()['default_note']}"
    parts = [status + ".", info["meaning"]]
    if attribute.raw and info.get("raw_nonzero"):
        parts.append(info["raw_nonzero"].format(raw=attribute.raw))
    return " ".join(parts)


def ata_title(attribute: SmartAttribute) -> str:
    info = ata_info(attribute.id)
    name = info["title"] if info else attribute.name or "атрибут производителя"
    return f"#{attribute.id} {name}"


@dataclass(frozen=True)
class NvmeRow:
    key: str
    title: str
    value: str
    note: str = ""


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _critical_warning(value: int) -> str:
    if value == 0:
        return "0 (нет предупреждений)"
    names = [name for bit, name in CRITICAL_WARNING_BITS.items() if value & bit]
    return f"{value}: " + ", ".join(names or ["неизвестный бит"])


def _format(key: str, value: Any, info: dict[str, str]) -> str:
    if key == "critical_warning" and isinstance(value, int):
        return _critical_warning(value)
    kind = info.get("kind", "")
    if kind == "data_units" and isinstance(value, int):
        terabytes = value * NVME_DATA_UNIT_BYTES / 1e12
        return f"{_decimal(terabytes)} ТБ ({value} единиц по 512 000 байт)"
    unit = "мин" if kind == "minutes" else info.get("unit", "")
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) or "—"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def nvme_rows(log: dict[str, Any]) -> list[NvmeRow]:
    """Все поля журнала здоровья NVMe в порядке справочника, затем неизвестные — как есть."""
    known: dict[str, dict[str, str]] = _data()["nvme"]
    keys = [key for key in known if key in log] + [key for key in log if key not in known]
    rows = []
    for key in keys:
        info = known.get(key, {})
        value = log[key]
        note = info.get("note", "")
        if info.get("nonzero") and isinstance(value, int | float) and value:
            note = info["nonzero"]
        rows.append(
            NvmeRow(
                key, info.get("title", f"Поле smartctl: {key}"), _format(key, value, info), note
            )
        )
    return rows
