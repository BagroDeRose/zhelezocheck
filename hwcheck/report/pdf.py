"""Сохранение отчёта в PDF — без движка браузера (SPEC 1.3, задача 25.4).

PDF собирается `QTextDocument` + `QPdfWriter` из отдельной «печатной» разметки отчёта
(`templates/report_print.html.j2`): QTextDocument понимает только часть HTML и CSS, поэтому
плашка решения и цветные полосы находок сделаны таблицами. Графики рисуются из того же SVG,
что и в HTML-отчёте, модулем QtSvg в картинки PNG и вставляются в документ.

Раньше PDF печатал движок браузера QtWebEngine. Его убрали из программы: он занимал около
200 МБ из 395 МБ сборки и падал на страницах Авито. Сравнение качества — в docs/DECISIONS.md.

Для работы нужен запущенный QApplication (в программе он уже есть, в тестах его даёт pytest-qt).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QMarginsF, QSizeF, QUrl
from PySide6.QtGui import (
    QColor,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)
from PySide6.QtSvg import QSvgRenderer

from hwcheck.models import CheckSession
from hwcheck.report.builder import build_print_html

log = logging.getLogger(__name__)

PDF_DPI = 120  # плотность раскладки: 10 pt читаются как в обычном документе
CHART_SCALE = 3  # графики рисуются в 3 раза крупнее — в PDF они остаются чёткими


def _a4_layout() -> QPageLayout:
    return QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(12, 12, 12, 12),
        QPageLayout.Unit.Millimeter,
    )


def svg_to_image(svg: str, scale: int = CHART_SCALE) -> QImage:
    """SVG-график → картинка (QtSvg, без движка браузера)."""
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    size = renderer.defaultSize()
    image = QImage(size.width() * scale, size.height() * scale, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def pdf_from_print_html(html: str, charts: list[str], path: Path) -> bool:
    """PDF через QTextDocument из печатной разметки (`builder.build_print_html`).

    Графики добавляются в документ картинками `chart_N.png`. True — если файл создан."""
    document = QTextDocument()
    document.setDocumentMargin(0)
    for index, svg in enumerate(charts):
        document.addResource(
            QTextDocument.ResourceType.ImageResource.value,
            QUrl(f"chart_{index}.png"),
            svg_to_image(svg),
        )
    document.setHtml(html)
    writer = QPdfWriter(str(path))
    writer.setPageLayout(_a4_layout())
    writer.setResolution(PDF_DPI)
    writer.setTitle("Отчёт ЖелезоЧек")
    writer.setCreator("ЖелезоЧек")
    page = writer.pageLayout().paintRectPixels(PDF_DPI)
    document.setPageSize(QSizeF(page.width(), page.height()))
    document.print_(writer)
    del writer  # файл дописывается при уничтожении
    return path.is_file() and path.stat().st_size > 0


def save_report_pdf(session: CheckSession, path: Path) -> Path:
    """Сохраняет отчёт о проверке в PDF. Возвращает путь или бросает RuntimeError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    html, charts = build_print_html(session)
    if not pdf_from_print_html(html, charts, path):
        raise RuntimeError("Не удалось сохранить отчёт в PDF")
    log.info("PDF сохранён: %s", path.name)
    return path
