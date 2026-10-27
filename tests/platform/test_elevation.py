"""Тесты логики прав администратора с подменой ctypes (без реального UAC)."""

import pytest

from hwcheck.platform import elevation


class FakeShell32:
    def __init__(self, admin: int = 0, shell_result: int = 42) -> None:
        self.admin = admin
        self.shell_result = shell_result
        self.calls: list[tuple[object, ...]] = []

    def IsUserAnAdmin(self) -> int:  # noqa: N802 — имя функции из WinAPI
        return self.admin

    def ShellExecuteW(self, *args: object) -> int:  # noqa: N802 — имя функции из WinAPI
        self.calls.append(args)
        return self.shell_result


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation.sys, "platform", "win32")


def test_is_admin_true(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation, "_shell32", lambda: FakeShell32(admin=1))
    assert elevation.is_admin() is True


def test_is_admin_false(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation, "_shell32", lambda: FakeShell32(admin=0))
    assert elevation.is_admin() is False


def test_is_admin_error_means_false(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> FakeShell32:
        raise OSError("нет shell32")

    monkeypatch.setattr(elevation, "_shell32", broken)
    assert elevation.is_admin() is False


def test_relaunch_uses_runas(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeShell32(shell_result=42)
    monkeypatch.setattr(elevation, "_shell32", lambda: fake)
    monkeypatch.setattr(elevation.sys, "frozen", False, raising=False)
    monkeypatch.setattr(elevation.sys, "argv", ["hwcheck", "--demo", "my scenario"])
    assert elevation.relaunch_elevated() is True
    _hwnd, verb, exe, params, _cwd, _show = fake.calls[0]
    assert verb == "runas"
    assert exe == elevation.sys.executable
    assert params == '-m hwcheck --demo "my scenario"'


def test_relaunch_frozen_passes_only_args(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeShell32(shell_result=42)
    monkeypatch.setattr(elevation, "_shell32", lambda: fake)
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(elevation.sys, "argv", ["app.exe", "--x"])
    assert elevation.relaunch_elevated() is True
    assert fake.calls[0][3] == "--x"


def test_relaunch_refused(windows: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Пользователь нажал «Нет» в окне UAC → ShellExecute возвращает код ≤ 32.
    monkeypatch.setattr(elevation, "_shell32", lambda: FakeShell32(shell_result=5))
    assert elevation.relaunch_elevated() is False


def test_non_windows_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation.sys, "platform", "linux")
    monkeypatch.setattr(elevation, "_shell32", lambda: pytest.fail("не должно вызываться"))
    assert elevation.is_admin() is False
    assert elevation.relaunch_elevated() is False
