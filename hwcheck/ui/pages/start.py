"""Страница «Старт»: приветствие, права администратора, сводка найденного железа карточками.

Сведения о железе собираются в фоне сразу при открытии — окно при этом не зависает.
"""

from __future__ import annotations

import logging
import time
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwcheck.models import HardwareSnapshot
from hwcheck.platform.elevation import ElevatedProcess
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label
from hwcheck.ui.summary_cards import SummaryCard, build_cards
from hwcheck.ui.widgets.summary_grid import SummaryGrid
from hwcheck.ui.workers import CollectWorker

log = logging.getLogger(__name__)

# Перезапуск с правами: как часто проверять новую копию и через сколько секунд сказать, что
# она запускается дольше обычного (само окно не закрывается, пока копия не отметит «готова»).
RELAUNCH_POLL_MS = 250
RELAUNCH_SLOW_S = 90.0
# Без замка (флешка без записи) готовность копии не узнать — ждём, не упала ли она сразу.
RELAUNCH_NO_LOCK_S = 3.0


def summary_cards(snapshot: HardwareSnapshot) -> list[SummaryCard]:
    """Карточки сводки о железе для показа на старте (задача 22.5)."""
    return build_cards(snapshot)


class StartPage(QWidget):
    """Первая страница проверки."""

    next_requested = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.snapshot: HardwareSnapshot | None = None
        self.worker: CollectWorker | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(title_label(strings.START_TITLE))
        layout.addWidget(text_label(strings.START_INTRO))

        admin = ctx.admin_check()
        self.admin_label = text_label(strings.ADMIN_YES if admin else strings.ADMIN_NO, muted=True)
        self.relaunch_button = QPushButton(strings.ADMIN_RELAUNCH)
        self.relaunch_button.setVisible(not admin and not ctx.is_demo)
        self.relaunch_button.clicked.connect(self._relaunch)
        self._child: ElevatedProcess | None = None
        self._relaunch_timer: QTimer | None = None
        self._relaunch_started = 0.0
        self._token = ""  # одноразовый ключ: копия с правами пишет его в отметку «готова»
        self._child_has_lock = False
        self._slow_noted = False
        self._ready_sent = False
        layout.addWidget(card(self.admin_label, self.relaunch_button))

        # Сводка: строка состояния (идёт сбор / ошибка) и сетка карточек с прокруткой.
        self.summary_label = text_label(strings.COLLECTING, muted=True)
        self.summary_grid = SummaryGrid()
        self.summary_scroll = QScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_scroll.setWidget(self.summary_grid)
        summary = card(title_label(strings.SUMMARY_TITLE), self.summary_label, self.summary_scroll)
        layout.addWidget(summary, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.next_button = QPushButton(strings.NEXT)
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.next_requested.emit)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    def start_collect(self) -> None:
        """Запускает сбор сведений в фоне."""
        self.next_button.setEnabled(False)
        self.summary_label.setText(strings.COLLECTING)
        self.summary_grid.set_cards([])
        self.worker = CollectWorker(self.ctx.backend)
        self.worker.collected.connect(self._on_collected)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_collected(self, snapshot: HardwareSnapshot) -> None:
        log.info("Сведения о железе собраны")
        self.snapshot = snapshot
        self.next_button.setEnabled(True)
        try:
            self.summary_grid.set_cards(summary_cards(snapshot))
            self.summary_label.setText(strings.SUMMARY_HINT)
        except Exception:  # неполные данные не должны ронять окно (задача 15.6)
            log.exception("Не удалось показать сводку")
            self.summary_label.setText(strings.SUMMARY_FAILED)
        self._announce_ready()

    def _on_failed(self, error: str) -> None:
        self.summary_label.setText(strings.COLLECT_FAILED.format(error=escape(error)))
        self.next_button.setEnabled(True)  # проверку можно провести и без сводки
        self._announce_ready()

    def _announce_ready(self) -> None:
        """Копия с правами: окно открыто и собрало сведения — старое окно может закрыться."""
        if not self.ctx.relaunch_token or self._ready_sent:
            return
        self._ready_sent = True
        lock = self.ctx.instance_lock
        if lock is not None:
            lock.mark_ready(self.ctx.relaunch_token)
        log.info("Копия с правами администратора готова: окно открыто, сведения собраны")
        window = self.window()
        window.raise_()
        window.activateWindow()

    def _relaunch(self) -> None:
        """Перезапуск с правами: окно закрывается, только когда новая копия открылась и собрала
        сведения (отметка «готова»). Если копия не стартовала или упала — остаёмся и говорим."""
        self.relaunch_button.setEnabled(False)
        lock = self.ctx.instance_lock
        if lock is not None:
            lock.clear_ready()
            lock.release()  # новая копия займёт замок сразу, без ожидания
        log.info("Перезапуск с правами администратора: запрос")
        self._token = uuid.uuid4().hex
        child = self.ctx.relaunch(self._token)
        if not child:
            log.warning("Перезапуск с правами администратора не начался (отказ в UAC или ошибка)")
            self._relaunch_failed(strings.ADMIN_RELAUNCH_FAILED)
            return
        log.info("Копия с правами администратора запущена, номер процесса %s", child.pid)
        self.admin_label.setText(strings.ADMIN_RELAUNCHING)
        self._child = child
        self._child_has_lock = False
        self._slow_noted = False
        self._relaunch_started = time.monotonic()
        self._relaunch_timer = QTimer(self)
        self._relaunch_timer.setInterval(RELAUNCH_POLL_MS)
        self._relaunch_timer.timeout.connect(self._check_relaunch)
        self._relaunch_timer.start()

    def _check_relaunch(self) -> None:
        child = self._child
        if child is None:
            return
        elapsed = time.monotonic() - self._relaunch_started
        code = child.poll()
        if code is not None:
            hex_code = f"0x{code & 0xFFFFFFFF:08X}"
            log.error(
                "Копия с правами администратора закрылась, не успев открыться "
                "(замок %s), код выхода %s",
                "успела занять" if self._child_has_lock else "не заняла",
                hex_code,
            )
            self._stop_watching()
            self._relaunch_failed(strings.ADMIN_RELAUNCH_DIED.format(code=hex_code))
            return
        lock = self.ctx.instance_lock
        if lock is None:
            ready = elapsed >= RELAUNCH_NO_LOCK_S
        else:
            if not self._child_has_lock and lock.held_by_other():
                self._child_has_lock = True
                log.info("Копия с правами администратора заняла замок — жду, пока она откроется")
            ready = lock.ready_token() == self._token
        if ready:
            log.info("Копия с правами администратора готова — закрываю это окно")
            self._stop_watching()
            QApplication.quit()
        elif not self._slow_noted and elapsed >= RELAUNCH_SLOW_S:
            self._slow_noted = True
            log.warning("Копия с правами администратора не готова уже %.0f с", elapsed)
            self.admin_label.setText(strings.ADMIN_RELAUNCH_SLOW)

    def _stop_watching(self) -> None:
        if self._relaunch_timer is not None:
            self._relaunch_timer.stop()
            self._relaunch_timer = None
        if self._child is not None:
            self._child.close()
            self._child = None

    def _relaunch_failed(self, text: str) -> None:
        lock = self.ctx.instance_lock
        if lock is not None:
            lock.acquire(0)  # эта копия остаётся единственной
        self.admin_label.setText(text)
        self.relaunch_button.setEnabled(True)
