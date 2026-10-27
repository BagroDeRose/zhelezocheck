"""Общие помощники тестов: чтение фикстур и подмена запуска внешних команд."""

import json
from pathlib import Path
from typing import Any

from hwcheck.platform.runner import RunResult

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def fixture_json(*parts: str) -> Any:
    return json.loads(fixture_text(*parts))


class FakeRun:
    """Подмена runner.run: отдаёт заданный stdout и запоминает команды."""

    def __init__(self, stdout: str = "", returncode: int | None = 0, **flags: Any) -> None:
        self.result = RunResult(returncode, stdout, flags.pop("stderr", ""), 0.1, **flags)
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], timeout: float = 60.0, **kwargs: Any) -> RunResult:
        self.commands.append(cmd)
        return self.result
