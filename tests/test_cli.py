"""Тесты консольных команд на демо-сценариях."""

import json
from pathlib import Path

import pytest

from hwcheck import cli
from hwcheck.models import HardwareSnapshot


def test_collect_demo_prints_snapshot_json(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["collect", "--demo", "healthy_gaming_pc"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    snap = HardwareSnapshot.from_dict(data)
    assert snap.gpus[0].name == "NVIDIA GeForce RTX 3060"


def test_collect_demo_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "snap.json"
    code = cli.main(["collect", "--demo", "mining_gpu", "--out", str(out)])
    assert code == 0
    snap = HardwareSnapshot.from_json(out.read_text(encoding="utf-8"))
    assert snap.gpus[0].pci_device_id == "2484"
    assert str(out) in capsys.readouterr().out


def test_collect_unknown_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["collect", "--demo", "nope"])
    assert code == 2
    assert "healthy_gaming_pc" in capsys.readouterr().err


def test_no_command_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 1
    assert "collect" in capsys.readouterr().out


def test_run_demo_short(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from hwcheck.models import CheckSession, TestStatus

    out = tmp_path / "run.json"
    assert cli.main(["run", "--demo", "ram_errors", "--short", "--out", str(out)]) == 0
    session = CheckSession.from_json(out.read_text(encoding="utf-8"))
    assert session.mode == "short"
    assert session.demo_scenario == "ram_errors"
    statuses = {r.name: r.status for r in session.results}
    assert statuses["ram_quick"] is TestStatus.FAILED
    assert len(statuses) == 5
    text = capsys.readouterr().out
    assert "100%" in text


def test_run_only(tmp_path: Path) -> None:
    from hwcheck.models import CheckSession

    out = tmp_path / "run.json"
    assert (
        cli.main(
            ["run", "--demo", "healthy_gaming_pc", "--only", "vram,cpu_load", "--out", str(out)]
        )
        == 0
    )
    session = CheckSession.from_json(out.read_text(encoding="utf-8"))
    assert [r.name for r in session.results] == ["vram", "cpu_load"]


def test_verdict_demo_mining(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["verdict", "--demo", "mining_gpu"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Вердикт: ТОРГОВАТЬСЯ")
    assert "майнинговая прошивка" in text
    assert "Аргументы для торга:" in text
    assert "Что не удалось проверить:" in text


def test_verdict_from_saved_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "run.json"
    assert cli.main(["run", "--demo", "dying_hdd", "--short", "--out", str(out)]) == 0
    capsys.readouterr()
    assert cli.main(["verdict", "--from", str(out)]) == 0
    assert "Вердикт: УХОДИТЬ" in capsys.readouterr().out


def test_verdict_requires_source(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["verdict"]) == 2
