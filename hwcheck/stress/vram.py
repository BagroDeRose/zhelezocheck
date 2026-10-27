"""Тест видеопамяти через утилиту memtest_vulkan (лежит в `vendor/memtest_vulkan/`).

memtest_vulkan записывает в видеопамять узоры и читает их обратно; любая ошибка означает,
что память видеокарты неисправна (частая проблема карт после майнинга).

Как запускаем:
1. Стартуем программу, читаем её вывод построчно.
2. Когда она спрашивает, какую карту тестировать, — отвечаем номером нужной карты
   (по коду устройства), иначе она сама выберет первую через 8 секунд.
3. Через заданное время (быстрый режим — 3 мин, полный — 6+ мин) останавливаем её:
   пробуем «Ctrl+Break», на «press any key» отправляем нажатие, затем завершаем утилиту
   вместе с её рабочим процессом-потомком (проверено на memtest_vulkan 0.5.0: она
   запускает себя второй раз как рабочий процесс).
4. Разбираем вывод: итерации, скорость, строки «Error found», итог PASSed/FAILed,
   ошибки запуска Vulkan (тогда тест «пропущен» с понятным объяснением).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hwcheck.backends.base import STRESS_VRAM, ProgressCallback, SampleCallback
from hwcheck.config import get_paths
from hwcheck.models import GpuInfo, TestResult, TestStatus, is_discrete_gpu
from hwcheck.platform.runner import StreamProcess
from hwcheck.stress.sensors import SensorRecording

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"memtest_vulkan v(\d+\.\d+\.\d+)")
_DEVICE_RE = re.compile(
    r"^\s*(\d+): Bus=0x([0-9A-Fa-f]+):([0-9A-Fa-f]+) DevId=0x([0-9A-Fa-f]{4})\s+(\d+)GB\s+(.+?)\s*$"
)
_TEST_OF_RE = re.compile(r"test of (\d+):")
_ITERATION_RE = re.compile(
    r"^\s*(\d+) iteration\. Passed\s+([\d.]+) seconds\s+written:\s*([\d.]+)GB\s+([\d.]+)GB/sec"
    r"\s+checked:\s*([\d.]+)GB\s+([\d.]+)GB/sec"
)
_ERROR_RE = re.compile(r"Error found\..*total errors 0x([0-9A-Fa-f]+)")
_INIT_ERROR_MARKERS = (
    "ERROR_INCOMPATIBLE_DRIVER",
    "ERROR_INITIALIZATION_FAILED",
    "library failed to load",
    "LibraryLoadFailure",
    "early exit during init",
    "No Vulkan",
)

INIT_ERROR_NOTE = (
    "Тест видеопамяти не запустился: на этом компьютере не работает Vulkan "
    "(нет драйвера видеокарты или он слишком старый). Вердикт по видеокарте опирается "
    "на остальные проверки."
)
EXITED_EARLY_NOTE = (
    "Тест видеопамяти не смог начать проверку на этой видеокарте: утилита сразу завершилась. "
    "Так бывает со встроенной графикой и со старыми драйверами. Вердикт по видеокарте "
    "опирается на остальные проверки."
)
NO_DISCRETE_GPU_NOTE = (
    "Отдельной видеокарты нет: у встроенной графики своей видеопамяти нет — она берёт "
    "часть оперативной памяти, а её проверяет тест памяти."
)
LAST_LINES_KEPT = 10
MISSING_EXE_NOTE = (
    "Программа теста видеопамяти memtest_vulkan не найдена. "
    "Разработчику: запустите scripts\\setup_vendor.ps1."
)


@dataclass
class VulkanDevice:
    index: int
    bus: str
    device_id: str
    vram_gb: int
    name: str


@dataclass
class MemtestOutput:
    """Всё, что удалось понять из вывода memtest_vulkan."""

    version: str = ""
    devices: list[VulkanDevice] = field(default_factory=list)
    tested_device: int | None = None
    iterations: int = 0
    seconds: float = 0.0
    write_speed_gbps: float | None = None
    read_speed_gbps: float | None = None
    errors: int = 0
    error_lines: list[str] = field(default_factory=list)
    passed: bool = False
    failed: bool = False
    init_error: str | None = None
    waiting_for_key: bool = False
    asks_device: bool = False
    last_lines: list[str] = field(default_factory=list)  # для журнала, если что-то пошло не так


class MemtestParser:
    """Построчный разбор вывода memtest_vulkan."""

    def __init__(self) -> None:
        self.result = MemtestOutput()

    def feed(self, line: str) -> None:
        out = self.result
        if line.strip():
            out.last_lines = [*out.last_lines, line.strip()][-LAST_LINES_KEPT:]
        if match := _VERSION_RE.search(line):
            out.version = match.group(1)
        if match := _DEVICE_RE.match(line):
            index, bus_hi, bus_lo, device, size, name = match.groups()
            out.devices.append(
                VulkanDevice(int(index), f"{bus_hi}:{bus_lo}", device.lower(), int(size), name)
            )
            return
        if "Override index to test" in line:
            out.asks_device = True
        if (match := _TEST_OF_RE.search(line)) and "Standard" in line:
            out.tested_device = int(match.group(1))
        if match := _ITERATION_RE.match(line):
            out.iterations = int(match.group(1))
            out.seconds = float(match.group(2))
            out.write_speed_gbps = float(match.group(4))
            out.read_speed_gbps = float(match.group(6))
            return
        if match := _ERROR_RE.search(line):
            out.errors += int(match.group(1), 16)
            out.error_lines.append(line.strip())
        if "testing PASSed" in line:
            out.passed = True
        if "testing FAILed" in line or "errors found" in line:
            out.failed = True
        if any(marker in line for marker in _INIT_ERROR_MARKERS) and out.iterations == 0:
            out.init_error = out.init_error or line.strip()
        if "press any key" in line:
            out.waiting_for_key = True


def _vendor(name: str) -> str:
    lowered = name.lower()
    if any(word in lowered for word in ("nvidia", "geforce", "quadro", "tesla")):
        return "NVIDIA"
    if "amd" in lowered or "radeon" in lowered:
        return "AMD"
    return "Intel" if "intel" in lowered else ""


def is_discrete_device(device: VulkanDevice) -> bool:
    """Похоже ли устройство Vulkan на отдельную видеокарту (по названию, как в сводке)."""
    return is_discrete_gpu(GpuInfo(vendor=_vendor(device.name), name=device.name))


def choose_device(devices: list[VulkanDevice], target_device_id: str | None) -> int | None:
    """Номер устройства для теста или None, если отдельной видеокарты нет (задача 22.7).

    Сначала — устройство с кодом главной видеокарты из сводки; иначе — отдельная видеокарта
    с наибольшей памятью. Встроенную графику не тестируем никогда: своей видеопамяти у неё
    нет, а нагрузка на общую память подвешивает ноутбуки (особенно с процессорами AMD).
    """
    if target_device_id:
        for device in devices:
            if device.device_id == target_device_id.lower() and is_discrete_device(device):
                return device.index
    discrete = [device for device in devices if is_discrete_device(device)]
    return max(discrete, key=lambda d: d.vram_gb).index if discrete else None


def to_result(out: MemtestOutput, duration: float) -> TestResult:
    """Превращает разобранный вывод в TestResult."""
    metrics: dict[str, Any] = {
        "errors": out.errors,
        "iterations": out.iterations,
        "seconds": out.seconds,
        "write_speed_gbps": out.write_speed_gbps,
        "speed_gbps": out.read_speed_gbps,
        "memtest_version": out.version,
    }
    tested = next((d for d in out.devices if d.index == out.tested_device), None)
    if tested is not None:
        metrics["device_id"] = tested.device_id
        metrics["tested_gb"] = tested.vram_gb
    result = TestResult(name=STRESS_VRAM, component="gpu0", duration_s=duration, metrics=metrics)
    if out.errors > 0 or out.failed:
        result.status = TestStatus.FAILED
        result.notes.append(f"Найдены ошибки видеопамяти: {out.errors}.")
    elif out.init_error:
        result.status = TestStatus.SKIPPED
        result.notes.append(INIT_ERROR_NOTE)
        result.metrics["init_error"] = out.init_error
    elif out.iterations > 0:
        result.status = TestStatus.PASSED
    else:
        result.status = TestStatus.SKIPPED
        result.notes.append(EXITED_EARLY_NOTE)
        result.metrics["last_output"] = out.last_lines
        log.warning("memtest_vulkan завершился без проверок. Вывод: %s", " | ".join(out.last_lines))
    return result


def default_exe() -> Path:
    return get_paths().vendor / "memtest_vulkan" / "memtest_vulkan.exe"


def run_vram_test(
    duration: float,
    cancel_event: threading.Event,
    on_progress: ProgressCallback | None = None,
    on_sample: SampleCallback | None = None,
    exe: Path | None = None,
    target_device_id: str | None = None,
    stream_factory: Callable[..., Any] = StreamProcess,
    use_sensors: bool = True,
) -> TestResult:
    """Запускает memtest_vulkan на `duration` секунд и возвращает итог."""
    exe = exe or default_exe()
    if not exe.is_file():
        return TestResult(name=STRESS_VRAM, status=TestStatus.SKIPPED, notes=[MISSING_EXE_NOTE])

    parser = MemtestParser()
    answered = {"device": False, "key": False}
    holder: dict[str, Any] = {}

    def on_line(line: str) -> None:
        parser.feed(line)
        process = holder.get("process")
        if process is None:
            return
        out = parser.result
        if out.asks_device and not answered["device"]:
            answered["device"] = True
            index = choose_device(out.devices, target_device_id)
            if index is None:
                holder["no_discrete"] = True  # не ждём автовыбора первого (встроенного) GPU
                return
            process.send(f"{index}\n".encode())
        if out.waiting_for_key and not answered["key"]:
            answered["key"] = True
            process.send(b"\n")

    with SensorRecording(on_sample, enabled=use_sensors, cpu=False) as sensors:
        start = time.monotonic()
        process = stream_factory(
            [str(exe)],
            on_line,
            encoding_hint="utf-8",
            cwd=str(exe.parent),
            stdin_pipe=True,
            new_process_group=True,
            below_normal=True,
        )
        holder["process"] = process
        on_line("")  # ответить на вопросы, если они пришли до сохранения process
        cancelled = False
        while process.running:
            if holder.get("no_discrete"):
                break
            if cancel_event.wait(0.2):
                cancelled = True
                break
            elapsed = time.monotonic() - start
            if on_progress:
                on_progress(min(elapsed / duration, 1.0) if duration > 0 else 1.0)
            if elapsed >= duration:
                # Пробуем «Ctrl+Break»; до скрытой консоли он обычно не доходит, и тогда
                # stop() завершает утилиту вместе с её рабочим процессом-потомком. Это
                # безопасно: ошибки памяти утилита печатает сразу, итог не обязателен.
                process.interrupt()
                process.wait(0.5)
                break
        process.stop()
        elapsed = time.monotonic() - start

    if holder.get("no_discrete"):
        log.info("Тест видеопамяти пропущен: среди устройств Vulkan нет отдельной видеокарты")
        return TestResult(name=STRESS_VRAM, status=TestStatus.SKIPPED, notes=[NO_DISCRETE_GPU_NOTE])
    if cancelled:
        return TestResult(
            name=STRESS_VRAM,
            status=TestStatus.SKIPPED,
            component="gpu0",
            duration_s=elapsed,
            metrics={"cancelled": True},
            samples=sensors.samples,
            notes=["Тест остановлен пользователем."],
        )
    if on_progress:
        on_progress(1.0)
    result = to_result(parser.result, elapsed)
    result.samples = sensors.samples
    result.notes.extend(sensors.notes())
    return result
