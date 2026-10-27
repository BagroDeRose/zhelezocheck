"""Тесты файла порогов: схема, загрузка, разумность значений."""

import json
from pathlib import Path

import jsonschema
import pytest

from hwcheck import thresholds
from hwcheck.backends.base import ALL_STRESS_TESTS
from hwcheck.config import package_data_dir


def test_schema() -> None:
    data = json.loads((package_data_dir() / "thresholds.json").read_text(encoding="utf-8"))
    schema = json.loads((package_data_dir() / "thresholds.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_load_defaults() -> None:
    th = thresholds.load_thresholds()
    assert th.get("gpu.emergency_stop_c") == 90
    assert th.get("gpu.warning_c") == 83
    assert th.get("cpu.clock_drop_pct") == 15
    assert th.get("gpu.warning_c") < th.get("gpu.emergency_stop_c")
    assert th.get("ssd.wear_warning_pct") < th.get("ssd.wear_critical_pct")
    assert th.why("gpu.emergency_stop_c")


def test_unknown_key() -> None:
    with pytest.raises(KeyError):
        thresholds.load_thresholds().get("nope")


def test_durations_cover_all_tests_and_short_mode_is_safe() -> None:
    th = thresholds.load_thresholds()
    for mode in ("quick", "full", "short"):
        for test in ALL_STRESS_TESTS:
            assert th.duration(mode, test) > 0
    # Режим --short на машине разработчика — не дольше 30 секунд на тест.
    assert all(th.duration("short", t) <= 30 for t in ALL_STRESS_TESTS)
    # Быстрая проверка — около 10 минут, полная — 30–40 минут.
    assert sum(th.duration("quick", t) for t in ALL_STRESS_TESTS) <= 12 * 60
    assert 25 * 60 <= sum(th.duration("full", t) for t in ALL_STRESS_TESTS) <= 40 * 60


def test_load_custom_file(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "thresholds": {
                    "x": {"value": 1.5, "unit": "", "why": "достаточно длинное пояснение"}
                },
                "durations_s": {"quick": {}, "full": {}, "short": {}},
            }
        ),
        encoding="utf-8",
    )
    assert thresholds.load_thresholds(path).get("x") == 1.5
