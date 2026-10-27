"""Главное окно: слева навигация, справа страницы. Здесь же — порядок проверки:
Старт → Режим → Прогресс → Вердикт."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from hwcheck.models import CheckSession
from hwcheck.session import plan_steps
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.keyboard_guard import KeyboardGuard
from hwcheck.ui.pages.common import escape
from hwcheck.ui.pages.history import HistoryPage
from hwcheck.ui.pages.laptop import LaptopPage
from hwcheck.ui.pages.listing import ListingPage
from hwcheck.ui.pages.mode import ModePage
from hwcheck.ui.pages.progress import ProgressPage
from hwcheck.ui.pages.settings import SettingsPage
from hwcheck.ui.pages.start import StartPage
from hwcheck.ui.pages.verdict import VerdictPage
from hwcheck.ui.theme import apply_theme
from hwcheck.ui.workers import CheckWorker

log = logging.getLogger(__name__)

FLOW_PAGES = ("start", "mode", "progress", "verdict")


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.worker: CheckWorker | None = None
        self.last_session: CheckSession | None = None
        self.flow_page = "start"
        self.setWindowTitle(strings.WINDOW_TITLE)
        self.resize(1100, 760)

        self.pages: dict[str, QWidget] = {}
        self.stack = QStackedWidget()
        self.start_page = StartPage(ctx)
        self.mode_page = ModePage(ctx)
        self.progress_page = ProgressPage()
        self.verdict_page = VerdictPage(ctx)
        self.history_page = HistoryPage(ctx)
        self.settings_page = SettingsPage(ctx)
        self.listing_page = ListingPage(ctx)
        self.laptop_page = LaptopPage(ctx)
        # Сверка объявления с железом — по сведениям, собранным на стартовой странице (25.4).
        self.listing_page.snapshot_provider = lambda: self.start_page.snapshot
        # Вопрос «Да/Нет»; в тестах и самопроверке подменяется (без окна сообщения).
        self.confirm: Callable[[str, str], bool] = self.ask_yes_no
        # Alt+F4, Alt и F10 во время теста клавиатуры не закрывают окно и не открывают меню.
        self.keyboard_guard = KeyboardGuard(self.laptop_page.keyboard)
        app = QApplication.instance()
        if app is not None:
            guard = self.keyboard_guard
            app.installNativeEventFilter(guard)
            self.destroyed.connect(lambda: app.removeNativeEventFilter(guard))
        for name, page in (
            ("start", self.start_page),
            ("mode", self.mode_page),
            ("progress", self.progress_page),
            ("verdict", self.verdict_page),
            ("history", self.history_page),
            ("listing", self.listing_page),
            ("laptop", self.laptop_page),
            ("settings", self.settings_page),
        ):
            self.add_page(name, page)

        # Навигация слева: пункт → страница (для «Проверки» — текущий шаг проверки).
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        # Без фокуса клавиатуры у меню нет пунктирной рамки вокруг пункта (замечание 15.4).
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_targets: list[str] = []
        self.add_nav(strings.NAV_CHECK, "check")
        self.add_nav(strings.NAV_LISTING, "listing")
        self.add_nav(strings.NAV_LAPTOP, "laptop")
        self.add_nav(strings.NAV_HISTORY, "history")
        self.add_nav(strings.NAV_SETTINGS, "settings")
        self.nav.currentRowChanged.connect(self._nav_changed)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        if ctx.is_demo:
            badge = QLabel(strings.DEMO_BADGE.format(scenario=ctx.demo_scenario))
            badge.setObjectName("badge")
            content_layout.addWidget(badge)
        self.readonly_banner = QLabel(strings.READONLY_STICK)
        self.readonly_banner.setObjectName("badge")
        self.readonly_banner.setWordWrap(True)
        self.readonly_banner.setVisible(ctx.read_only)
        content_layout.addWidget(self.readonly_banner)
        content_layout.addWidget(self.stack, 1)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.nav)
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.start_page.next_requested.connect(lambda: self.go_to("mode"))
        self.mode_page.back_requested.connect(lambda: self.go_to("start"))
        self.mode_page.start_requested.connect(self.start_check)
        self.progress_page.stop_requested.connect(self.stop_check)
        self.verdict_page.new_check_requested.connect(self.new_check)
        self.verdict_page.report_saved.connect(lambda _path: self.history_page.refresh())
        self.settings_page.theme_changed.connect(self.apply_theme)

        self.nav.setCurrentRow(0)
        self.go_to("start")

    # -- страницы и навигация ----------------------------------------------

    def add_page(self, name: str, page: QWidget) -> None:
        self.pages[name] = page
        self.stack.addWidget(page)

    def add_nav(self, title: str, target: str) -> None:
        self.nav.addItem(title)
        self.nav_targets.append(target)

    def current_page_name(self) -> str:
        current = self.stack.currentWidget()
        return next(name for name, page in self.pages.items() if page is current)

    def go_to(self, name: str) -> None:
        if name in FLOW_PAGES:
            self.flow_page = name
            row = self.nav_targets.index("check")
        else:
            row = self.nav_targets.index(name) if name in self.nav_targets else -1
        if name == "history":
            self.history_page.refresh()
        if name == "mode":
            self.mode_page.refresh()
        if name == "laptop":
            self.laptop_page.refresh()
        if name == "listing":
            self.listing_page.refresh()
        self.stack.setCurrentWidget(self.pages[name])
        if row >= 0 and self.nav.currentRow() != row:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(row)
            self.nav.blockSignals(False)

    def _nav_changed(self, row: int) -> None:
        if 0 <= row < len(self.nav_targets):
            target = self.nav_targets[row]
            self.go_to(self.flow_page if target == "check" else target)

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)

    # -- проверка -------------------------------------------------------------

    def start_check(self, mode: str) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        steps = plan_steps(self.ctx.backend, mode)
        planned = sum(step.duration for step in steps) * self.ctx.backend.time_scale
        self.progress_page.set_charts_allowed(True)
        self.progress_page.begin(planned_total_s=planned)
        self.go_to("progress")
        listing = self.mode_page.listing_to_use()
        self.worker = CheckWorker(
            self.ctx.backend,
            mode,
            self.start_page.snapshot,
            self.ctx.demo_scenario,
            listing,
            list(self.ctx.manual_findings.values()),
        )
        self.worker.progress.connect(self.progress_page.on_progress)
        self.worker.sample.connect(self.progress_page.on_sample)
        self.worker.step_done.connect(self.progress_page.on_step_done)
        self.worker.finished_check.connect(self._check_finished)
        self.worker.failed.connect(self._check_failed)
        self.worker.start()

    def stop_check(self) -> None:
        if self.worker is not None:
            self.worker.cancel()

    def _check_finished(self, session: CheckSession) -> None:
        self.last_session = session
        try:
            self.ctx.history.save(session)
        except (OSError, sqlite3.Error) as error:
            # Ошибка истории не должна прятать вердикт.
            log.warning("Не удалось сохранить историю: %s", error)
        self.verdict_page.show_session(session)
        self.go_to("verdict")

    def _check_failed(self, error: str) -> None:
        self.progress_page.step_label.setText(escape(error))
        self.progress_page.stop_button.setEnabled(False)

    def new_check(self) -> None:
        # Результаты тестов ноутбука относятся к прошлому компьютеру — сбрасываем.
        self.ctx.manual_findings.clear()
        self.laptop_page.clear_results()
        self.go_to("start")
        self.start_page.start_collect()

    def is_checking(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def ask_yes_no(self, title: str, text: str) -> bool:
        """Вопрос «Да/Нет» пользователю (окно Windows)."""
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — имя метода Qt
        keyboard = self.laptop_page.keyboard
        if keyboard.running:
            # Во время теста клавиатуры окно закрывается только после подтверждения (25.1).
            if keyboard.alt_f4_recent() or not self.confirm(
                strings.KEYBOARD_CLOSE_TITLE, strings.KEYBOARD_CLOSE_CONFIRM
            ):
                event.ignore()
                return
            keyboard.stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(4000)
        super().closeEvent(event)
