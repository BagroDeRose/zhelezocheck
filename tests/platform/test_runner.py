"""Тесты обёртки внешних команд: кодировки, таймаут, отмена, запрет shell."""

import sys
import threading
import time
from pathlib import Path

import pytest

from hwcheck.platform import runner

FIXTURES = Path(__file__).parent.parent / "fixtures" / "encodings"
EXPECTED = "Имя диска: Samsung SSD 980\r\nСостояние: Исправен\r\n"


@pytest.mark.parametrize(
    "name",
    [
        "utf8.raw",
        "utf8_bom.raw",
        "utf16le_bom.raw",
        "utf16le_nobom.raw",
        "utf16be_bom.raw",
        "cp866.raw",
        "cp1251.raw",
    ],
)
def test_decode_fixture(name: str) -> None:
    assert runner.decode_output((FIXTURES / name).read_bytes()) == EXPECTED


def test_decode_empty() -> None:
    assert runner.decode_output(b"") == ""


def test_decode_hint_used_first() -> None:
    data = "Привет".encode("cp1251")
    assert runner.decode_output(data, encoding_hint="cp1251") == "Привет"


def test_decode_bad_hint_falls_back() -> None:
    data = "Привет".encode()
    assert runner.decode_output(data, encoding_hint="ascii") == "Привет"


def test_run_success_captures_output() -> None:
    result = runner.run([sys.executable, "-c", "print('hello'); import sys; sys.exit(3)"])
    assert result.stdout.strip() == "hello"
    assert result.returncode == 3
    assert not result.timed_out
    assert not result.ok


def test_run_stderr_captured() -> None:
    result = runner.run([sys.executable, "-c", "import sys; sys.stderr.write('oops')"])
    assert result.stderr == "oops"
    assert result.ok


def test_run_timeout() -> None:
    start = time.monotonic()
    result = runner.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    assert result.timed_out
    assert time.monotonic() - start < 4
    assert not result.ok


def test_run_cancel() -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = runner.run([sys.executable, "-c", "import time; time.sleep(5)"], cancel_event=cancel)
    assert result.cancelled
    assert time.monotonic() - start < 3


def test_run_not_found() -> None:
    result = runner.run(["definitely_missing_program_hwcheck_123"])
    assert result.not_found
    assert result.returncode is None
    assert not result.ok


def test_run_rejects_string_command() -> None:
    with pytest.raises(TypeError):
        runner.run("echo hi")  # type: ignore[arg-type]  # проверяем запрет строки-команды


def test_module_never_uses_shell_true() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source


def test_stream_process_lines_and_stdin() -> None:
    lines: list[str] = []
    code = (
        "import sys\n"
        "print('one', flush=True)\n"
        "name = sys.stdin.readline().strip()\n"
        "print('got ' + name, flush=True)\n"
    )
    proc = runner.StreamProcess([sys.executable, "-c", code], lines.append, stdin_pipe=True)
    deadline = time.monotonic() + 5
    while not lines and time.monotonic() < deadline:
        time.sleep(0.05)
    proc.send(b"abc\n")
    assert proc.wait(5) == 0
    proc.stop()
    assert lines == ["one", "got abc"]
    assert not proc.running


def test_stream_process_stop_long_running() -> None:
    proc = runner.StreamProcess(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        lambda line: None,
        new_process_group=True,
    )
    assert proc.running
    start = time.monotonic()
    proc.interrupt()
    proc.stop(grace=1.0)
    assert not proc.running
    assert time.monotonic() - start < 3


def test_stream_process_missing_program() -> None:
    with pytest.raises(FileNotFoundError):
        runner.StreamProcess(["definitely_missing_program_hwcheck_123"], lambda line: None)


def test_stream_process_stop_kills_children() -> None:
    import psutil

    pids: list[str] = []
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = runner.StreamProcess([sys.executable, "-c", code], pids.append)
    deadline = time.monotonic() + 10
    while not pids and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pids, "дочерний процесс не запустился"
    child = int(pids[0])
    assert psutil.pid_exists(child)
    proc.stop()
    time.sleep(0.2)
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


@pytest.mark.skipif(sys.platform != "win32", reason="классы приоритета процессов — только Windows")
def test_stream_process_below_normal_priority() -> None:
    """Датчики и memtest запускаются с приоритетом «ниже обычного» (задача 22.7)."""
    import psutil

    assert sys.platform == "win32"  # для pyright на Linux: дальше — только Windows-код

    lines: list[str] = []
    code = "import psutil; print(int(psutil.Process().nice()), flush=True)"
    proc = runner.StreamProcess([sys.executable, "-c", code], lines.append, below_normal=True)
    assert proc.wait(10) == 0
    proc.stop()
    assert lines == [str(int(psutil.BELOW_NORMAL_PRIORITY_CLASS))]
