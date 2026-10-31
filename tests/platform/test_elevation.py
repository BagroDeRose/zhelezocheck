"""Тесты логики прав администратора: подмена ShellExecuteEx (без реального UAC) и настоящая
проверка структуры ShellExecuteEx и дескриптора процесса в Windows (глагол «open», без UAC)."""

import os
import sys
import time
from pathlib import Path

import pytest

from hwcheck.platform import elevation


class FakeShell32:
    def __init__(self, admin: int = 0) -> None:
        self.admin = admin

    def IsUserAnAdmin(self) -> int:  # noqa: N802 — имя функции из WinAPI
        return self.admin


class FakeProcess:
    def __init__(self, handle: int) -> None:
        self.handle = handle
        self.pid = 0

    def poll(self) -> int | None:
        return None

    def close(self) -> None:
        pass


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Платформа «Windows» с подменённым ShellExecuteEx; список — его вызовы."""
    calls: list[tuple[object, ...]] = []

    def fake_execute(verb: str, file: str, params: str, directory: str) -> int | None:
        calls.append((verb, file, params, directory))
        return 4242

    monkeypatch.setattr(elevation.sys, "platform", "win32")
    monkeypatch.setattr(elevation, "_shell_execute_ex", fake_execute)
    monkeypatch.setattr(elevation, "WindowsProcess", FakeProcess)
    return calls


def test_is_admin_true(windows: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation, "_shell32", lambda: FakeShell32(admin=1))
    assert elevation.is_admin() is True


def test_is_admin_false(windows: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation, "_shell32", lambda: FakeShell32(admin=0))
    assert elevation.is_admin() is False


def test_is_admin_error_means_false(windows: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> FakeShell32:
        raise OSError("нет shell32")

    monkeypatch.setattr(elevation, "_shell32", broken)
    assert elevation.is_admin() is False


def test_relaunch_uses_runas_in_program_folder(
    windows: list[tuple[object, ...]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HWCHECK_ROOT", str(tmp_path))
    monkeypatch.setattr(elevation.sys, "frozen", False, raising=False)
    monkeypatch.setattr(elevation.sys, "argv", ["hwcheck", "--demo", "my scenario"])
    child = elevation.relaunch_elevated("k1")
    assert isinstance(child, FakeProcess) and child.handle == 4242
    verb, exe, params, directory = windows[0]
    assert verb == "runas"
    assert exe == elevation.sys.executable
    # --relaunched и ключ: новая копия знает, что её ждёт старое окно, и чем отметить «готова».
    assert params == '-m hwcheck --demo "my scenario" --relaunched k1'
    # Копия стартует в папке программы, а не в C:\Windows\System32.
    assert Path(str(directory)).resolve() == tmp_path.resolve()


def test_relaunch_frozen_passes_only_args(
    windows: list[tuple[object, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(elevation.sys, "argv", ["app.exe", "--x", "--relaunched", "old"])
    assert elevation.relaunch_elevated("new") is not None
    assert windows[0][2] == "--x --relaunched new"  # старый ключ заменён, а не удвоен


def test_relaunch_refused(windows: object, monkeypatch: pytest.MonkeyPatch) -> None:
    # Пользователь нажал «Нет» в окне UAC → ShellExecuteEx не запускает процесс.
    monkeypatch.setattr(elevation, "_shell_execute_ex", lambda *args: None)
    assert elevation.relaunch_elevated("k") is None


def test_relaunch_error_is_not_a_crash(windows: object, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> int:
        raise OSError("shell32 недоступна")

    monkeypatch.setattr(elevation, "_shell_execute_ex", broken)
    assert elevation.relaunch_elevated("k") is None


def test_non_windows_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation.sys, "platform", "linux")
    monkeypatch.setattr(elevation, "_shell32", lambda: pytest.fail("не должно вызываться"))
    monkeypatch.setattr(elevation, "_shell_execute_ex", lambda *a: pytest.fail("не вызывать"))
    assert elevation.is_admin() is False
    assert elevation.relaunch_elevated("k") is None


@pytest.mark.skipif(sys.platform != "win32", reason="настоящий ShellExecuteEx — только Windows")
def test_real_shell_execute_ex_returns_process_and_exit_code() -> None:
    """Структура SHELLEXECUTEINFOW и дескриптор процесса — по-настоящему (глагол «open» не
    вызывает UAC): запускаем `cmd /c exit 7` и дожидаемся кода выхода 7."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    cmd = str(Path(system_root) / "System32" / "cmd.exe")
    handle = elevation._shell_execute_ex("open", cmd, "/c exit 7", system_root, show=0)
    assert handle
    process = elevation.WindowsProcess(handle)
    assert process.pid > 0  # номер процесса — по нему старое окно узнаёт отметку «готова»
    try:
        deadline = time.monotonic() + 10
        code = process.poll()
        while code is None and time.monotonic() < deadline:
            time.sleep(0.05)
            code = process.poll()
        assert code == 7
    finally:
        process.close()
    assert process.poll() is None  # после close дескриптора нет — и ошибки тоже нет
