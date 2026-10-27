"""Построение детерминированных сеансов проверки для тестов отчёта."""

import threading

from hwcheck.backends.fake import FakeBackend
from hwcheck.models import CheckSession
from hwcheck.session import run_check


def demo_session(scenario: str) -> CheckSession:
    session = run_check(FakeBackend(scenario), "quick", threading.Event(), demo_scenario=scenario)
    session.id = "00000000-1111-2222-3333-444444444444"
    session.started_at = "2026-10-05T12:00:00"
    session.finished_at = "2026-10-05T12:10:00"
    session.app_version = "0.0.0-test"
    return session
