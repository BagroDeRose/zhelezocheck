"""История проверок в SQLite (`data/history.sqlite` рядом с программой).

Для каждой проверки сохраняется: номер, дата, режим, решение, краткое описание компьютера,
путь к отчёту и полный JSON проверки (чтобы открыть её снова и пересобрать отчёт).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hwcheck.models import CheckSession, is_discrete_gpu

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    decision TEXT NOT NULL,
    computer TEXT NOT NULL,
    summary TEXT NOT NULL,
    report_path TEXT,
    session_json TEXT NOT NULL
)
"""


@dataclass
class HistoryEntry:
    """Строка истории (без полного JSON — его читает `load_session`)."""

    id: str
    created_at: str
    mode: str
    decision: str
    computer: str
    summary: str
    report_path: str | None


def describe_computer(session: CheckSession) -> str:
    """Краткое описание: процессор и видеокарта."""
    snap = session.snapshot
    parts = []
    if snap.cpu and snap.cpu.name:
        parts.append(snap.cpu.name)
    discrete = [g.name for g in snap.gpus if is_discrete_gpu(g)]
    if discrete:
        parts.append(discrete[0])
    if snap.system and snap.system.is_laptop:
        parts.append("ноутбук")
    return " / ".join(parts) or "неизвестный компьютер"


class History:
    """Работа с базой истории проверок."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create()
        except sqlite3.DatabaseError as error:
            if isinstance(error, sqlite3.OperationalError):
                raise  # нет доступа к файлу — это не повреждение, сохраняем как есть
            # Файл испорчен: откладываем его в сторону (не удаляем) и начинаем новую историю.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            broken = db_path.with_name(f"{db_path.name}.broken-{stamp}")
            db_path.replace(broken)
            logging.getLogger(__name__).warning("История повреждена, сохранена как %s", broken.name)
            self._create()

    def _create(self) -> None:
        with self._connect() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            yield db

    def save(self, session: CheckSession, report_path: Path | None = None) -> None:
        """Сохраняет (или обновляет) проверку."""
        verdict = session.verdict
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO checks "
                "(id, created_at, mode, decision, computer, summary, report_path, session_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.started_at,
                    session.mode,
                    verdict.decision.value if verdict else "",
                    describe_computer(session),
                    verdict.summary if verdict else "",
                    str(report_path) if report_path else None,
                    session.to_json(indent=None),
                ),
            )

    def set_report_path(self, check_id: str, report_path: Path) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE checks SET report_path = ? WHERE id = ?", (str(report_path), check_id)
            )

    def list(self, limit: int = 200) -> list[HistoryEntry]:
        """Последние проверки, новые сверху."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, created_at, mode, decision, computer, summary, report_path "
                "FROM checks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [HistoryEntry(*row) for row in rows]

    def get(self, check_id: str) -> HistoryEntry | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT id, created_at, mode, decision, computer, summary, report_path "
                "FROM checks WHERE id = ?",
                (check_id,),
            ).fetchone()
        return HistoryEntry(*row) if row else None

    def load_session(self, check_id: str) -> CheckSession | None:
        """Полная проверка из истории (для повторного открытия отчёта)."""
        with self._connect() as db:
            row = db.execute("SELECT session_json FROM checks WHERE id = ?", (check_id,)).fetchone()
        return CheckSession.from_json(row[0]) if row else None

    def delete(self, check_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM checks WHERE id = ?", (check_id,))
