"""Тесты PowerShell-обёртки на записанных образцах вывода (без реального PowerShell)."""

from pathlib import Path

import pytest

from hwcheck.platform import powershell
from hwcheck.platform.runner import RunResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "powershell"


class FakeRun:
    """Подменяет runner.run: запоминает команду и отдаёт заранее заданный результат."""

    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.cmd: list[str] = []

    def __call__(self, cmd: list[str], timeout: float = 60.0, **kwargs: object) -> RunResult:
        self.cmd = cmd
        return self.result


def _ok(stdout: str) -> FakeRun:
    return FakeRun(RunResult(0, stdout, "", 0.1))


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_single_object() -> None:
    fake = _ok(_fixture("single_object.json"))
    data = powershell.ps_json("Get-CimInstance Win32_OperatingSystem", run_fn=fake)
    assert isinstance(data, dict)
    assert data["BuildNumber"] == "22631"


def test_single_object_as_list() -> None:
    fake = _ok(_fixture("single_object.json"))
    items = powershell.ps_json_list("Get-CimInstance Win32_OperatingSystem", run_fn=fake)
    assert len(items) == 1 and items[0]["Caption"].startswith("Microsoft")


def test_array() -> None:
    fake = _ok(_fixture("array.json"))
    items = powershell.ps_json_list("Get-PhysicalDisk", run_fn=fake)
    assert [i["Name"] for i in items] == ["Disk0", "Disk1"]


def test_empty_output() -> None:
    fake = _ok(_fixture("empty.txt"))
    assert powershell.ps_json("Get-Nothing", run_fn=fake) is None
    assert powershell.ps_json_list("Get-Nothing", run_fn=fake) == []


def test_error_raises_with_message() -> None:
    fake = FakeRun(RunResult(1, "", _fixture("error_stderr.txt"), 0.2))
    with pytest.raises(powershell.PowerShellError) as info:
        powershell.ps_json("Get-CimInstance -ClassName Win32_Foo", run_fn=fake)
    assert "Отказано в доступе" in str(info.value)
    assert info.value.access_denied


def test_timeout_raises() -> None:
    fake = FakeRun(RunResult(None, "", "", 30.0, timed_out=True))
    with pytest.raises(powershell.PowerShellError):
        powershell.ps_json("Start-Sleep 100", run_fn=fake)


def test_not_found_raises() -> None:
    fake = FakeRun(RunResult(None, "", "not found", 0.0, not_found=True))
    with pytest.raises(powershell.PowerShellError):
        powershell.ps_json("Get-Date", run_fn=fake)


def test_invalid_json_raises() -> None:
    fake = _ok("это не JSON")
    with pytest.raises(powershell.PowerShellError):
        powershell.ps_json("Get-Date", run_fn=fake)


def test_command_line_shape() -> None:
    fake = _ok("1")
    powershell.ps_json("Get-Date", run_fn=fake)
    assert fake.cmd[0].lower().startswith("powershell")
    assert "-NoProfile" in fake.cmd and "-NonInteractive" in fake.cmd
    script = fake.cmd[-1]
    assert "Get-Date" in script
    assert "ConvertTo-Json -Depth 5 -Compress" in script


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/Date(1689811200000)/", "2023-07-20T00:00:00+00:00"),
        ("2023-07-20T00:00:00", "2023-07-20T00:00:00"),
        ("20230720000000.000000+180", "2023-07-20T00:00:00"),
        (None, None),
        ("", None),
    ],
)
def test_parse_ps_date(value: str | None, expected: str | None) -> None:
    assert powershell.parse_ps_date(value) == expected
