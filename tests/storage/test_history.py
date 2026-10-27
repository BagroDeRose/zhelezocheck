"""Тесты истории проверок на временной базе."""

from pathlib import Path

from hwcheck.storage.history import History, describe_computer
from tests.report.helpers import demo_session


def test_crud(tmp_path: Path) -> None:
    history = History(tmp_path / "data" / "history.sqlite")
    first = demo_session("healthy_gaming_pc")
    second = demo_session("mining_gpu")
    second.id = "second"
    second.started_at = "2026-10-06T09:00:00"

    history.save(first)
    history.save(second, report_path=tmp_path / "r.html")
    entries = history.list()
    assert [e.id for e in entries] == ["second", first.id]  # новые сверху
    assert entries[0].decision == "negotiate"
    assert entries[0].report_path == str(tmp_path / "r.html")
    assert "RTX 3070" in entries[0].computer

    entry = history.get(first.id)
    assert entry is not None and entry.decision == "buy" and entry.report_path is None
    history.set_report_path(first.id, tmp_path / "x.pdf")
    updated = history.get(first.id)
    assert updated is not None and updated.report_path == str(tmp_path / "x.pdf")

    restored = history.load_session("second")
    assert restored == second

    history.delete("second")
    assert history.get("second") is None
    assert history.load_session("second") is None
    assert [e.id for e in history.list()] == [first.id]


def test_save_twice_updates(tmp_path: Path) -> None:
    history = History(tmp_path / "h.sqlite")
    session = demo_session("worn_ssd")
    history.save(session)
    history.save(session, report_path=tmp_path / "r.html")
    assert len(history.list()) == 1


def test_reopen_existing_db(tmp_path: Path) -> None:
    path = tmp_path / "h.sqlite"
    History(path).save(demo_session("dying_hdd"))
    assert len(History(path).list()) == 1


def test_describe_laptop() -> None:
    text = describe_computer(demo_session("laptop_worn_battery"))
    assert "Ryzen 7 5800H" in text and "ноутбук" in text
