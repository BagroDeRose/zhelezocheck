"""Сводка «Что найдено» карточками (задача 22.5)."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.models import BatteryInfo, HardwareSnapshot, SmartData
from hwcheck.ui import strings
from hwcheck.ui.summary_cards import CRITICAL, INFO, OK, WARNING, SummaryCard, build_cards
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
        assert 2 <= len(card.params) <= 7, card.key


def test_card_parameters_match_spec() -> None:
    cards = cards_by_key("healthy_gaming_pc")
    names = {key: [name for name, _ in card.params] for key, card in cards.items()}
    values = {key: dict(card.params) for key, card in cards.items()}
    assert names["board"][:2] == ["Производитель", "Модель"]
    assert names["bios"][:2] == ["Версия", "Дата"]
    assert names["memory"] == ["Объём", "Планки", "Частота", "Модули"]
    assert values["memory"]["Модули"] == "16 ГБ Kingston ×2"
    assert names["disk0"][:3] == ["Модель", "Объём", "Тип"]
    assert names["gpu0"][:3] == ["Модель", "Видеопамять", "Драйвер"]
    assert names["cpu"][:2] == ["Модель", "Ядра / потоки"]
    assert values["cpu"]["Сокет"] == "AM4"
    assert names["windows"][:3] == ["Версия", "Сборка", "Разрядность"]
    assert "RTX 3060" in cards["gpu0"].plain_text() and "12 ГБ" in cards["gpu0"].plain_text()


def test_gpu_card_shows_chip_bus_and_power() -> None:
    gpu = cards_by_key("healthy_gaming_pc")["gpu0"]
    values = dict(gpu.params)
    assert "GA106" in values["Чип"]
    # В простое поколение PCIe снижается (это норма), поэтому показываем максимальное.
    assert values["Шина"] == "PCIe 4.0 ×16"
    assert values["Лимит мощности"] == "170 Вт"
    assert gpu.status == OK and gpu.status_text == strings.CARD_GPU_MATCH


def test_fake_gpu_card_is_red() -> None:
    gpu = cards_by_key("fake_gpu_relabel")["gpu0"]
    assert gpu.status == CRITICAL and "GT 730" in gpu.plain_text()


def test_reduced_pcie_width_warns() -> None:
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    # Порог тот же, что у правила вердикта: тревожно только меньше половины линий.
    snapshot.gpus[0].pcie_width_current = 8
    gpu = next(c for c in build_cards(snapshot) if c.key == "gpu0")
    assert gpu.status == OK
    snapshot.gpus[0].pcie_width_current = 4
    gpu = next(c for c in build_cards(snapshot) if c.key == "gpu0")
    assert gpu.status == WARNING and "×4 из ×16" in gpu.status_text


def test_disk_card_shows_hours_and_temperature() -> None:
    values = dict(cards_by_key("healthy_gaming_pc")["disk1"].params)
    assert values["Наработка"] == "14 210 ч (≈1,6 г.)"
    assert values["Температура"] == "34 °C"


def test_nvme_written_and_low_spare() -> None:
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    smart = snapshot.disks[0].smart
    assert smart is not None
    smart.data_written_tb = 46.6
    smart.available_spare_pct, smart.available_spare_threshold_pct = 5, 10
    card = next(c for c in build_cards(snapshot) if c.key == "disk0")
    assert dict(card.params)["Записано"] == "46,6 ТБ"
    assert card.status == WARNING and card.status_text == strings.CARD_DISK_SPARE_LOW


def test_windows_card_install_date_and_uptime() -> None:
    values = dict(cards_by_key("healthy_gaming_pc")["windows"].params)
    assert values["Установлена"] == "14.03.2024"
    assert values["Без перезагрузки"] == "2 ч 59 мин"


def test_recently_installed_windows_is_a_hint() -> None:
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    assert snapshot.system is not None
    snapshot.system.install_date = "2026-10-01T08:00:00"  # за 4 дня до проверки
    card = next(c for c in build_cards(snapshot) if c.key == "windows")
    assert card.status == INFO and card.status_text == strings.CARD_WINDOWS_RECENT


def test_event_log_card() -> None:
    card = cards_by_key("healthy_gaming_pc")["events"]
    assert card.status == OK and "30" in card.status_text
    assert dict(card.params)["Синие экраны"] == "0"
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    assert snapshot.events is not None
    snapshot.events.counts["bugcheck"] = 2
    card = next(c for c in build_cards(snapshot) if c.key == "events")
    assert card.status == WARNING and dict(card.params)["Синие экраны"] == "2"
    snapshot.events.counts["bugcheck"] = 0
    snapshot.events.partial = True
    card = next(c for c in build_cards(snapshot) if c.key == "events")
    assert card.status == INFO and card.status_text == strings.CARD_EVENTS_PARTIAL


@pytest.mark.parametrize(
    ("manufacturer", "model"),
    [("System manufacturer", "System Product Name"), ("To be filled by O.E.M.", "To Be Filled")],
)
def test_oem_placeholders_are_hidden(manufacturer: str, model: str) -> None:
    """Сборные компьютеры вместо названия пишут заглушки — их не показываем."""
    snapshot = FakeBackend("healthy_gaming_pc").collect()
    assert snapshot.system is not None
    snapshot.system.manufacturer, snapshot.system.model = manufacturer, model
    board = next(c for c in build_cards(snapshot) if c.key == "board")
    assert [name for name, _ in board.params] == ["Производитель", "Модель"]
    assert "B550-A PRO" in board.plain_text()


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
