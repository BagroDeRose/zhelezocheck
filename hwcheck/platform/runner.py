"""Единая обёртка для запуска внешних программ (PowerShell, nvidia-smi, smartctl и др.).

Зачем она нужна:
- у каждой команды есть таймаут — программа не зависнет навсегда;
- команду можно отменить по событию (кнопка «Остановить»);
- вывод Windows-программ бывает в разных кодировках (UTF-8, UTF-16, cp866, cp1251) —
  здесь он превращается в нормальный текст;
- запуск всегда без оболочки (`shell` выключен) — команда передаётся списком аргументов,
  поэтому подстановка чужого текста в команду невозможна;
- каждая команда записывается в лог.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

log = logging.getLogger(__name__)

# Как часто проверять таймаут и отмену, секунд.
_POLL_INTERVAL = 0.1

# Флаг Windows: не открывать чёрное окно консоли для дочерней программы.
CREATE_NO_WINDOW = 0x08000000


@dataclass
class RunResult:
    """Результат запуска внешней команды."""

    returncode: int | None
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    cancelled: bool = False
    not_found: bool = False

    @property
    def ok(self) -> bool:
        """Команда завершилась сама и с кодом 0."""
        return self.returncode == 0 and not (self.timed_out or self.cancelled or self.not_found)


RunFn = Callable[..., RunResult]
"""Тип функции запуска (сама `run` или её подмена в тестах)."""


def creation_flags() -> int:
    """Флаги запуска процесса: на Windows прячем окно консоли."""
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


# --------------------------------------------------------------------------
# Декодирование вывода
# --------------------------------------------------------------------------

_BOMS: list[tuple[bytes, str]] = [
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
]


def decode_output(data: bytes, encoding_hint: str | None = None) -> str:
    """Превращает байты вывода программы в текст, угадывая кодировку.

    Порядок: подсказка → метка BOM → UTF-16 без BOM (много нулевых байтов) →
    UTF-8 → лучшая из cp866/cp1251 (по количеству нормальных русских букв).
    """
    if not data:
        return ""
    if encoding_hint:
        try:
            return data.decode(encoding_hint)
        except (UnicodeDecodeError, LookupError):
            pass
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    utf16 = _guess_utf16_without_bom(data)
    if utf16:
        return data.decode(utf16, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    candidates = [data.decode("cp866", errors="replace"), data.decode("cp1251", errors="replace")]
    # При равенстве побеждает cp866 — это кодировка консоли Windows по умолчанию.
    return max(candidates, key=_russian_text_score)


def _guess_utf16_without_bom(data: bytes) -> str | None:
    """Если в каждом втором байте нули — это UTF-16 без метки. Возвращает кодировку или None."""
    if len(data) < 2 or len(data) % 2 != 0:
        return None
    even_zeros = data[0::2].count(0)
    odd_zeros = data[1::2].count(0)
    half = len(data) // 2
    if odd_zeros > half * 0.3 and odd_zeros > even_zeros:
        return "utf-16-le"
    if even_zeros > half * 0.3 and even_zeros > odd_zeros:
        return "utf-16-be"
    return None


def _russian_text_score(text: str) -> int:
    """Оценка «похожести на русский текст»: русские буквы А–я минус псевдографика."""
    letters = sum(1 for ch in text if "А" <= ch <= "я")
    box_drawing = sum(1 for ch in text if "─" <= ch <= "◿")
    return letters - box_drawing


# --------------------------------------------------------------------------
# Запуск
# --------------------------------------------------------------------------


def run(
    cmd: list[str],
    timeout: float = 60.0,
    encoding_hint: str | None = None,
    cancel_event: threading.Event | None = None,
    cwd: str | None = None,
) -> RunResult:
    """Запускает команду и ждёт её завершения (или таймаута, или отмены).

    `cmd` — список: программа и её аргументы. Строка не принимается.
    """
    if not isinstance(cmd, list) or not cmd:
        raise TypeError("Команда должна быть непустым списком аргументов")
    log.info("Запуск: %s", cmd[0] if len(cmd) == 1 else f"{cmd[0]} (+{len(cmd) - 1} арг.)")
    start = time.monotonic()
    try:
        # S603: это единственное место запуска процессов; оболочка выключена, cmd — список.
        process = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            creationflags=creation_flags(),
        )
    except (FileNotFoundError, PermissionError, OSError) as error:
        log.info("Программа не найдена или не запускается: %s (%s)", cmd[0], error)
        return RunResult(None, "", str(error), time.monotonic() - start, not_found=True)

    timed_out = False
    cancelled = False
    while True:
        try:
            out, err = process.communicate(timeout=_POLL_INTERVAL)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() - start > timeout:
                timed_out = True
            elif cancel_event is not None and cancel_event.is_set():
                cancelled = True
            if timed_out or cancelled:
                process.kill()
                out, err = process.communicate()
                break

    duration = time.monotonic() - start
    result = RunResult(
        returncode=None if (timed_out or cancelled) else process.returncode,
        stdout=decode_output(out, encoding_hint),
        stderr=decode_output(err, encoding_hint),
        duration=duration,
        timed_out=timed_out,
        cancelled=cancelled,
    )
    log.info(
        "Завершено: %s, код %s, %.1f с%s%s",
        cmd[0],
        result.returncode,
        duration,
        ", таймаут" if timed_out else "",
        ", отменено" if cancelled else "",
    )
    return result


# --------------------------------------------------------------------------
# Потоковый запуск (программа работает долго и пишет строки по мере работы)
# --------------------------------------------------------------------------


class StreamProcess:
    """Фоновая программа, каждая строка вывода которой передаётся в `on_line`.

    Нужна для датчиков (`nvidia-smi -lms 1000`) и долгих тестов (memtest_vulkan).
    Остановка — `stop()`: сначала мягко, затем принудительно.
    """

    def __init__(
        self,
        cmd: list[str],
        on_line: Callable[[str], None],
        encoding_hint: str | None = "utf-8",
        cwd: str | None = None,
        stdin_pipe: bool = False,
        new_process_group: bool = False,
        below_normal: bool = False,
    ) -> None:
        if not isinstance(cmd, list) or not cmd:
            raise TypeError("Команда должна быть непустым списком аргументов")
        log.info("Фоновый запуск: %s", cmd[0])
        self.encoding_hint = encoding_hint
        self.on_line = on_line
        flags = creation_flags()
        if new_process_group and sys.platform == "win32":
            # Своя группа процессов нужна, чтобы послать программе Ctrl+Break (как Ctrl+C).
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if below_normal and sys.platform == "win32":
            # Приоритет «ниже обычного» (наследуют и дочерние процессы программы): датчики
            # и тесты не отнимают процессор у окна и системы (задача 22.7).
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        # S603: единственное место потокового запуска; оболочка выключена, cmd — список.
        self.process = subprocess.Popen(  # noqa: S603
            cmd,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            creationflags=flags,
        )
        self._reader = threading.Thread(target=self._read, name=f"stream-{cmd[0]}", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        stream = self.process.stdout
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            text = decode_output(raw, self.encoding_hint).rstrip("\r\n")
            if text.strip():
                try:
                    self.on_line(text)
                except Exception:  # ошибка обработчика не должна обрывать чтение
                    log.exception("Ошибка обработки строки вывода")

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def send(self, data: bytes) -> None:
        """Пишет байты во ввод программы (например, «нажатие клавиши»)."""
        if self.process.stdin is not None:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except OSError:
                pass

    def interrupt(self) -> None:
        """Просит программу завершиться «как по Ctrl+C» (Ctrl+Break), без принудительного убийства.

        Если не получилось — ничего страшного: потом вызывается `stop()`.
        """
        if not self.running:
            return
        try:
            if sys.platform == "win32":
                os.kill(self.process.pid, signal.CTRL_BREAK_EVENT)
            else:
                self.process.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            log.info("Не удалось послать Ctrl+Break, будет принудительная остановка")

    def wait(self, timeout: float) -> int | None:
        """Ждёт завершения до `timeout` секунд. Возвращает код или None, если ещё работает."""
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def stop(self, grace: float = 1.0) -> None:
        """Останавливает программу ВМЕСТЕ с её дочерними процессами.

        Некоторые утилиты (например, memtest_vulkan) запускают рабочий процесс-потомок;
        если завершить только родителя, потомок продолжит нагружать железо.
        """
        children = _children_of(self.process.pid)
        if self.running:
            self.process.terminate()
            if self.wait(grace) is None:
                self.process.kill()
                self.wait(grace)
        _kill_all(children, grace)
        self._reader.join(timeout=grace)


def _children_of(pid: int) -> list[psutil.Process]:
    """Все потомки процесса (их нужно найти ДО завершения родителя)."""
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []


def _kill_all(processes: list[psutil.Process], grace: float) -> None:
    for child in processes:
        try:
            child.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(processes, timeout=grace)
