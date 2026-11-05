"""PDF и JSON-экспорт со скрытием идентификаторов (этап 48 v2.1)."""

import base64
import json
import re
from pathlib import Path

from PySide6.QtGui import QTextDocument, QTextTable
from pytestqt.qtbot import QtBot

from hwcheck import schema
from hwcheck.collectors import disks
from hwcheck.models import CheckSession, ListingClaims
from hwcheck.report import builder, pdf
from hwcheck.report.privacy import HIDDEN, mask_identifiers
from tests.helpers import fixture_json
from tests.report.helpers import demo_session


def session_with_identifiers() -> CheckSession:
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.system is not None and session.snapshot.memory is not None
    session.snapshot.system.computer_name = "DESKTOP-SELLER01"
    session.snapshot.memory.modules[0].serial_number = "MEMSERIAL123"
    session.snapshot.disks[0] = disks.parse_smartctl(
        fixture_json("smartctl", "sata_ssd_healthy.json")
    )
    session.snapshot.disks[0].serial_number = "DISKSERIAL456"
    session.listing = ListingClaims(
        title="RTX 3060", seller_name="Иван", url="https://example.test/1"
    )
    return session


# ---------------------------------------------------------------- скрытие идентификаторов


def test_mask_identifiers_hides_and_keeps_original() -> None:
    session = session_with_identifiers()
    masked = mask_identifiers(session)
    text = masked.to_json()
    for secret in ("DESKTOP-SELLER01", "MEMSERIAL123", "DISKSERIAL456", "Иван"):
        assert secret not in text, secret
    assert masked.snapshot.system is not None and masked.snapshot.system.computer_name == HIDDEN
    # Исходная проверка не изменилась (история хранит настоящие данные).
    assert session.snapshot.system is not None
    assert session.snapshot.system.computer_name == "DESKTOP-SELLER01"
    # Остальное — на месте: модели, замеры, вердикт.
    assert masked.snapshot.disks[0].model == session.snapshot.disks[0].model
    assert [len(r.samples) for r in masked.results] == [len(r.samples) for r in session.results]


def test_empty_identifiers_stay_empty() -> None:
    """Пустое поле не превращается в «скрыто» — нечего было скрывать."""
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.system is not None
    session.snapshot.system.computer_name = ""  # имя компьютера не прочиталось
    masked = mask_identifiers(session)
    assert masked.snapshot.system is not None and masked.snapshot.system.computer_name == ""


def test_placeholder_serial_is_not_hidden() -> None:
    """Ручная проверка rc2: заглушка «00000000» превращалась в «скрыто», и отчёт не мог
    показать «Не указано производителем». Настоящие номера по-прежнему скрываются."""
    session = demo_session("healthy_gaming_pc")
    assert session.snapshot.memory is not None
    session.snapshot.memory.modules[0].serial_number = "00000000"
    session.snapshot.memory.modules[1].serial_number = "MEMSERIAL789"
    masked = mask_identifiers(session)
    assert masked.snapshot.memory is not None
    assert [m.serial_number for m in masked.snapshot.memory.modules] == ["00000000", HIDDEN]
    html = builder.build_html(masked, mode="specialist")
    start = html.index("DIMM_A2: серийный номер")
    assert "Не указано производителем" in html[start : html.index("</tr>", start)]


# ---------------------------------------------------------------- JSON


def _embedded_json(html: str) -> dict:
    match = re.search(
        r'href="data:application/json;base64,([A-Za-z0-9+/=]+)" download="([^"]+)"', html
    )
    assert match, "нет ссылки «Скачать полный JSON»"
    assert match.group(2).endswith(".json")
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))


def test_html_has_full_json_download_and_it_is_masked() -> None:
    session = session_with_identifiers()
    html = builder.build_html(mask_identifiers(session))
    assert "Скачать полный JSON" in html
    data = _embedded_json(html)
    restored = schema.load_session(json.dumps(data))
    assert len(restored.results) == len(session.results)
    assert sum(len(r.samples) for r in restored.results) == sum(
        len(r.samples) for r in session.results
    )
    assert "DESKTOP-SELLER01" not in json.dumps(data, ensure_ascii=False)
    assert "DESKTOP-SELLER01" not in html


def test_save_report_files_hide_by_default(tmp_path: Path, qtbot: QtBot) -> None:
    session = session_with_identifiers()
    html_path = builder.save_html(session, tmp_path)
    json_path = builder.save_json(session, tmp_path)
    for path in (html_path, json_path):
        text = path.read_text(encoding="utf-8")
        assert "MEMSERIAL123" not in text and "DESKTOP-SELLER01" not in text, path.name
    restored = schema.load_session(json_path.read_text(encoding="utf-8"))
    assert restored.id == session.id
    shown = builder.save_json(session, tmp_path / "open", hide_identifiers=False)
    assert "MEMSERIAL123" in shown.read_text(encoding="utf-8")


# ---------------------------------------------------------------- PDF


def test_print_html_is_full_and_masked(qtbot: QtBot) -> None:
    html, charts = builder.build_print_html(mask_identifiers(session_with_identifiers()))
    assert "ТОРГОВАТЬСЯ" in html or "БРАТЬ" in html
    assert "Паспорт проверки" in html and "Что проверить перед оплатой" in html
    assert "<svg" not in html and charts
    for index in range(len(charts)):
        assert f'src="chart_{index}.png"' in html
    assert "DISKSERIAL456" not in html and "Current" in html  # полный SMART тоже в PDF


def test_big_tables_repeat_header_on_each_page(qtbot: QtBot) -> None:
    html, _ = builder.build_print_html(demo_session("healthy_gaming_pc"))
    document = QTextDocument()
    document.setHtml(html)
    tables = [
        frame for frame in document.rootFrame().childFrames() if isinstance(frame, QTextTable)
    ]
    big = [t for t in tables if t.rows() > 10]
    assert big and all(t.format().headerRowCount() >= 1 for t in big)


def test_pdf_file_with_charts(qtbot: QtBot, tmp_path: Path) -> None:
    path = pdf.save_report_pdf(session_with_identifiers(), tmp_path / "report.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 20000
    assert b"MEMSERIAL123" not in data
