"""Тесты обёртки memtest_vulkan: разбор вывода и управление запуском (без реального GPU)."""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hwcheck.models import TestStatus
from hwcheck.stress import vram
from tests.helpers import fixture_text


def _parse(name: str) -> vram.MemtestOutput:
    parser = vram.MemtestParser()
    for line in fixture_text("memtest", name).splitlines():
        parser.feed(line)
    return parser.result


def test_parse_pass() -> None:
    out = _parse("pass_single.txt")
    assert out.version == "0.5.0"
    assert [(d.index, d.device_id, d.vram_gb) for d in out.devices] == [(1, "2503", 12)]
    assert out.tested_device == 1
    assert out.iterations == 5995
    assert out.seconds == 150.0151
    assert out.write_speed_gbps == 236.6
    assert out.read_speed_gbps == 286.7
    assert out.errors == 0
    assert out.passed is True and out.failed is False
    assert out.waiting_for_key is True
    assert out.init_error is None


def test_parse_errors() -> None:
    out = _parse("errors.txt")
    assert out.errors == 0x20 + 0x1A
    assert out.failed is True and out.passed is False
    assert len(out.error_lines) == 2
    assert out.iterations == 13


def test_parse_init_incompatible_driver() -> None:
    out = _parse("init_incompatible_driver.txt")
    assert out.init_error is not None and "INCOMPATIBLE_DRIVER" in out.init_error
    assert out.iterations == 0


def test_parse_init_library_failed() -> None:
    out = _parse("init_library_failed.txt")
    assert out.init_error is not None and "library failed to load" in out.init_error


def test_parse_multi_gpu() -> None:
    out = _parse("multi_gpu.txt")
    assert [d.device_id for d in out.devices] == ["4680", "2206"]
    assert out.tested_device == 2
    assert out.iterations == 58
    assert out.passed is False and out.failed is False  # тест прерван до итога — это нормально


def test_choose_device() -> None:
    out = _parse("multi_gpu.txt")
    assert vram.choose_device(out.devices, "2206") == 2
    # Код не совпал или неизвестен — берётся отдельная видеокарта, а не первая в списке
    # (первой обычно стоит встроенная графика; задача 22.7).
    assert vram.choose_device(out.devices, "ffff") == 2
    assert vram.choose_device(out.devices, None) == 2
    assert vram.choose_device(out.devices, "4680") == 2  # код встроенной — тоже не она


def test_choose_device_never_picks_integrated() -> None:
    out = _parse("igpu_only.txt")
    assert [d.name for d in out.devices] == ["AMD Radeon(TM) Graphics"]
    assert vram.choose_device(out.devices, None) is None
    assert vram.choose_device(out.devices, "1638") is None


def test_run_skips_when_only_integrated_gpu(tmp_path: Path) -> None:
    fake = FakeMemtest("igpu_only.txt", line_delay=0.05)
    started = time.monotonic()
    result = vram.run_vram_test(
        30, threading.Event(), exe=_exe(tmp_path), stream_factory=fake.factory, use_sensors=False
    )
    assert result.status is TestStatus.SKIPPED
    assert result.notes == [vram.NO_DISCRETE_GPU_NOTE]
    assert fake.sent == [] and fake.stopped
    assert time.monotonic() - started < 3


def test_result_from_output() -> None:
    passed = vram.to_result(_parse("pass_single.txt"), duration=150.0)
    assert passed.status is TestStatus.PASSED
    assert passed.metrics["errors"] == 0 and passed.metrics["iterations"] == 5995
    failed = vram.to_result(_parse("errors.txt"), duration=10.0)
    assert failed.status is TestStatus.FAILED
    assert failed.metrics["errors"] == 58
    skipped = vram.to_result(_parse("init_incompatible_driver.txt"), duration=1.0)
    assert skipped.status is TestStatus.SKIPPED
    assert any("Vulkan" in note for note in skipped.notes)
    # 15.9: утилита завершилась сразу, не начав проверку, — «пропущен» с понятной причиной.
    nothing = vram.to_result(vram.MemtestOutput(last_lines=["some output"]), duration=1.0)
    assert nothing.status is TestStatus.SKIPPED
    assert nothing.notes == [vram.EXITED_EARLY_NOTE]
    assert nothing.metrics["last_output"] == ["some output"]


def test_parser_keeps_last_output_lines() -> None:
    parser = vram.MemtestParser()
    for index in range(30):
        parser.feed(f"line {index}")
    parser.feed("")
    assert parser.result.last_lines == [f"line {i}" for i in range(20, 30)]


class FakeMemtest:
    """Подмена StreamProcess: проигрывает фикстуру и запоминает, что ему «нажимали»."""

    def __init__(self, fixture: str, finish_by_itself: bool = False, line_delay: float = 0.0):
        self.lines = fixture_text("memtest", fixture).splitlines()
        self.finish_by_itself = finish_by_itself
        self.line_delay = line_delay
        self.sent: list[bytes] = []
        self.interrupted = False
        self.stopped = False
        self._alive = True
        self.cmd: list[str] = []

    def factory(
        self, cmd: list[str], on_line: Callable[[str], None], **kwargs: Any
    ) -> "FakeMemtest":
        self.cmd = cmd

        def play() -> None:
            for line in self.lines:
                if self.stopped:
                    return
                on_line(line)
                time.sleep(self.line_delay)
            if self.finish_by_itself:
                self._alive = False

        threading.Thread(target=play, daemon=True).start()
        time.sleep(0.05)
        return self

    @property
    def running(self) -> bool:
        return self._alive and not self.stopped

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def interrupt(self) -> None:
        self.interrupted = True
        self._alive = False

    def wait(self, timeout: float) -> int | None:
        return 0 if not self.running else None

    def stop(self, grace: float = 1.0) -> None:
        self.stopped = True


def _exe(tmp_path: Path) -> Path:
    exe = tmp_path / "memtest_vulkan.exe"
    exe.write_bytes(b"")
    return exe


def test_run_full_duration_then_graceful_stop(tmp_path: Path) -> None:
    fake = FakeMemtest("multi_gpu.txt")
    progress: list[float] = []
    result = vram.run_vram_test(
        0.6,
        threading.Event(),
        on_progress=progress.append,
        exe=_exe(tmp_path),
        target_device_id="2206",
        stream_factory=fake.factory,
        use_sensors=False,
    )
    assert result.status is TestStatus.PASSED
    assert fake.interrupted, "по окончании времени тест останавливается как по Ctrl+C"
    assert b"2\n" in fake.sent, "выбрана видеокарта с нужным кодом устройства"
    assert progress[-1] == 1.0
    assert result.metrics["iterations"] == 58


def test_run_finishes_by_itself_with_errors(tmp_path: Path) -> None:
    fake = FakeMemtest("errors.txt", finish_by_itself=True)
    result = vram.run_vram_test(
        30,
        threading.Event(),
        exe=_exe(tmp_path),
        stream_factory=fake.factory,
        use_sensors=False,
    )
    assert result.status is TestStatus.FAILED
    assert b"\n" in fake.sent, "на «press any key» отправлено нажатие"


def test_run_cancel(tmp_path: Path) -> None:
    fake = FakeMemtest("pass_single.txt", line_delay=0.5)
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = vram.run_vram_test(
        60, cancel, exe=_exe(tmp_path), stream_factory=fake.factory, use_sensors=False
    )
    assert time.monotonic() - start < 3
    assert result.status is TestStatus.SKIPPED
    assert result.metrics["cancelled"] is True
    assert fake.stopped


def test_run_without_exe(tmp_path: Path) -> None:
    result = vram.run_vram_test(10, threading.Event(), exe=tmp_path / "missing.exe")
    assert result.status is TestStatus.SKIPPED
    assert any("setup_vendor" in note for note in result.notes)


def test_parse_real_run_stopped_after_20_seconds() -> None:
    # Реальный вывод memtest_vulkan 0.5.0 на GTX 1660 (машина разработчика), тест остановлен
    # программой через 20 с: с одной видеокартой утилита не задаёт вопрос о выборе устройства.
    out = _parse("real_gtx1660_20s_stopped.txt")
    assert out.asks_device is False
    assert out.tested_device == 1 and out.devices[0].device_id == "2184"
    assert out.iterations == 125
    assert vram.to_result(out, duration=20).status is TestStatus.PASSED
