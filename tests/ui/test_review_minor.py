"""Мелкие замечания ревью 12.2."""

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from hwcheck.backends.fake import FakeBackend
from hwcheck.config import get_paths
from hwcheck.models import HardwareSnapshot
from hwcheck.report import builder
from hwcheck.stress import sensors
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.ui.context import AppContext
from hwcheck.ui.main_window import MainWindow
from tests.report.helpers import demo_session
from tests.ui.helpers import make_window


def test_history_finds_report_after_drive_letter_change(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, opened = make_window(qtbot, tmp_path, pro=True)
    session = demo_session("worn_ssd")
    report = builder.save_html(session, ctx.paths.reports)
    report.write_text("ОТЧЁТ С ФЛЕШКИ", encoding="utf-8")  # метка: файл не должен пересоздаться
    ctx.history.save(session, report_path=Path("Z:/старая_буква") / report.name)
    window.go_to("history")
    window.history_page.table.selectRow(0)
    assert window.history_page.open_selected() == report
    assert opened == [report]
    assert report.read_text(encoding="utf-8") == "ОТЧЁТ С ФЛЕШКИ"  # открыт, а не пересоздан


def test_chart_limit_from_thresholds() -> None:
    session = demo_session("mining_gpu")
    base = load_thresholds()
    custom = Thresholds(
        values={**base.values, "gpu.warning_c": 50.0},
        reasons=base.reasons,
        units=base.units,
        durations=base.durations,
    )
    assert builder.build_charts(session, custom) != builder.build_charts(session, base)


def test_pawnio_path_follows_windir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drivers = tmp_path / "System32" / "drivers"
    drivers.mkdir(parents=True)
    (drivers / "PawnIO.sys").write_bytes(b"")
    monkeypatch.setenv("WINDIR", str(tmp_path))
    available, reason = sensors.cpu_temperature_support()
    assert not available
    assert "LibreHardwareMonitor" in reason  # драйвер найден в папке Windows из WINDIR


class SlowBackend(FakeBackend):
    def collect(self) -> HardwareSnapshot:
        time.sleep(5)
        return super().collect()


def test_close_during_collection_does_not_crash(qtbot: QtBot, tmp_path: Path) -> None:
    ctx = AppContext.create(SlowBackend("healthy_gaming_pc"), get_paths(tmp_path), "demo")
    window = MainWindow(ctx)
    window.show()
    window.start_page.start_collect()
    started = time.monotonic()
    window.close()
    assert time.monotonic() - started < 1.5  # окно не ждёт сбор сведений
    assert not window.isVisible()
    worker = window.start_page.worker
    assert worker is not None
    qtbot.waitUntil(lambda: worker.isFinished(), timeout=10000)
