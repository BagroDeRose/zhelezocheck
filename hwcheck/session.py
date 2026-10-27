"""Проверка целиком: собрать сведения о железе → прогнать нагрузочные тесты → вердикт.

Этот модуль связывает бэкенд, движок тестов и пороги. Им пользуются и консольная команда
`run`, и графический интерфейс, чтобы порядок проверки был одинаковым.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime

from hwcheck import __version__
from hwcheck.backends.base import ALL_STRESS_TESTS, HardwareBackend
from hwcheck.listing.analyze import listing_findings
from hwcheck.models import CheckSession, Finding, HardwareSnapshot, ListingClaims
from hwcheck.stress.engine import ProgressFn, SampleFn, StepDoneFn, StressEngine, StressStep
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.verdict.engine import decide

MODES = ("quick", "full", "short")


def plan_steps(
    backend: HardwareBackend,
    mode: str,
    thresholds: Thresholds | None = None,
    only: list[str] | None = None,
) -> list[StressStep]:
    """Шаги проверки для режима: все доступные тесты в стандартном порядке."""
    th = thresholds or load_thresholds()
    available = set(backend.available_stress_tests())
    names = [name for name in ALL_STRESS_TESTS if name in available]
    if only:
        names = [name for name in names if name in only]
    return [StressStep(name, th.duration(mode, name)) for name in names]


def run_check(
    backend: HardwareBackend,
    mode: str,
    cancel_event: threading.Event,
    on_progress: ProgressFn | None = None,
    on_sample: SampleFn | None = None,
    on_step_done: StepDoneFn | None = None,
    on_collected: Callable[[HardwareSnapshot], None] | None = None,
    only: list[str] | None = None,
    demo_scenario: str = "",
    snapshot: HardwareSnapshot | None = None,
    listing: ListingClaims | None = None,
    manual_findings: list[tuple[Finding, str | None]] | None = None,
) -> CheckSession:
    """Выполняет проверку и возвращает сеанс с результатами."""
    if mode not in MODES:
        raise ValueError(f"Неизвестный режим «{mode}»")
    session = CheckSession(
        id=str(uuid.uuid4()),
        started_at=datetime.now().isoformat(timespec="seconds"),
        mode=mode,
        demo_scenario=demo_scenario,
        app_version=__version__,
    )
    session.snapshot = snapshot or backend.collect()
    if on_collected:
        on_collected(session.snapshot)
    engine = StressEngine(
        backend, on_progress=on_progress, on_sample=on_sample, on_step_done=on_step_done
    )
    steps = plan_steps(backend, mode, only=only)
    session.results = engine.run(steps, cancel_event)
    session.listing = listing
    session.verdict = decide(
        session.snapshot,
        session.results,
        claimed_ram_gb=listing.ram_gb if listing else None,
        extra_findings=(listing_findings(listing, session.snapshot) if listing else [])
        + list(manual_findings or []),
        expected_tests=[step.name for step in steps],
    )
    session.finished_at = datetime.now().isoformat(timespec="seconds")
    return session
