"""Режим самопроверки сборки: демо-проверка до вердикта, сохранение отчёта, выход с кодом 0."""

from pathlib import Path

from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from hwcheck import __main__ as entry
from hwcheck.ui.smoke import run_smoke_test
from tests.ui.helpers import make_window


def test_smoke_test_passes(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="mining_gpu")
    window.show()  # как в собранной программе: тест клавиатуры шлёт сообщения окну
    code = run_smoke_test(window, timeout_s=30)
    assert code == 0
    assert list(ctx.paths.reports.glob("*.html")) and list(ctx.paths.reports.glob("*.pdf"))
    log = (ctx.paths.logs / "smoke_test.txt").read_text(encoding="utf-8")
    assert "OK" in log and "negotiate" in log
    assert "Графики для PDF (QtSvg): рисуются" in log  # 25.4: PDF без движка браузера
    assert "Объявление из файла: разобрано" in log  # 22.2: сохранённая страница
    assert "Объявление из текста: разобрано" in log
    if QGuiApplication.platformName() == "windows":  # 25.1: настоящее окно Windows
        assert "Alt+F4 в тесте клавиатуры: окно не закрылось, F4 засчитана" in log
        assert "Закрытие окна во время теста: спрошено подтверждение" in log
    assert window.isVisible() and not window.laptop_page.keyboard.running


def test_smoke_test_timeout(qtbot: QtBot, tmp_path: Path) -> None:
    window, ctx, _ = make_window(qtbot, tmp_path, time_scale=1.0)  # «настоящее» время — не успеет
    assert run_smoke_test(window, timeout_s=1) == 1
    assert "FAIL" in (ctx.paths.logs / "smoke_test.txt").read_text(encoding="utf-8")


def test_smoke_flag_requires_demo() -> None:
    args = entry.parse_args(["--smoke-test"])
    assert args.smoke_test and args.demo == ""
    assert entry.parse_args(["--demo", "worn_ssd", "--smoke-test"]).demo == "worn_ssd"


def test_smoke_runs_worker_check_when_given(qtbot: QtBot, tmp_path: Path) -> None:
    from hwcheck.models import TestResult, TestStatus

    calls: list[int] = []

    def fake_cpu() -> TestResult:
        calls.append(1)
        return TestResult(name="cpu_load", status=TestStatus.PASSED, metrics={"workers": 2})

    window, ctx, _ = make_window(qtbot, tmp_path)
    assert run_smoke_test(window, timeout_s=30, worker_check=fake_cpu) == 0
    assert calls == [1]
    assert "Процессы нагрузки: работают" in (ctx.paths.logs / "smoke_test.txt").read_text(
        encoding="utf-8"
    )


def test_smoke_fails_when_workers_broken(qtbot: QtBot, tmp_path: Path) -> None:
    from hwcheck.models import TestResult, TestStatus

    window, _, _ = make_window(qtbot, tmp_path)
    broken = TestResult(name="cpu_load", status=TestStatus.ERROR, notes=["нет процессов"])
    assert run_smoke_test(window, timeout_s=30, worker_check=lambda: broken) == 1


def test_smoke_reports_keyboard_check_honestly_without_real_window(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """Без настоящего окна Windows (offscreen) самопроверка пишет «не проверялся», а не «OK»."""
    window, ctx, _ = make_window(qtbot, tmp_path, scenario="mining_gpu")
    window.show()
    run_smoke_test(window, timeout_s=30)
    log = (ctx.paths.logs / "smoke_test.txt").read_text(encoding="utf-8")
    if QGuiApplication.platformName() != "windows":
        assert "Alt+F4 в тесте клавиатуры: не проверялся (нет настоящего окна Windows)" in log
