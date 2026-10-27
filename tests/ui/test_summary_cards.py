"""Сводка «Что найдено» карточками (задача 22.5)."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.models import BatteryInfo, HardwareSnapshot, SmartData
from hwcheck.ui.summary_cards import CRITICAL, OK, WARNING, SummaryCard, build_cards
from hwcheck.ui.widgets.summary_grid import MAX_COLUMNS, SummaryGrid, columns_for
from tests.ui.helpers import make_window


def cards_by_key(scenario: str) -> dict[str, SummaryCard]:
    return {card.key: card for card in build_cards(FakeBackend(scenario).collect())}


def test_gaming_pc_has_all_component_cards() -> None:
    cards = cards_by_key("healthy_gaming_pc")
    for key in ("board", "bios", "cpu", "memory", "gpu0", "disk0", "windows"):
        assert key in cards, key
    assert "battery" not in cards  # у настольного компьютера батареи нет
    for card in cards.values():
        assert card.icon and card.title and card.status_text
        assert 2 <= len(card.params) <= 4, card.key


def test_card_parameters_match_spec() -> None:
    cards = cards_by_key("healthy_gaming_pc")
    names = {key: [name for name, _ in card.params] for key, card in cards.items()}
    assert names["board"][:2] == ["Производитель", "Модель"]
    assert names["bios"][:2] == ["Версия", "Дата"]
    assert names["memory"] == ["Объём", "Планки", "Частота"]
    assert names["disk0"][:3] == ["Модель", "Объём", "Тип"]
    assert names["gpu0"] == ["Модель", "Видеопамять", "Драйвер"]
    assert names["cpu"][:2] == ["Модель", "Ядра / потоки"]
    assert names["windows"] == ["Версия", "Сборка", "Разрядность"]
    assert "RTX 3060" in cards["gpu0"].plain_text() and "12 ГБ" in cards["gpu0"].plain_text()


def test_laptop_has_battery_card_with_status() -> None:
    cards = cards_by_key("laptop_worn_battery")
    assert cards["battery"].status in (WARNING, CRITICAL)
    assert "Ноутбук" in cards["board"].plain_text()


def test_dying_disk_is_red() -> None:
    cards = cards_by_key("dying_hdd")
    statuses = [card.status for key, card in cards.items() if key.startswith("disk")]
    assert CRITICAL in statuses


@pytest.mark.parametrize(
    ("smart", "status"),
    [
        (SmartData(reallocated_sectors=0, health_passed=True), OK),
        (SmartData(reallocated_sectors=3), WARNING),
        (SmartData(pending_sectors=80), CRITICAL),
        (SmartData(health_passed=False), CRITICAL),
    ],
)
def test_disk_status_from_smart(smart: SmartData, status: str) -> None:
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    snapshot.disks = snapshot.disks[:1]
    snapshot.disks[0].smart = smart
    card = next(c for c in build_cards(snapshot) if c.key == "disk0")
    assert card.status == status


def test_unknown_battery_wear_does_not_crash() -> None:
    snapshot = HardwareSnapshot(battery=BatteryInfo(design_capacity_mwh=0))
    card = next(c for c in build_cards(snapshot) if c.key == "battery")
    assert card.status == "info"


def test_collector_errors_get_their_own_card() -> None:
    snapshot = HardwareSnapshot(errors={"gpu": "nvidia-smi не ответил"})
    cards = build_cards(snapshot)
    assert [c.key for c in cards] == ["errors"]
    assert "nvidia-smi не ответил" in cards[0].plain_text()


@pytest.mark.parametrize(
    ("width", "columns"), [(200, 1), (300, 1), (560, 2), (800, 3), (1100, 4), (3000, MAX_COLUMNS)]
)
def test_columns_follow_width(width: int, columns: int) -> None:
    assert columns_for(width) == columns


def at(grid: SummaryGrid, row: int, column: int) -> object:
    item = grid.grid.itemAtPosition(row, column)
    return item.widget() if item else None


def test_grid_rearranges_on_resize(qtbot: QtBot) -> None:
    grid = SummaryGrid()
    qtbot.addWidget(grid)
    grid.set_cards(build_cards(FakeBackend("healthy_gaming_pc").collect()))
    grid.resize(1100, 600)
    grid.show()
    qtbot.waitUntil(lambda: grid.columns == 4)
    assert at(grid, 0, 3) is grid.cards[3]
    grid.resize(300, 600)
    qtbot.waitUntil(lambda: grid.columns == 1)
    assert at(grid, 3, 0) is grid.cards[3]


def test_start_page_shows_cards(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    cards = window.start_page.summary_grid.cards
    assert len(cards) >= 7
    assert all(card.status_label.text().startswith("●") for card in cards)
