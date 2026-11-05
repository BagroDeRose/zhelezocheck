"""Тесты страниц интерфейса (задачи 7.2–7.6) на фейковом бэкенде."""

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import get_paths
from hwcheck.models import HardwareSnapshot
from hwcheck.storage.history import HistoryEntry
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


class FakeLock:
    """Замок «одна копия»: что с ним делала страница, занят ли он «другой копией»
    и какой ключ записан в отметке «готова»."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.other = False
        self.ready: str | None = None

    @property
    def active(self) -> bool:
        return True

    def release(self) -> None:
        self.events.append("release")

    def acquire(self, timeout_ms: int = 0) -> bool:
        self.events.append("acquire")
        return True

    def held_by_other(self) -> bool:
        return self.other

    def clear_ready(self) -> None:
        self.events.append("clear")
        self.ready = None

    def mark_ready(self, token: str) -> None:
        self.events.append("ready")
        self.ready = token

    def ready_token(self) -> str | None:
        return self.ready


class FakeChild:
    """Копия с правами: `exit_code` None — работает, число — уже закрылась."""

    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code = exit_code
        self.closed = False
        self.pid = 4242

    def poll(self) -> int | None:
        return self.exit_code

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def quits(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    from hwcheck.ui.pages import start

    calls: list[bool] = []
    monkeypatch.setattr(start, "RELAUNCH_POLL_MS", 10)
    monkeypatch.setattr(start.QApplication, "quit", lambda: calls.append(True))
    return calls


def test_relaunch_refused_keeps_window(qtbot: QtBot, tmp_path: Path, quits: list[bool]) -> None:
    """Отказ в окне UAC: окно остаётся, замок возвращается этой копии, кнопку можно нажать ещё."""
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    lock = FakeLock()
    ctx.instance_lock = lock  # type: ignore[assignment]  # подмена замка
    ctx.relaunch = lambda token: None
    page = window.start_page
    assert page.relaunch_button.isVisibleTo(page)
    page.relaunch_button.click()
    assert page.admin_label.text() == strings.ADMIN_RELAUNCH_FAILED
    assert lock.events == ["clear", "release", "acquire"]
    assert page.relaunch_button.isEnabled() and quits == []


def test_relaunch_child_died_keeps_window(qtbot: QtBot, tmp_path: Path, quits: list[bool]) -> None:
    """Копия с правами сразу закрылась: это окно не закрывается и показывает код выхода."""
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    lock = FakeLock()
    child = FakeChild(exit_code=0xC0000005)
    ctx.instance_lock = lock  # type: ignore[assignment]
    ctx.relaunch = lambda token: child
    page = window.start_page
    page.relaunch_button.click()
    qtbot.waitUntil(lambda: page.relaunch_button.isEnabled(), timeout=3000)
    assert "0xC0000005" in page.admin_label.text()
    assert lock.events == ["clear", "release", "acquire"] and child.closed and quits == []


def test_relaunch_child_died_after_taking_lock(
    qtbot: QtBot, tmp_path: Path, quits: list[bool]
) -> None:
    """Копия заняла замок, но упала до того, как открылось окно: это окно остаётся (так и было
    на i7-3770 — копия падала уже после замка, а старое окно к тому времени закрывалось)."""
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    lock = FakeLock()
    child = FakeChild()
    ctx.instance_lock = lock  # type: ignore[assignment]
    ctx.relaunch = lambda token: child
    page = window.start_page
    page.relaunch_button.click()
    lock.other = True  # копия заняла замок…
    qtbot.wait(100)
    assert quits == []  # …но этого мало: ждём, пока она откроет окно и соберёт сведения
    child.exit_code = 1
    qtbot.waitUntil(lambda: page.relaunch_button.isEnabled(), timeout=3000)
    assert "0x00000001" in page.admin_label.text() and quits == []


def test_relaunch_quits_when_child_is_ready(
    qtbot: QtBot, tmp_path: Path, quits: list[bool]
) -> None:
    """Окно закрывается только тогда, когда копия с правами отметила «готова» нашим ключом."""
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    lock = FakeLock()
    child = FakeChild()
    tokens: list[str] = []
    ctx.instance_lock = lock  # type: ignore[assignment]
    ctx.relaunch = lambda token: tokens.append(token) or child
    page = window.start_page
    page.relaunch_button.click()
    assert page.admin_label.text() == strings.ADMIN_RELAUNCHING
    assert len(tokens) == 1 and len(tokens[0]) >= 16  # ключ одноразовый и непредсказуемый
    lock.other = True
    lock.ready = "чужой"  # отметка от прошлого перезапуска не считается
    qtbot.wait(100)
    assert quits == []
    lock.ready = tokens[0]
    qtbot.waitUntil(lambda: quits == [True], timeout=3000)
    assert child.closed and lock.events == ["clear", "release"]


def test_relaunch_slow_child_keeps_waiting(
    qtbot: QtBot, tmp_path: Path, quits: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Копия долго не готова: окно не закрывается само, а объясняет, что происходит."""
    from hwcheck.ui.pages import start

    monkeypatch.setattr(start, "RELAUNCH_SLOW_S", 0.05)
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    ctx.instance_lock = FakeLock()  # type: ignore[assignment]
    child = FakeChild()
    ctx.relaunch = lambda token: child
    page = window.start_page
    page.relaunch_button.click()
    qtbot.waitUntil(lambda: page.admin_label.text() == strings.ADMIN_RELAUNCH_SLOW, timeout=3000)
    assert quits == []


def test_relaunched_copy_marks_ready_after_collect(qtbot: QtBot, tmp_path: Path) -> None:
    """Копия с правами (--relaunched КЛЮЧ) отмечает «готова», когда окно собрало сведения."""
    ctx = AppContext.create(FakeBackend("healthy_gaming_pc", time_scale=0.002), get_paths(tmp_path))
    ctx.admin_check = lambda: True
    ctx.relaunch_token = "k42"
    lock = FakeLock()
    ctx.instance_lock = lock  # type: ignore[assignment]
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: lock.ready is not None, timeout=5000)
    assert lock.ready == "k42" and lock.events == ["ready"]


def test_normal_start_does_not_mark_ready(qtbot: QtBot, tmp_path: Path) -> None:
    """Обычный запуск (без --relaunched) отметку «готова» не пишет."""
    window, ctx, _ = make_window(qtbot, tmp_path, demo=False)
    lock = FakeLock()
    ctx.instance_lock = lock  # type: ignore[assignment]
    window.start_page.start_collect()
    qtbot.waitUntil(lambda: window.start_page.next_button.isEnabled(), timeout=5000)
    assert lock.events == []


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


def test_mode_choice_is_exclusive(qtbot: QtBot, tmp_path: Path) -> None:
    """Можно выбрать только один режим: «Быстрая» и «Полная» не отмечаются одновременно."""
    window, _, _ = make_window(qtbot, tmp_path, demo=False)
    window.go_to("mode")
    page = window.mode_page
    page.show()
    qtbot.mouseClick(page.full, Qt.MouseButton.LeftButton)
    assert page.full.isChecked() and not page.quick.isChecked()
    assert page.selected_mode() == "full"
    qtbot.mouseClick(page.quick, Qt.MouseButton.LeftButton)
    assert page.quick.isChecked() and not page.full.isChecked()
    assert page.selected_mode() == "quick"


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


class SlowHistory:
    """История на медленной флешке: каждое чтение — полсекунды; помнит, из какого потока."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def list(self, limit: int = 200) -> list[HistoryEntry]:
        self.calls.append(threading.get_ident())
        time.sleep(0.5)
        return [HistoryEntry("id1", "2026-11-01T00:24:00", "quick", "buy", "ПК", "", None)]


def test_history_refresh_does_not_block_window(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Журнал владельца (01.11.2026): открытие базы истории на флешке заняло 3,3 с прямо в
    потоке окна — при переключении вкладок программа «думала». Теперь история читается в фоне,
    а частые переключения не запускают чтение заново, пока идёт предыдущее."""
    slow = SlowHistory()
    monkeypatch.setattr(AppContext, "history", property(lambda self: slow))
    window, _, _ = make_window(qtbot, tmp_path)
    page = window.history_page
    started = time.monotonic()
    for _ in range(5):  # быстрые переключения туда-обратно
        window.go_to("history")
        window.go_to("laptop")
    window.go_to("history")
    assert time.monotonic() - started < 0.3  # окно не ждёт флешку
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=5000)
    qtbot.waitUntil(lambda: not page.loading, timeout=5000)
    assert threading.get_ident() not in slow.calls  # не в потоке окна
    assert len(slow.calls) <= 2  # одно чтение и, самое большее, одно повторное


def test_history_page_lists_and_opens(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, opened = make_window(qtbot, tmp_path, scenario="dying_hdd")
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    window.go_to("history")
    page = window.history_page
    qtbot.waitUntil(lambda: page.table.rowCount() == 1, timeout=5000)  # история читается в фоне
    item = page.table.item(0, 2)
    assert item is not None and item.text() == strings.DECISION_TITLES["walk_away"]
    page.table.selectRow(0)
    path = page.open_selected()  # отчёт ещё не сохраняли — HTML создаётся автоматически
    assert path is not None and path.is_file() and opened == [path]
