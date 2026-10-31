"""Защита от второй копии программы (задача 20.3).

В журнале с ноутбука HONOR сбор сведений шёл в 2–3 потока одновременно: программу,
по-видимому, запустили несколько раз с одной флешки (например, двойной щелчок, пока
открывалось окно, или повтор после запроса прав администратора). Несколько копий делят одну
папку `data/` (история, лицензия, журнал) и вместе нагружают слабый ноутбук.

Файл-замок `data/hwcheck.lock` (QLockFile) держит работающая копия. Вторая копия ждёт
несколько секунд — этого хватает, чтобы закрылась старая копия при перезапуске с правами
администратора — и, если замок так и не освободился, сообщает, что программа уже открыта.
Если на флешку писать нельзя, защита отключается, а программа всё равно запускается.

Рядом с замком лежит отметка `data/relaunch.ready`: копия, запущенная с правами
администратора, пишет в неё одноразовый ключ от старого окна, когда её окно открылось и
собрало сведения.
Старое окно закрывается только после этой отметки — замка для этого мало: копия занимает его
в самом начале и может упасть уже после него (так было на компьютере с i7-3770).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QLockFile

log = logging.getLogger(__name__)

# Сколько ждать освобождения замка: старая копия закрывается после запроса прав администратора.
WAIT_MS = 10_000
READY_FILE_NAME = "relaunch.ready"


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

    @property
    def active(self) -> bool:
        """Эта копия держит замок (False — защита недоступна, например флешка без записи)."""
        return self._lock is not None

    def release(self) -> None:
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def held_by_other(self) -> bool:
        """Замок держит другой процесс — например, только что запущенная копия с правами
        администратора. Пока замок у этой копии или его состояние не узнать — False."""
        if self._lock is not None or not self._can_write():
            return False
        probe = QLockFile(str(self.path))
        probe.setStaleLockTime(0)
        if probe.tryLock(0):
            probe.unlock()
            return False
        return probe.error() == QLockFile.LockError.LockFailedError

    @property
    def _ready_file(self) -> Path:
        return self.path.with_name(READY_FILE_NAME)

    def mark_ready(self, token: str) -> None:
        """Копия с правами: «окно открыто и работает» (ключ от старого окна — в отметку)."""
        try:
            self._ready_file.parent.mkdir(parents=True, exist_ok=True)
            self._ready_file.write_text(token, encoding="utf-8")
        except OSError:
            log.warning("Не удалось записать отметку %s", READY_FILE_NAME)

    def ready_token(self) -> str | None:
        """Ключ из отметки «готова» или None (отметки нет, она пустая или не читается)."""
        try:
            return self._ready_file.read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeDecodeError):
            return None

    def clear_ready(self) -> None:
        """Убирает старую отметку перед новым перезапуском."""
        try:
            self._ready_file.unlink(missing_ok=True)
        except OSError:
            log.warning("Не удалось удалить отметку %s", READY_FILE_NAME)
