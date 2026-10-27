"""Тесты исправлений по итогам ручной проверки (SPEC 1.1, этап 15)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView
from pytestqt.qtbot import QtBot

from hwcheck.models import HardwareSnapshot
from hwcheck.ui.theme import COLORS, stylesheet
from hwcheck.ui.widgets.keyboard_view import KeyboardView
from tests.ui.helpers import make_window

# ---------------------------------------------------------------- 15.4 рамка фокуса


def test_nav_has_no_focus_rectangle(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    assert window.nav.focusPolicy() == Qt.FocusPolicy.NoFocus
    for theme in ("light", "dark"):
        assert "QListWidget#nav::item:focus" in stylesheet(theme)
        assert "outline: none" in stylesheet(theme)


# ---------------------------------------------------------------- 15.5 тёмная тема


def test_dark_theme_styles_tables_and_combobox() -> None:
    css = stylesheet("dark")
    for selector in (
        "QHeaderView::section",
        "QTableCornerButton::section",
        "QTableWidget::item:selected",
        "QComboBox QAbstractItemView",
        "QComboBox",
    ):
        assert selector in css, selector
    # Заголовки таблиц — на цвете панели темы, а не системном белом.
    header = css.split("QHeaderView::section")[1].split("}")[0]
    assert "#2b2d31" in header or "#25272b" in header


def test_threshold_reasons_wrap_and_have_tooltips(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    table = window.settings_page.thresholds_table
    assert table.wordWrap()
    reason = table.item(0, 2)
    assert reason is not None
    assert reason.toolTip() == reason.text()
    assert table.verticalHeader().isHidden()
    mode = table.verticalHeader().sectionResizeMode(0)
    assert mode == QHeaderView.ResizeMode.ResizeToContents


# ---------------------------------------------------------------- 15.6 сводка не падает


def test_summary_error_does_not_break_start_page(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hwcheck.ui import strings
    from hwcheck.ui.pages import start

    def broken(_snapshot: object) -> list[object]:
        raise KeyError("нет поля")

    monkeypatch.setattr(start, "summary_cards", broken)
    window, _, _ = make_window(qtbot, tmp_path)
    assert window.start_page.summary_label.text() == strings.SUMMARY_FAILED
    assert window.start_page.next_button.isEnabled()


def test_summary_handles_empty_fields() -> None:
    from hwcheck.models import DiskInfo, GpuInfo
    from hwcheck.ui.pages.start import summary_cards

    snapshot = HardwareSnapshot(collected_at="", is_admin=True)
    snapshot.disks = [DiskInfo(model="", device="")]
    snapshot.gpus = [GpuInfo(name="")]
    assert summary_cards(snapshot)


# ---------------------------------------------------------------- 15.7 сводка и отчёт


def _laptop_snapshot() -> HardwareSnapshot:
    from hwcheck.models import DiskInfo, GpuInfo

    snapshot = HardwareSnapshot(collected_at="", is_admin=False)
    snapshot.gpus = [GpuInfo(vendor="AMD", name="AMD Radeon(TM) Graphics", vram_mb=512)]
    snapshot.disks = [DiskInfo(model="Накопитель без названия (/dev/sdb)", device="/dev/sdb")]
    return snapshot


def test_summary_shows_shared_memory_and_unknown_size() -> None:
    from hwcheck.ui.pages.start import summary_cards

    text = " | ".join(card.plain_text() for card in summary_cards(_laptop_snapshot()))
    assert "Модель: AMD Radeon(TM) Graphics; Видеопамять: общая с ОЗУ" in text
    assert "0 ГБ" not in text
    assert "Модель: Накопитель без названия (/dev/sdb); Объём: не определено" in text


def test_report_rows_for_integrated_gpu() -> None:
    from hwcheck.models import CheckSession
    from hwcheck.report.builder import _gpu_rows

    rows = _gpu_rows(CheckSession(snapshot=_laptop_snapshot()))
    assert rows[0]["vram"] == "общая с ОЗУ"


# ---------------------------------------------------------------- 15.10 оценка времени


def _seconds(text: str) -> int:
    import re

    match = re.search(r"(\d+) мин (\d+) с", text)
    assert match, text
    return int(match.group(1)) * 60 + int(match.group(2))


def test_remaining_estimate_never_grows(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from hwcheck.ui.pages import progress

    clock = {"now": 1000.0}
    monkeypatch.setattr(progress.time, "monotonic", lambda: clock["now"])
    page = progress.ProgressPage()
    qtbot.addWidget(page)
    page.begin(planned_total_s=600)
    shown = []
    # Первые шаги идут быстрее плана, потом медленнее — оценка всё равно не растёт.
    for elapsed, fraction in ((1, 0.03), (3, 0.05), (60, 0.10), (200, 0.30), (500, 0.60)):
        clock["now"] = 1000.0 + elapsed
        page.on_progress(fraction, "cpu_load")
        shown.append(_seconds(page.remaining_label.text()))
    assert shown == sorted(shown, reverse=True)
    assert shown[0] == 582  # 600 × (1 − 0.03) — по плану, а не «1 секунда»


def test_main_window_passes_planned_duration(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.start_check("quick")
    # Быстрая проверка ≈ 570 «секунд» плана × масштаб времени тестового бэкенда.
    assert 0 < window.progress_page.planned_total_s < 5
    window.stop_check()
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=5000)


# ---------------------------------------------------------------- 15.11 клавиатура


def _press(
    view: KeyboardView,
    key: Qt.Key,
    scan: int,
    native_mods: int,
    mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        int(key),
        mods,
        scan,
        0,
        native_mods,
    )
    view.keyPressEvent(event)


def test_right_ctrl_and_alt_are_recognized(qtbot: QtBot, tmp_path: Path) -> None:
    from hwcheck.ui.widgets.keyboard_view import EXTENDED_KEY_FLAG

    view = KeyboardView()
    qtbot.addWidget(view)
    # Qt под Windows сообщает правые Ctrl/Alt тем же скан-кодом, что и левые,
    # а «правость» — флагом расширенной клавиши в nativeModifiers.
    _press(view, Qt.Key.Key_Control, 0x1D, EXTENDED_KEY_FLAG)
    _press(view, Qt.Key.Key_Alt, 0x38, EXTENDED_KEY_FLAG)
    assert view.is_lit("Ctrl ") and view.is_lit("Alt ")
    assert not view.is_lit("Ctrl") and not view.is_lit("Alt")
    _press(view, Qt.Key.Key_Control, 0x1D, 0)
    assert view.is_lit("Ctrl")


def test_alt_f4_during_keyboard_test_does_not_close(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path, pro=True)
    window.show()
    page = window.laptop_page
    page.start_keyboard_test()
    _press(page.keyboard, Qt.Key.Key_F4, 0x3E, 0, Qt.KeyboardModifier.AltModifier)
    window.close()
    assert window.isVisible()
    assert page.keyboard.is_lit("F4")


# ---------------------------------------------------------------- 15.12 блок «Ноутбук»


def test_verdict_and_report_show_laptop_block(qtbot: QtBot, tmp_path: Path) -> None:
    from hwcheck.report.builder import build_html

    window, _, _ = make_window(qtbot, tmp_path, scenario="laptop_worn_battery", pro=True)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=15000)
    page = window.verdict_page
    assert page.laptop_card.isVisibleTo(page)
    assert "износ" in page.laptop.text() and "Клавиатура" in page.laptop.text()
    assert page.session is not None
    html = build_html(page.session)
    assert "<h2>Ноутбук</h2>" in html and "Клавиатура" in html


def test_verdict_hides_laptop_block_for_desktop(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=15000)
    assert not window.verdict_page.laptop_card.isVisibleTo(window.verdict_page)


# ---------------------------------------------------------------- v1.2: 22.3 прокрутка, 22.4 фокус


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_scrollbars_are_thin_and_without_arrows(theme: str) -> None:
    css = stylesheet(theme)
    for selector in (
        "QScrollBar:vertical",
        "QScrollBar:horizontal",
        "QScrollBar::handle:vertical",
        "QScrollBar::handle:horizontal",
        "QScrollBar::add-line",
        "QScrollBar::sub-line",
    ):
        assert selector in css, selector
    handle = css.split("QScrollBar::handle:vertical")[1].split("}")[0]
    assert "border-radius" in handle
    arrows = css.split("QScrollBar::add-line")[1].split("}")[0]
    assert "height: 0" in arrows and "width: 0" in arrows


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_focus_is_shown_by_theme_not_dotted_frame(theme: str) -> None:
    css = stylesheet(theme)
    for selector in ("QPushButton:focus", "QCheckBox:focus", "QRadioButton:focus",
                     "QComboBox:focus", "QLineEdit:focus"):  # fmt: skip
        assert selector in css, selector
    button_focus = css.split("QPushButton:focus")[1].split("}")[0]
    assert "outline: none" in button_focus and "border" in button_focus


def test_buttons_stay_keyboard_focusable(qtbot: QtBot, tmp_path: Path) -> None:
    """Доступность не ломаем: кнопки по-прежнему получают фокус с клавиатуры."""
    from PySide6.QtWidgets import QPushButton

    window, _, _ = make_window(qtbot, tmp_path)
    buttons = window.findChildren(QPushButton)
    assert buttons and all(b.focusPolicy() != Qt.FocusPolicy.NoFocus for b in buttons)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_inputs_follow_theme(theme: str) -> None:
    """Поле ключа (QPlainTextEdit) в тёмной теме не должно оставаться белым (22.4)."""
    css = stylesheet(theme)
    block = css.split("QPlainTextEdit, QTextEdit {")[1].split("}")[0]
    assert COLORS[theme]["panel"] in block


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_disabled_primary_button_looks_disabled(theme: str) -> None:
    """Выключенная главная кнопка не должна выглядеть нажимаемой (22.6, «Сохранить отчёт»)."""
    css = stylesheet(theme)
    block = css.split("QPushButton#primary:disabled {")[1].split("}")[0]
    assert COLORS[theme]["accent"] not in block and COLORS[theme]["muted"] in block
