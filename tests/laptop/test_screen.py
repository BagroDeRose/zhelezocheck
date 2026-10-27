"""Логика теста экрана: последовательность цветов и находка по ответу пользователя."""

from hwcheck.laptop import screen
from hwcheck.models import Severity


def test_sequence_of_colors() -> None:
    test = screen.ScreenTest()
    names = []
    while not test.finished:
        names.append(test.current.key)
        test.advance()
    assert names == ["black", "white", "red", "green", "blue", "gradient"]
    test.advance()  # лишние нажатия ничего не ломают
    assert test.finished


def test_defects_reported_is_critical() -> None:
    finding, bargain = screen.screen_finding(defects=True)
    assert finding.id == "laptop.screen_defects"
    assert finding.severity is Severity.CRITICAL
    assert bargain is None


def test_no_defects_is_ok() -> None:
    finding, _ = screen.screen_finding(defects=False)
    assert finding.id == "laptop.screen_ok" and finding.severity is Severity.OK
