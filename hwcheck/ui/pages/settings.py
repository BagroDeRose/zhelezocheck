"""Страница «Настройки и О программе»: тема, пороги (только просмотр), версия, лицензии."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hwcheck import __version__
from hwcheck.build_config import load_build_config
from hwcheck.thresholds import load_thresholds
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label

THRESHOLDS_HEIGHT = 320
NOTICES_HEIGHT = 260


def short_url(url: str) -> str:
    """https://github.com/BagroDeRose → github.com/BagroDeRose."""
    return url.removeprefix("https://").removeprefix("http://").rstrip("/")


class SettingsPage(QWidget):
    theme_changed = Signal(str)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        # Страница прокручивается целиком: карточки занимают свою высоту и не сжимаются,
        # даже если окно невысокое (замечание v1.2).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        self.scroll_area.setWidget(body)
        outer.addWidget(self.scroll_area)
        layout.addWidget(title_label(strings.SETTINGS_TITLE))

        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem(strings.THEME_LIGHT, "light")
        self.theme.addItem(strings.THEME_DARK, "dark")
        self.theme.setCurrentIndex(1 if ctx.settings.theme == "dark" else 0)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form.addRow(strings.THEME_LABEL, self.theme)
        form_widget = QWidget()
        form_widget.setLayout(form)
        layout.addWidget(card(form_widget))

        thresholds = load_thresholds()
        keys = sorted(thresholds.values)
        self.thresholds_table = QTableWidget(len(keys), len(strings.THRESHOLD_COLUMNS))
        self.thresholds_table.setHorizontalHeaderLabels(strings.THRESHOLD_COLUMNS)
        self.thresholds_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.thresholds_table.verticalHeader().hide()
        self.thresholds_table.setWordWrap(True)
        for row, key in enumerate(keys):
            value = f"{thresholds.values[key]:g} {thresholds.units[key]}".strip()
            for column, text in enumerate((key, value, thresholds.reasons[key])):
                item = QTableWidgetItem(text)
                item.setToolTip(text)  # длинное «Почему так» видно целиком при наведении
                self.thresholds_table.setItem(row, column, item)
        # Последняя колонка растягивается по ширине окна, текст в ней переносится,
        # а высота строк подстраивается под перенесённый текст.
        self.thresholds_table.horizontalHeader().setStretchLastSection(True)
        self.thresholds_table.resizeColumnToContents(0)
        self.thresholds_table.resizeColumnToContents(1)
        self.thresholds_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.thresholds_table.setMinimumHeight(THRESHOLDS_HEIGHT)
        layout.addWidget(card(title_label(strings.THRESHOLDS_TITLE), self.thresholds_table))

        notices = QTextBrowser()
        # В сборке файл лежит рядом с exe, при разработке — в packaging/.
        candidates = [
            ctx.paths.root / "_internal" / "THIRD_PARTY_NOTICES.md",
            ctx.paths.root / "THIRD_PARTY_NOTICES.md",
            ctx.paths.root / "packaging" / "THIRD_PARTY_NOTICES.md",
        ]
        notices_file = next((p for p in candidates if p.is_file()), candidates[0])
        try:
            notices.setMarkdown(notices_file.read_text(encoding="utf-8"))
        except OSError:
            notices.setPlainText("Файл THIRD_PARTY_NOTICES.md не найден.")
        self.about_label = text_label(strings.ABOUT_TEXT.format(version=__version__))
        # Свободная программа (MIT): копирайт строкой, лицензия и компоненты — кнопкой/карточкой.
        self.copyright_label = text_label(strings.ABOUT_COPYRIGHT, muted=True)
        download_url = load_build_config().download_latest
        self.about_download_button = QPushButton(strings.DOWNLOAD_LATEST)
        self.about_download_button.setToolTip(download_url)
        self.about_download_button.clicked.connect(lambda: self.ctx.open_url(download_url))
        self.notices_button = QPushButton(strings.ABOUT_THIRD_PARTY)
        self.notices_button.clicked.connect(lambda: self.show_notices())
        about_row = QHBoxLayout()
        about_row.addWidget(self.about_download_button)
        about_row.addWidget(self.notices_button)
        about_row.addStretch(1)
        about_buttons = QWidget()
        about_buttons.setLayout(about_row)
        layout.addWidget(
            card(
                title_label(strings.ABOUT_TITLE),
                self.about_label,
                self.copyright_label,
                about_buttons,
            )
        )
        layout.addWidget(self._contacts_card())
        notices.setMinimumHeight(NOTICES_HEIGHT)
        self.notices_card = card(title_label(strings.THIRD_PARTY_TITLE), notices)
        layout.addWidget(self.notices_card)
        layout.addStretch(1)

    def show_notices(self) -> None:
        self.scroll_area.ensureWidgetVisible(self.notices_card)

    def _contacts_card(self) -> QWidget:
        """«Контактная информация» (22.1): ссылки — кнопками, открываются только по нажатию."""
        config = load_build_config()
        telegram = short_url(config.contact_telegram)
        self.contacts_label = text_label(
            strings.CONTACTS_TEXT.format(
                telegram="@" + telegram.removeprefix("t.me/") if telegram else "—",
                email=escape(config.contact_email or "—"),
                github=escape(short_url(config.contact_github) or "—"),
                form=strings.CONTACTS_FORM_LINE if config.feedback_form_url else "",
            )
        )
        self.contact_buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout()
        for key, title, url in (
            ("telegram", strings.CONTACTS_TELEGRAM, config.contact_telegram),
            ("github", strings.CONTACTS_GITHUB, config.contact_github),
            ("form", strings.CONTACTS_FORM, config.feedback_form_url),
        ):
            if not url:
                continue
            link = QPushButton(title)
            link.setToolTip(url)
            link.clicked.connect(lambda _checked=False, u=url: self.ctx.open_url(u))
            self.contact_buttons[key] = link
            row.addWidget(link)
        self.email = config.contact_email
        self.copy_email_button = QPushButton(strings.CONTACTS_COPY_EMAIL)
        self.copy_email_button.setEnabled(bool(self.email))
        self.copy_email_button.clicked.connect(lambda: self._copy_email())
        row.addWidget(self.copy_email_button)
        row.addStretch(1)
        buttons = QWidget()
        buttons.setLayout(row)
        # «Скачать последнюю версию» — своей строкой: в одну строку кнопки не помещаются (28.5).
        download = QPushButton(strings.DOWNLOAD_LATEST)
        download.setToolTip(config.download_latest)
        download.clicked.connect(lambda: self.ctx.open_url(config.download_latest))
        self.contact_buttons["download"] = download
        download_row = QHBoxLayout()
        download_row.addWidget(download)
        download_row.addStretch(1)
        download_buttons = QWidget()
        download_buttons.setLayout(download_row)
        hint = text_label(strings.CONTACTS_HINT, muted=True)
        return card(
            title_label(strings.CONTACTS_TITLE),
            self.contacts_label,
            buttons,
            download_buttons,
            hint,
        )

    def _copy_email(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None or not self.email:
            return
        clipboard.setText(self.email)
        self.copy_email_button.setText(strings.CONTACTS_COPIED)
        QTimer.singleShot(
            2000,
            self.copy_email_button,
            lambda: self.copy_email_button.setText(strings.CONTACTS_COPY_EMAIL),
        )

    def _theme_changed(self) -> None:
        theme = str(self.theme.currentData())
        self.ctx.settings.theme = theme
        self.ctx.save_settings()
        self.theme_changed.emit(theme)
