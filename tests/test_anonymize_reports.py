"""Обезличивание отчётов ручной проверки (SPEC 1.1, 15.3): серийные номера → XXXX."""

from pathlib import Path

from scripts import anonymize_reports as anon

QA = Path(__file__).resolve().parent.parent / "docs" / "qa" / "manual_check"


def test_serials_replaced(tmp_path: Path) -> None:
    report = tmp_path / "report.html"
    report.write_text(
        "<td>Серийный номер: WD-WCC4N1234567</td>"
        '<td>"serial_number": "S3Z9NB0K123456X"</td>'
        "<td>S/N ABC123456789</td><td>SerialNumber=PF2K3H4L</td>"
        "<td>Модель: WDC WD10EZEX-22MFCA0</td>",
        encoding="utf-8",
    )
    assert anon.anonymize_file(report) == 4
    text = report.read_text(encoding="utf-8")
    for serial in ("WD-WCC4N1234567", "S3Z9NB0K123456X", "ABC123456789", "PF2K3H4L"):
        assert serial not in text
    assert text.count("XXXX") == 4
    assert "WDC WD10EZEX-22MFCA0" in text  # модель не трогаем


def test_real_manual_check_reports_have_no_serials() -> None:
    for path in QA.glob("*.html"):
        assert anon.find_serials(path.read_text(encoding="utf-8")) == [], path.name
