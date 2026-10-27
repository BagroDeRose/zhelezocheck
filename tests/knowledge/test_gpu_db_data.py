"""Проверка справочника видеокарт: схема, источники, отсутствие противоречий."""

import json
from collections import defaultdict
from typing import Any

import jsonschema

from hwcheck.config import package_data_dir
from hwcheck.knowledge import pci_ids

VENDOR_IDS = {"NVIDIA": "10de", "AMD": "1002"}


def _load(name: str) -> Any:
    return json.loads((package_data_dir() / name).read_text(encoding="utf-8"))


def test_schema_valid() -> None:
    jsonschema.validate(_load("gpu_db.json"), _load("gpu_db.schema.json"))


def test_every_card_has_source_and_sane_clocks() -> None:
    for card in _load("gpu_db.json")["cards"]:
        assert card["source_url"].startswith("https://"), card["model"]
        assert card["boost_clock_mhz"] >= card["base_clock_mhz"], card["model"]


def test_models_unique() -> None:
    models = [card["model"] for card in _load("gpu_db.json")["cards"]]
    assert len(models) == len(set(models))


def test_shared_device_ids_are_consistent() -> None:
    # Один код устройства может быть у нескольких моделей одного чипа (RX 470/570/580),
    # но не у моделей разных производителей или разных чипов.
    owners: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for card in _load("gpu_db.json")["cards"]:
        for device_id in card["device_ids"]:
            owners[(card["vendor"], device_id)].add((card["vendor"], card["chip"]))
    contradictions = {key: value for key, value in owners.items() if len(value) > 1}
    assert contradictions == {}


def test_device_ids_exist_in_pci_database() -> None:
    for card in _load("gpu_db.json")["cards"]:
        for device_id in card["device_ids"]:
            assert pci_ids.lookup(VENDOR_IDS[card["vendor"]], device_id), (card["model"], device_id)


def test_both_vendors_and_mining_cards_present() -> None:
    cards = _load("gpu_db.json")["cards"]
    assert {c["vendor"] for c in cards} == {"NVIDIA", "AMD"}
    assert sum(c["mining_popular"] for c in cards) >= 20
