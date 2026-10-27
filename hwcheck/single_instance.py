"""Защита от второй копии программы (задача 20.3).

В журнале с ноутбука HONOR сбор сведений шёл в 2–3 потока одновременно: программу,
по-видимому, запустили несколько раз с одной флешки (например, двойной щелчок, пока
открывалось окно, или повтор после запроса прав администратора). Несколько копий делят одну
папку `data/` (история, лицензия, журнал) и вместе нагружают слабый ноутбук.

Файл-замок `data/hwcheck.lock` (QLockFile) держит работающая копия. Вторая копия ждёт
несколько секунд — этого хватает, чтобы закрылась старая копия при перезапуске с правами
администратора — и, если замок так и не освободился, сообщает, что программа уже открыта.
Если на флешку писать нельзя, защита отключается, а программа всё равно запускается.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile

# Сколько ждать освобождения замка: старая копия закрывается после запроса прав администратора.
WAIT_MS = 10_000


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock: QLockFile | None = None

    def _can_write(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return True

    def acquire(self, timeout_ms: int = WAIT_MS) -> bool:
        """True — эта копия единственная (или защита недоступна); False — уже открыта другая."""
        if not self._can_write():
            return True
        lock = QLockFile(str(self.path))
        lock.setStaleLockTime(0)  # «зависший» замок упавшей копии определяется по номеру процесса
        if lock.tryLock(timeout_ms):
            self._lock = lock
            return True
        return lock.error() != QLockFile.LockError.LockFailedError

    def release(self) -> None:
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None
