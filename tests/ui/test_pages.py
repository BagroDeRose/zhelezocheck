"""Тесты страниц интерфейса (задачи 7.2–7.6) на фейковом бэкенде."""

import time
from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import get_paths
from hwcheck.models import HardwareSnapshot
from hwcheck.thresholds import load_thresholds
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow
from hwcheck.ui.pages.progress import remaining_text
from tests.ui.helpers import make_window

# ---------------------------------------------------------------- 7.2 Старт


def test_start_summary_and_admin_status(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, scenario="laptop_worn_battery")
    page = window.start_page
    assert page.snapshot is not None
    text = page.summary_grid.plain_text()
    assert "Ryzen 7 5800H" in text and "Батарея" in text and "Ноутбук" in text
    assert page.admin_label.text() == strings.ADMIN_NO
    assert not page.relaunch_button.isVisibleTo(page)  # в демо перезапуск не предлагается


def test_relaunch_button_real_mode(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    calls: list[bool] = []
    ctx.relaunch = lambda: calls.append(True) or False
    page = window.start_page
    assert page.relaunch_button.isVisibleTo(page)
    page.relaunch_button.click()
    assert calls == [True]
    assert page.admin_label.text() == strings.ADMIN_RELAUNCH_FAILED


def test_admin_status_yes(qtbot: QtBot, tmp_path: Path) -> None:
    ctx = AppContext.create(FakeBackend("healthy_gaming_pc"), get_paths(tmp_path))
    ctx.admin_check = lambda: True
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    assert window.start_page.admin_label.text() == strings.ADMIN_YES
    assert not window.start_page.relaunch_button.isVisibleTo(window.start_page)


class BrokenBackend(FakeBackend):
    def collect(self) -> HardwareSnapshot:
        raise RuntimeError("WMI сломан")


def test_collect_failure_shown(qtbot: QtBot, tmp_path: Path) -> None:
    ctx = AppContext.create(BrokenBackend("healthy_gaming_pc"), get_paths(tmp_path), "x")
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    assert "WMI сломан" in window.start_page.summary_label.text()


def test_summary_cards_show_markup_as_plain_text(qtbot: QtBot, tmp_path: Path) -> None:
    """Имя устройства с HTML показывается как текст, а не как разметка."""
    window, _, _ = make_window(qtbot, tmp_path)
    snap = FakeBackend("healthy_gaming_pc").collect()
    snap.gpus[0].name = "<b>x</b>"
    window.start_page._on_collected(snap)
    labels = [
        label
        for widget in window.start_page.summary_grid.cards
        for label in widget.param_labels
        if "<b>x</b>" in label.text()
    ]
    assert labels and all(lb.textFormat() == Qt.TextFormat.PlainText for lb in labels)


# ---------------------------------------------------------------- 7.3 Режим


def test_full_mode_available_for_everyone(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=False)
    window.go_to("mode")
    page = window.mode_page
    assert page.full.isEnabled()  # версия 2.0: полная проверка доступна всем, без ключа


def test_full_mode_available_with_pro(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, demo=False, pro=True)
    window.go_to("mode")
    page = window.mode_page
    page.full.setChecked(True)
    with qtbot.waitSignal(page.start_requested) as signal:
        page._start()
    assert signal.args == ["full"]


def test_mode_shows_load_warning(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    texts = " ".join(
        label.text() for label in window.mode_page.findChildren(type(window.start_page.admin_label))
    )
    assert "сама остановит тест" in texts


# ---------------------------------------------------------------- 7.4 Прогресс


def test_progress_updates_and_charts(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, time_scale=0.01)
    values: list[int] = []
    window.start_check("quick")
    qtbot.waitUntil(
        lambda: (
            (values.append(window.progress_page.bar.value()) or True)
            and window.current_page_name() == "verdict"
        ),
        timeout=20000,
    )
    assert values == sorted(values)
    assert window.progress_page.gpu_chart.points
    assert window.progress_page.cpu_chart.points
    assert window.progress_page.log.count() == 5


def test_remaining_text() -> None:
    assert remaining_text(60, 0.5) == strings.PROGRESS_REMAINING.format(minutes=1, seconds=0)
    assert remaining_text(0.5, 0.01) == strings.PROGRESS_REMAINING_UNKNOWN


def test_stop_cancels_within_3_seconds(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, time_scale=0.05)  # ~30 с на всю проверку
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.progress_page.bar.value() > 50, timeout=10000)
    started = time.monotonic()
    window.progress_page.stop_button.click()
    assert not window.progress_page.stop_button.isEnabled()
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=4000)
    assert time.monotonic() - started < 3.5
    assert window.verdict_page.stopped_label.isVisibleTo(window.verdict_page)
    verdict = window.last_session.verdict if window.last_session else None
    assert verdict is not None and verdict.not_checked


# ---------------------------------------------------------------- 7.5 Вердикт


def test_verdict_save_and_open_report(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, opened = make_window(qtbot, tmp_path, scenario="worn_ssd")
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    page = window.verdict_page
    assert strings.DECISION_TITLES["negotiate"].upper() in page.banner.text()
    assert "SSD" in page.reasons.text()
    assert page.bargain_card.isVisibleTo(page)
    assert not page.open_button.isEnabled()
    path = page.save_report()
    assert path is not None and path.is_file()
    assert list(ctx.paths.reports.glob("*.pdf")), "рядом с HTML сохраняется PDF"
    assert page.open_button.isEnabled()
    page.open_button.click()
    assert opened == [path]
    assert ctx.history.list()[0].report_path == str(path)


def test_report_available_for_everyone(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    assert window.verdict_page.save_button.isEnabled()  # отчёт доступен всем (версия 2.0)
    assert window.verdict_page.save_report() is not None
    assert len(ctx.history.list()) == 1  # история пишется всегда


# ---------------------------------------------------------------- 7.6 Настройки


def test_settings_page(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    page = window.settings_page
    assert page.thresholds_table.rowCount() == len(load_thresholds().values)
    assert page.thresholds_table.editTriggers() == page.thresholds_table.EditTrigger.NoEditTriggers
    texts = " ".join(
        label.text() for label in page.findChildren(type(window.start_page.admin_label))
    )
    from hwcheck import __version__

    assert "ЖелезоЧек" in texts and __version__ in texts  # версия (в т.ч. кандидат X.Y.Z-rcN)


def test_history_page_lists_and_opens(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, opened = make_window(qtbot, tmp_path, scenario="dying_hdd")
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    window.go_to("history")
    page = window.history_page
    assert page.table.rowCount() == 1
    item = page.table.item(0, 2)
    assert item is not None and item.text() == strings.DECISION_TITLES["walk_away"]
    page.table.selectRow(0)
    path = page.open_selected()  # отчёт ещё не сохраняли — HTML создаётся автоматически
    assert path is not None and path.is_file() and opened == [path]
