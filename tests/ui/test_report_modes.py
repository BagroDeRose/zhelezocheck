"""Переключатель режимов отчёта в интерфейсе (этап 47 v2.1): «Для покупателя» и «Для
специалиста» из одного снимка, без повторных тестов; сохранённый отчёт открывается в
выбранном режиме."""

import re
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QRadioButton, QWidget
from pytestqt.qtbot import QtBot

from hwcheck.models import CheckSession
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow
from tests.ui.helpers import make_window


def finished_window(qtbot: QtBot, tmp_path: Path) -> tuple[MainWindow, AppContext, list[Path]]:
    window, ctx, opened = make_window(qtbot, tmp_path)
    window.start_check("quick")
    qtbot.waitUntil(lambda: window.current_page_name() == "verdict", timeout=20000)
    return window, ctx, opened


def test_mode_switch_is_exclusive_and_buyer_by_default(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    assert page.buyer_radio.isChecked() and not page.specialist_radio.isChecked()
    page.specialist_radio.click()
    assert page.specialist_radio.isChecked() and not page.buyer_radio.isChecked()


def test_specialist_view_from_same_snapshot(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    assert page.session is not None
    before = page.session.to_json()
    page.specialist_radio.click()
    assert page.views.currentWidget() is page.specialist_view
    text = page.specialist_view.toPlainText()
    assert "Паспорт проверки" in text and "Источник" in text
    page.buyer_radio.click()
    assert page.views.currentWidget() is page.buyer_view
    assert page.session.to_json() == before  # переключение не запускало тестов


def test_saved_report_opens_in_chosen_mode(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, opened = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    page.specialist_radio.click()
    path = page.save_report()
    assert path is not None
    html = path.read_text(encoding="utf-8")
    assert re.search(r'id="mode-specialist"[^>]*checked', html)
    page.buyer_radio.click()
    page.open_report()
    assert opened[-1] == path
    assert re.search(r'id="mode-buyer"[^>]*checked', path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- этап 48: экспорт


def test_settings_hide_identifiers_default_and_saved(qtbot: QtBot, tmp_path: Path) -> None:
    from hwcheck.storage.settings import load_settings

    window, ctx, _ = make_window(qtbot, tmp_path)
    box = window.settings_page.hide_identifiers
    assert box.isChecked() and ctx.settings.hide_identifiers  # по умолчанию — скрывать
    box.click()
    assert ctx.settings.hide_identifiers is False
    assert load_settings(ctx.paths.settings_file).hide_identifiers is False


def test_saving_report_writes_json_and_respects_setting(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    assert page.session is not None and page.session.snapshot.system is not None
    page.session.snapshot.system.computer_name = "DESKTOP-SELLER01"
    html = page.save_report()
    assert html is not None
    json_file = html.with_suffix(".json")
    assert json_file.is_file()
    for path in (html, json_file):
        assert "DESKTOP-SELLER01" not in path.read_text(encoding="utf-8"), path.name
    window.settings_page.hide_identifiers.click()  # показывать идентификаторы
    page.save_report()
    assert "DESKTOP-SELLER01" in json_file.read_text(encoding="utf-8")


def _indicator_center(image: QImage, button: QRadioButton) -> QColor:
    """Цвет в центре индикатора переключателя на снимке родителя."""
    x, y = button.x() + 2 + 8, button.y() + button.height() // 2
    ratio = image.devicePixelRatio()
    return image.pixelColor(int(x * ratio), int(y * ratio))


def _near(a: QColor, b: QColor) -> bool:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) < 60


def test_radio_indicator_readable_in_both_themes(qtbot: QtBot) -> None:
    """Выбранный пункт переключателя — точка цвета акцента, невыбранный — пустое кольцо.

    Нативный индикатор Windows в тёмной теме рисовал невыбранный пункт сплошной белой точкой,
    а выбранный — кольцом, и было непонятно, какой режим включён (этап 50 v2.1)."""
    from hwcheck.ui.theme import COLORS, stylesheet

    for theme in ("light", "dark"):
        box = QWidget()
        box.setStyleSheet(stylesheet(theme))
        qtbot.addWidget(box)
        checked, unchecked = QRadioButton("а", box), QRadioButton("б", box)
        checked.setAutoExclusive(False)
        unchecked.setAutoExclusive(False)
        checked.setChecked(True)
        unchecked.move(0, 40)
        box.resize(120, 80)
        box.show()
        qtbot.waitExposed(box)
        image = box.grab().toImage()
        accent, panel = QColor(COLORS[theme]["accent"]), QColor(COLORS[theme]["panel"])
        on, off = _indicator_center(image, checked), _indicator_center(image, unchecked)
        assert _near(on, accent), (theme, on.name())
        assert _near(off, panel), (theme, off.name())


def test_save_button_writes_in_background(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ручная проверка 2.1.0-rc1: при сохранении окно замирало на 2,3–2,9 с (запись PDF и
    истории на флешку в потоке окна). Теперь файлы пишутся в фоне, окно отвечает."""
    from hwcheck.ui.pages import verdict as verdict_module

    window, _ctx, _ = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    threads: list[str] = []
    real_pdf = verdict_module.save_report_pdf

    def slow_pdf(session: CheckSession, path: Path, hide_identifiers: bool = True) -> Path:
        threads.append(threading.current_thread().name)
        time.sleep(0.5)
        return real_pdf(session, path, hide_identifiers)

    monkeypatch.setattr(verdict_module, "save_report_pdf", slow_pdf)
    start = time.monotonic()
    page.save_button.click()
    assert time.monotonic() - start < 0.3, "кнопка не должна ждать записи файлов"
    assert not page.save_button.isEnabled()  # повторное нажатие во время записи невозможно
    assert page.status_label.text() == strings.REPORT_SAVING
    qtbot.waitUntil(page.open_button.isEnabled, timeout=20000)
    assert threads and threads[0] != threading.main_thread().name
    assert page.report_path is not None and page.report_path.is_file()
    assert page.save_button.isEnabled()


def test_background_save_of_old_check_does_not_touch_new_one(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пока пишутся файлы, пользователь открыл другую проверку — её экран не трогаем."""
    from hwcheck.ui.pages import verdict as verdict_module

    window, _ctx, _ = finished_window(qtbot, tmp_path)
    page = window.verdict_page
    first = page.session
    assert first is not None
    release = threading.Event()
    real_pdf = verdict_module.save_report_pdf

    def waiting_pdf(session: CheckSession, path: Path, hide_identifiers: bool = True) -> Path:
        release.wait(10)
        return real_pdf(session, path, hide_identifiers)

    monkeypatch.setattr(verdict_module, "save_report_pdf", waiting_pdf)
    page.save_button.click()
    second = CheckSession.from_json(first.to_json())
    second.id = "другая-проверка"
    page.show_session(second)
    release.set()
    qtbot.waitUntil(page.save_button.isEnabled, timeout=20000)
    qtbot.wait(200)
    assert page.report_path is None and not page.open_button.isEnabled()
