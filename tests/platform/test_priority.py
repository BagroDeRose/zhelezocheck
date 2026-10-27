"""Приоритет процессов нагрузки и число процессов (задача 22.7)."""

import sys
from typing import Any

import psutil
import pytest

from hwcheck.platform import priority


class FakeProcess:
    def __init__(self, error: Exception | None = None) -> None:
        self.values: list[Any] = []
        self.error = error

    def nice(self, value: Any) -> None:
        if self.error:
            raise self.error
        self.values.append(value)


@pytest.mark.parametrize(("cpus", "workers"), [(None, 1), (1, 1), (2, 1), (8, 7), (16, 15)])
def test_load_worker_count_leaves_one_core(cpus: int | None, workers: int) -> None:
    assert priority.load_worker_count(cpus) == workers


def test_lower_priority_sets_below_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess()
    assert priority.lower_own_priority(process)  # type: ignore[arg-type]  # подмена psutil.Process
    if sys.platform == "win32":  # константа psutil есть только в Windows-версии
        assert process.values == [psutil.BELOW_NORMAL_PRIORITY_CLASS]
    else:
        assert process.values == [priority.POSIX_NICE]


def test_lower_priority_failure_is_not_fatal() -> None:
    process = FakeProcess(error=psutil.AccessDenied())
    assert not priority.lower_own_priority(process)  # type: ignore[arg-type]  # подмена
