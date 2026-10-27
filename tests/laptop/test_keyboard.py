"""Логика теста клавиатуры: поиск клавиши по скан-коду или коду Qt, итог «не нажималось»."""

from PySide6.QtCore import Qt

from hwcheck.laptop import keyboard
from hwcheck.models import Severity


def test_layout_has_main_keys() -> None:
    labels = {key.label for row in keyboard.LAYOUT for key in row}
    assert {"Esc", "Q", "A", "Z", "Пробел", "Enter", "←", "F12"} <= labels
    assert len({key.scan for row in keyboard.LAYOUT for key in row}) == keyboard.key_count()


def test_find_key_by_scan_code_is_layout_independent() -> None:
    # На русской раскладке клавиша Q даёт «Й», но скан-код тот же — 16.
    key = keyboard.find_key(scan=16, qt_key=ord("Й"))
    assert key is not None and key.label == "Q"


def test_find_key_by_qt_code_when_no_scan() -> None:
    key = keyboard.find_key(scan=0, qt_key=int(Qt.Key.Key_Space))
    assert key is not None and key.label == "Пробел"
    assert keyboard.find_key(scan=0, qt_key=int(Qt.Key.Key_MediaPlay)) is None


def test_session_tracks_missing_keys() -> None:
    session = keyboard.KeyboardTest()
    assert session.press(scan=1, qt_key=0) is not None  # Esc
    session.press(scan=1, qt_key=0)
    assert len(session.pressed) == 1
    # Win проверяется отдельно (25.1) и в список ненажатых не входит.
    assert len(session.missing()) == keyboard.key_count() - 1 - len(keyboard.SEPARATE_KEYS)


def test_all_pressed_is_ok() -> None:
    session = keyboard.KeyboardTest()
    for row in keyboard.LAYOUT:
        for key in row:
            session.press(scan=key.scan, qt_key=0)
    finding, _ = session.finding()
    assert finding.id == "laptop.keyboard_ok" and finding.severity is Severity.OK


def test_missing_keys_listed() -> None:
    session = keyboard.KeyboardTest()
    for row in keyboard.LAYOUT:
        for key in row:
            if key.label not in ("Q", "Пробел"):
                session.press(scan=key.scan, qt_key=0)
    finding, bargain = session.finding()
    assert finding.id == "laptop.keyboard_missing"
    assert finding.severity is Severity.WARNING
    assert "Q" in finding.explanation and "Пробел" in finding.explanation
    assert bargain is not None and "Q" in bargain
