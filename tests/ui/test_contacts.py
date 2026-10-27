"""Настройки → «Контактная информация» (SPEC 1.2, задача 22.1)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from hwcheck import __version__
from hwcheck.build_config import BuildConfig, load_build_config
from hwcheck.ui import strings
from tests.ui.helpers import make_window


def test_contacts_come_from_build_config() -> None:
    config = load_build_config()
    assert config.contact_telegram == "https://t.me/BagroDeRose"
    assert config.contact_email == "bagroderose@gmail.com"
    assert config.contact_github == "https://github.com/BagroDeRose"
    assert config.feedback_form_url.startswith("https://forms.gle/")


def test_links_open_only_on_click(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path)
    opened: list[str] = []
    ctx.open_url = opened.append
    page = window.settings_page
    assert opened == []  # ничего не открывается само
    page.contact_buttons["telegram"].click()
    page.contact_buttons["github"].click()
    page.contact_buttons["form"].click()
    assert opened == [
        "https://t.me/BagroDeRose",
        "https://github.com/BagroDeRose",
        load_build_config().feedback_form_url,
    ]
    assert "bagroderose@gmail.com" in page.contacts_label.text()


def test_copy_email(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    page = window.settings_page
    page.copy_email_button.click()
    clipboard = QApplication.clipboard()
    assert clipboard is not None and clipboard.text() == "bagroderose@gmail.com"
    assert page.copy_email_button.text() == strings.CONTACTS_COPIED


def test_empty_form_link_is_hidden(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hwcheck.ui.pages import settings

    monkeypatch.setattr(
        settings,
        "load_build_config",
        lambda: BuildConfig(contact_telegram="https://t.me/x", contact_email="a@b.c"),
    )
    window, _, _ = make_window(qtbot, tmp_path)
    page = window.settings_page
    assert "form" not in page.contact_buttons and "github" not in page.contact_buttons
    assert "Форма" not in page.contacts_label.text()


def test_about_shows_version(qtbot: QtBot, tmp_path: Path) -> None:
    window, _, _ = make_window(qtbot, tmp_path)
    assert __version__ in window.settings_page.about_label.text()


def test_download_latest_link_in_contacts_and_about(qtbot: QtBot, tmp_path: Path) -> None:
    """SPEC 1.3, 28.5: «Скачать последнюю версию» — постоянная ссылка GitHub, по нажатию."""
    from hwcheck.build_config import DEFAULT_DOWNLOAD

    window, ctx, _ = make_window(qtbot, tmp_path)
    opened: list[str] = []
    ctx.open_url = opened.append
    page = window.settings_page
    assert DEFAULT_DOWNLOAD.endswith("/zhelezocheck/releases/latest")
    page.contact_buttons["download"].click()
    page.about_download_button.click()
    assert opened == [DEFAULT_DOWNLOAD, DEFAULT_DOWNLOAD]
    assert page.about_download_button.text() == "Скачать последнюю версию"


def test_download_button_has_own_row(qtbot: QtBot, tmp_path: Path) -> None:
    """28.5: «Скачать последнюю версию» — своей строкой, чтобы кнопки контактов не раздвигали
    страницу вширь (горизонтальная прокрутка; проверено скриншотом settings_*.png)."""
    window, _, _ = make_window(qtbot, tmp_path)
    buttons = window.settings_page.contact_buttons
    assert buttons["download"].parent() is not buttons["telegram"].parent()
