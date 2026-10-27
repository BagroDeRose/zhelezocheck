"""PDF отчёта без движка браузера (SPEC 1.3, 25.4): QTextDocument + QtSvg."""

from pathlib import Path

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from hwcheck.report import builder, pdf
from tests.report.helpers import demo_session


def test_pdf_from_session(qtbot: QtBot, tmp_path: Path) -> None:
    path = pdf.save_report_pdf(demo_session("mining_gpu"), tmp_path / "a" / "report.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000


def test_print_html_has_charts_as_images(qtbot: QtBot) -> None:
    html, charts = builder.build_print_html(demo_session("overheating_cpu"))
    assert charts and all(chart.startswith("<svg") for chart in charts)
    for index in range(len(charts)):
        assert f'src="chart_{index}.png"' in html
    assert "<svg" not in html  # QTextDocument SVG в разметке не рисует — только картинки
    assert "ТОРГОВАТЬСЯ" in html


def test_chart_svg_becomes_image(qtbot: QtBot) -> None:
    svg = builder.svg_line_chart([(0.0, 40.0), (60.0, 72.0)], "Температура", "°C")
    image = pdf.svg_to_image(svg)
    assert isinstance(image, QImage) and not image.isNull()
    width, height = builder.CHART_SIZE
    assert image.width() == width * pdf.CHART_SCALE and image.height() == height * pdf.CHART_SCALE
    # На картинке есть не только белый фон: линия графика нарисована.
    colors = {
        image.pixel(x, y) for x in range(0, image.width(), 7) for y in range(0, image.height(), 7)
    }
    assert len(colors) > 3


def test_no_webengine_imported(qtbot: QtBot) -> None:
    """Движок браузера программе больше не нужен (сборка меньше на ~200 МБ)."""
    import sys

    from hwcheck.ui.main_window import MainWindow  # noqa: F401 — загружаем все страницы

    assert not [name for name in sys.modules if name.startswith("PySide6.QtWebEngine")]
