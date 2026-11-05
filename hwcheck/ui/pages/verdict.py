"""Страница «Вердикт»: крупно решение, причины по важности, аргументы для торга,
что не проверено, кнопки «Сохранить отчёт» и «Открыть отчёт».

С 2.1 — переключатель режимов «Для покупателя / Для специалиста» (SPEC_V2_1, этап 47): оба
вида строятся из одного снимка проверки, переключение тестов не запускает. Вид специалиста в
окне — таблицы паспорта и разделов (графики — в HTML-отчёте). Сохранённый отчёт открывается
в выбранном режиме; второй режим — переключателем в самом отчёте.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hwcheck.laptop.details import laptop_details
from hwcheck.models import CheckSession, Severity, TestStatus
from hwcheck.report.builder import (
    build_inapp_specialist_html,
    report_file_name,
    save_html,
    save_json,
)
from hwcheck.report.pdf import save_report_pdf
from hwcheck.ui import strings
from hwcheck.ui.context import AppContext
from hwcheck.ui.pages.common import card, escape, text_label, title_label
from hwcheck.ui.theme import DECISION_COLORS, SEVERITY_COLORS

log = logging.getLogger(__name__)


def findings_html(session: CheckSession) -> str:
    """Причины вердикта: каждая находка целиком, с советом «что делать»."""
    verdict = session.verdict
    if verdict is None:
        return ""
    blocks = []
    for f in verdict.findings:
        if f.severity is Severity.OK:
            continue
        color = SEVERITY_COLORS[f.severity.value]
        tag = strings.SEVERITY_NAMES[f.severity.value]
        head = f'<span style="color:{color}"><b>{tag}:</b></span> <b>{escape(f.title)}</b>'
        impact = f"<br><i>Для покупки:</i> {escape(f.impact)}" if f.impact else ""
        advice = f"<br><i>Что делать:</i> {escape(f.advice)}" if f.advice else ""
        blocks.append(f"<p>{head}<br>{escape(f.explanation)}{impact}{advice}</p>")
    return "".join(blocks) or "<p>Проблем не найдено.</p>"


def bullet_html(items: list[str]) -> str:
    return "<br>".join(f"• {escape(item)}" for item in items)


class VerdictPage(QWidget):
    new_check_requested = Signal()
    report_saved = Signal(str)
    _written = Signal(str, object, str)  # из фона: номер проверки, путь (или None), ошибка

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.session: CheckSession | None = None
        self.report_path: Path | None = None
        self.report_mode = "buyer"

        outer = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setMinimumHeight(80)
        outer.addWidget(self.banner)
        self.stopped_label = text_label(strings.VERDICT_STOPPED, muted=True)
        outer.addWidget(self.stopped_label)

        # Режим отчёта: обе кнопки — в общей группе (они в одной строке, но так надёжнее).
        modes = QHBoxLayout()
        self.buyer_radio = QRadioButton(strings.REPORT_MODE_BUYER)
        self.specialist_radio = QRadioButton(strings.REPORT_MODE_SPECIALIST)
        self.buyer_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for radio in (self.buyer_radio, self.specialist_radio):
            self.mode_group.addButton(radio)
            modes.addWidget(radio)
        modes.addStretch(1)
        self.buyer_radio.toggled.connect(self._mode_changed)
        outer.addLayout(modes)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        self.reasons = text_label()
        self.good = text_label()
        self.bargain = text_label()
        self.not_checked = text_label()
        self.laptop = text_label()
        self.laptop_card = card(title_label(strings.VERDICT_LAPTOP), self.laptop)
        self.bargain_card = card(title_label(strings.VERDICT_BARGAIN), self.bargain)
        layout.addWidget(card(title_label(strings.VERDICT_REASONS), self.reasons))
        layout.addWidget(self.bargain_card)
        layout.addWidget(self.laptop_card)
        layout.addWidget(card(title_label(strings.VERDICT_NOT_CHECKED), self.not_checked))
        layout.addWidget(card(title_label(strings.VERDICT_GOOD), self.good))
        layout.addStretch(1)
        scroll.setWidget(body)
        self.buyer_view = scroll
        self.specialist_view = QTextBrowser()
        self.specialist_view.setOpenLinks(False)
        self.views = QStackedWidget()
        self.views.addWidget(self.buyer_view)
        self.views.addWidget(self.specialist_view)
        outer.addWidget(self.views, 1)

        self.status_label = text_label("", muted=True)
        outer.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.new_button = QPushButton(strings.NEW_CHECK)
        self.new_button.clicked.connect(self.new_check_requested.emit)
        buttons.addWidget(self.new_button)
        buttons.addStretch(1)
        self.save_button = QPushButton(strings.SAVE_REPORT)
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save_report_in_background)
        self._written.connect(self._report_written)
        self.open_button = QPushButton(strings.OPEN_REPORT)
        self.open_button.clicked.connect(self.open_report)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.open_button)
        outer.addLayout(buttons)

    def _mode_changed(self) -> None:
        """Переключение вида: только перерисовка из того же снимка, без тестов."""
        self.report_mode = "buyer" if self.buyer_radio.isChecked() else "specialist"
        if self.report_mode == "specialist" and self.session is not None:
            self.specialist_view.setHtml(build_inapp_specialist_html(self.session))
            self.views.setCurrentWidget(self.specialist_view)
        else:
            self.views.setCurrentWidget(self.buyer_view)

    def show_session(self, session: CheckSession) -> None:
        self.session = session
        self.report_path = None
        self.specialist_view.clear()
        self._mode_changed()
        verdict = session.verdict
        decision = verdict.decision.value if verdict else "negotiate"
        color = DECISION_COLORS[decision]
        summary = escape(verdict.summary) if verdict else ""
        self.banner.setText(
            f'<div style="background:{color}; color:white; padding:14px;">'
            f'<span style="font-size:30px; font-weight:700;">'
            f"{strings.DECISION_TITLES[decision].upper()}</span><br>{summary}</div>"
        )
        stopped = any(
            r.metrics.get("cancelled")
            or (r.status is TestStatus.SKIPPED and any("остановлен" in n for n in r.notes))
            for r in session.results
        )
        self.stopped_label.setVisible(stopped)
        self.reasons.setText(findings_html(session))
        good = [
            f"{f.title}. {f.explanation}"
            for f in (verdict.findings if verdict else [])
            if f.severity is Severity.OK
        ]
        self.good.setText(bullet_html(good) or "—")
        points = verdict.bargaining_points if verdict else []
        self.bargain.setText(bullet_html(points))
        self.bargain_card.setVisible(bool(points))
        laptop = laptop_details(session)
        self.laptop.setText(
            "<br>".join(f"<b>{escape(label)}:</b> {escape(text)}" for label, text in laptop)
        )
        self.laptop_card.setVisible(bool(laptop))
        missing = verdict.not_checked if verdict else []
        self.not_checked.setText(bullet_html(missing) or strings.VERDICT_NOTHING_MISSED)
        self.save_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.status_label.setText("")

    def _write_report(self, session: CheckSession, mode: str, hide: bool) -> Path:
        """Пишет HTML, JSON и PDF и обновляет историю. Окно не трогает — можно в фоне."""
        folder = self.ctx.paths.reports
        html_path = save_html(session, folder, mode, hide)
        save_json(session, folder, hide)
        pdf_path = folder / f"{report_file_name(session)}.pdf"
        try:
            save_report_pdf(session, pdf_path, hide)
        except RuntimeError as error:
            log.warning("PDF не создан: %s", error)
        self.ctx.history.save(session, report_path=html_path)
        return html_path

    def _report_written(self, session_id: str, html_path: Path | None, error: str) -> None:
        """Итог записи (в потоке окна): ссылка на отчёт или сообщение об ошибке."""
        self.save_button.setEnabled(self.session is not None)
        if self.session is None or self.session.id != session_id:
            return  # пока писались файлы, открыли другую проверку — её экран не трогаем
        if html_path is None:
            self.status_label.setText(strings.REPORT_FAILED.format(error=escape(error)))
            return
        self.report_path = html_path
        self.open_button.setEnabled(True)
        self.status_label.setText(strings.REPORT_SAVED.format(path=escape(str(html_path))))
        self.report_saved.emit(str(html_path))

    def save_report(self) -> Path | None:
        """Сохраняет отчёт и ждёт окончания записи (самопроверка сборки и тесты)."""
        if self.session is None:
            return None
        session = self.session
        try:
            path = self._write_report(session, self.report_mode, self.ctx.settings.hide_identifiers)
        except (OSError, sqlite3.Error) as error:
            self._report_written(session.id, None, str(error))
            return None
        self._report_written(session.id, path, "")
        return path

    def save_report_in_background(self) -> None:
        """Кнопка «Сохранить отчёт»: файлы пишутся в фоновом потоке, окно не замирает.

        Ручная проверка 2.1.0-rc1: запись PDF и истории на флешку занимала 2,3–2,9 с в
        потоке окна. Итог приходит в окно сигналом — Qt доставит его в поток окна. Поток не
        фоновый для Python (daemon=False): при закрытии программы запись дописывается."""
        if self.session is None:
            return
        session, mode, hide = self.session, self.report_mode, self.ctx.settings.hide_identifiers
        self.save_button.setEnabled(False)
        self.status_label.setText(strings.REPORT_SAVING)

        def finish(path: Path | None, error: str) -> None:
            try:
                self._written.emit(session.id, path, error)
            except RuntimeError:
                log.info("Окно закрыто до конца записи отчёта: %s", path or error)

        def work() -> None:
            try:
                path = self._write_report(session, mode, hide)
            except (OSError, sqlite3.Error, RuntimeError) as error:
                log.warning("Отчёт не сохранён: %s", error)
                finish(None, str(error))
                return
            finish(path, "")

        threading.Thread(target=work, name="report-save", daemon=False).start()

    def open_report(self) -> None:
        """Открывает отчёт в выбранном сейчас режиме (файл перезаписывается без тестов)."""
        if self.report_path is None or self.session is None:
            return
        try:
            save_html(
                self.session,
                self.report_path.parent,
                self.report_mode,
                self.ctx.settings.hide_identifiers,
            )
        except OSError as error:  # флешка только для чтения — открываем как сохранили
            log.warning("Режим отчёта не переключён: %s", error)
        self.ctx.open_path(self.report_path)
