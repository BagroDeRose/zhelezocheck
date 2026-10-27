"""Тесты сборщика сведений о материнской плате."""

from hwcheck.collectors import board
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_parse_desktop() -> None:
    info = board.parse(fixture_json("powershell", "board.json"))
    assert info.manufacturer == "ASUSTeK COMPUTER INC."
    assert info.product == "ROG STRIX B360-H GAMING"
    assert info.version == "Rev X.0x"


def test_parse_laptop_list() -> None:
    assert board.parse(fixture_json("powershell", "board_laptop.json")).manufacturer == "LENOVO"


def test_parse_empty() -> None:
    assert board.parse(None).product == ""


def test_collect() -> None:
    fake = FakeRun(fixture_text("powershell", "board.json"))
    assert board.collect(run_fn=fake).product.startswith("ROG")
    assert "Win32_BaseBoard" in fake.commands[0][-1]
