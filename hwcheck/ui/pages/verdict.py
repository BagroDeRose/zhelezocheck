"""Страница «Вердикт»: крупно решение, причины по важности, аргументы для торга,
что не проверено, кнопки «Сохранить отчёт» и «Открыть отчёт».

Бесплатная версия (docs/FREE_VS_PRO.md, задача 22.6): решение и краткий список главных причин;
критические находки — всегда целиком, с объяснением и советом. Подробные объяснения
остальных находок, аргументы для торга, сведения тестов ноутбука и отчёт — в Pro, на их месте
плашка «Доступно в Pro».
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwcheck.laptop.details import laptop_details
from hwcheck.models import CheckSession, Severity, TestStatus
from hwcheck.report.builder import report_file_name, save_html
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
        advice = f"<br><i>Что делать:</i> {escape(f.advice)}" if f.advice else ""
        blocks.append(f"<p>{head}<br>{escape(f.explanation)}{advice}</p>")
    return "".join(blocks) or "<p>Проблем не найдено.</p>"


def bullet_html(items: list[str]) -> str:
    return "<br>".join(f"• {escape(item)}" for item in items)


class VerdictPage(QWidget):
    new_check_requested = Signal()
    report_saved = Signal(str)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.session: CheckSession | None = None
        self.report_path: Path | None = None

        outer = QVBoxLayout(self)
        self.banner = QLabel()
        self.banner.setMinimumHeight(80)
        outer.addWidget(self.banner)
        self.stopped_label = text_label(strings.VERDICT_STOPPED, muted=True)
        outer.addWidget(self.stopped_label)

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
        outer.addWidget(scroll, 1)

        self.status_label = text_label("", muted=True)
        outer.addWidget(self.status_label)
        buttons = QHBoxLayout()
        self.new_button = QPushButton(strings.NEW_CHECK)
        self.new_button.clicked.connect(self.new_check_requested.emit)
        buttons.addWidget(self.new_button)
        buttons.addStretch(1)
        self.save_button = QPushButton(strings.SAVE_REPORT)
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save_report)
        self.open_button = QPushButton(strings.OPEN_REPORT)
        self.open_button.clicked.connect(self.open_report)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.open_button)
        outer.addLayout(buttons)

    def show_session(self, session: CheckSession) -> None:
        self.session = session
        self.report_path = None
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

    def save_report(self) -> Path | None:
        """Сохраняет HTML и PDF в папку отчётов на флешке и обновляет историю."""
        if self.session is None:
            return None
        try:
            html_path = save_html(self.session, self.ctx.paths.reports)
            pdf_path = self.ctx.paths.reports / f"{report_file_name(self.session)}.pdf"
            try:
                save_report_pdf(self.session, pdf_path)
            except RuntimeError as error:
                log.warning("PDF не создан: %s", error)
            self.ctx.history.save(self.session, report_path=html_path)
        except (OSError, sqlite3.Error) as error:
            self.status_label.setText(strings.REPORT_FAILED.format(error=escape(str(error))))
            return None
        self.report_path = html_path
        self.open_button.setEnabled(True)
        self.status_label.setText(strings.REPORT_SAVED.format(path=escape(str(html_path))))
        self.report_saved.emit(str(html_path))
        return html_path

    def open_report(self) -> None:
        if self.report_path is not None:
            self.ctx.open_path(self.report_path)
