"""Фоновый опрос датчиков во время нагрузочных тестов.

Источники (всё только чтение, драйверы не устанавливаются):
- видеокарты NVIDIA — `nvidia-smi --query-gpu=... -lms 1000` работает фоном и раз в секунду
  выдаёт строку CSV: температура, частоты, мощность, вентилятор, загрузка, причины
  снижения частот. Имя последнего поля зависит от версии драйвера — определяем через
  `nvidia-smi --help-query-gpu`;
- процессор — счётчик Windows «% Processor Performance» через WMI-класс
  `Win32_PerfFormattedData_Counters_ProcessorInformation` (работает без прав администратора
  и на любой языковой версии Windows). Реальная частота = номинальная × процент / 100;
- температура процессора напрямую — только если на компьютере УЖЕ установлен драйвер PawnIO
  и рядом с программой лежит LibreHardwareMonitorLib (чтение пока не реализовано);
- температура «тепловой зоны» ACPI (`MSAcpi_ThermalZoneTemperature`, root/wmi) — датчик
  материнской платы рядом с процессором, «примерно» (задача 25.3). Нужны права
  администратора и есть не на всех компьютерах; если класс недоступен, опрос сразу
  перестаёт его спрашивать. Значения в десятых долях кельвина переводятся в °C.

Недоступный датчик — это не ошибка: в `status` пишется понятная пометка.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hwcheck.collectors._util import to_float
from hwcheck.collectors.gpu_nvidia import find_nvidia_smi
from hwcheck.config import get_paths
from hwcheck.models import SensorSample
from hwcheck.platform import runner
from hwcheck.platform.runner import RunFn, StreamProcess
from hwcheck.thresholds import load_thresholds

log = logging.getLogger(__name__)

NVIDIA_BASE_FIELDS = [
    "timestamp",
    "index",
    "temperature.gpu",
    "clocks.sm",
    "clocks.mem",
    "power.draw",
    "fan.speed",
    "utilization.gpu",
]
REASON_FIELD_NEW = "clocks_event_reasons.active"
REASON_FIELD_OLD = "clocks_throttle_reasons.active"

# Названия значений в SensorSample для полей nvidia-smi (после timestamp и index).
_NVIDIA_VALUE_KEYS = [
    "temp_c",
    "clock_mhz",
    "mem_clock_mhz",
    "power_w",
    "fan_pct",
    "util_pct",
    "throttle_mask",
]

# Биты причин снижения частот (из документации NVML, nvmlClocksEventReasons).
THROTTLE_BITS = {
    0x1: "gpu_idle",
    0x2: "applications_clocks_setting",
    0x4: "sw_power_cap",
    0x8: "hw_slowdown",
    0x10: "sync_boost",
    0x20: "sw_thermal_slowdown",
    0x40: "hw_thermal_slowdown",
    0x80: "hw_power_brake_slowdown",
    0x100: "display_clock_setting",
}

CPU_SCRIPT = (
    "$zoneOk = $true; "
    "while ($true) { "
    "$x = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation "
    "-Filter \"Name='_Total'\"; "
    "$zone = ''; "
    "if ($zoneOk) { try { "
    "$z = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
    "-ErrorAction Stop | Measure-Object -Property CurrentTemperature -Maximum; "
    "if ($z.Maximum) { $zone = ([math]::Round($z.Maximum / 10 - 273.15, 1))"
    ".ToString([cultureinfo]::InvariantCulture) } "
    "} catch { $zoneOk = $false } }; "
    "'{0},{1},{2},{3}' -f $x.PercentProcessorPerformance,$x.ProcessorFrequency,"
    "$x.PercentProcessorUtility,$zone; "
    "Start-Sleep -Milliseconds {interval} }"
)

STATUS_OK = "ok"
GPU_UNAVAILABLE = (
    "Датчики видеокарты недоступны (нет nvidia-smi — карта не NVIDIA или нет драйвера)."
)
CPU_UNAVAILABLE = "Датчики частоты процессора недоступны."

StreamFactory = Callable[..., Any]


def detect_reason_field(nvidia_smi: str, run_fn: RunFn = runner.run) -> str:
    """Какое имя поля причин снижения частот понимает установленный драйвер."""
    result = run_fn([nvidia_smi, "--help-query-gpu"], timeout=15.0, encoding_hint="utf-8")
    if result.ok and REASON_FIELD_NEW in result.stdout:
        return REASON_FIELD_NEW
    return REASON_FIELD_OLD


def nvidia_query_command(nvidia_smi: str, reason_field: str, interval_ms: int = 1000) -> list[str]:
    """Команда фонового опроса nvidia-smi."""
    fields = ",".join([*NVIDIA_BASE_FIELDS, reason_field])
    return [
        nvidia_smi,
        f"--query-gpu={fields}",
        "--format=csv,noheader,nounits",
        "-lms",
        str(interval_ms),
    ]


def _number(text: str) -> float | None:
    text = text.strip()
    if not text or text.startswith("["):  # [N/A], [Not Supported]
        return None
    if text.lower().startswith("0x"):
        try:
            return float(int(text, 16))
        except ValueError:
            return None
    return to_float(text)


def parse_nvidia_line(line: str, t: float) -> SensorSample | None:
    """Строка CSV nvidia-smi → замер. Посторонние строки (сообщения об ошибках) → None."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != len(NVIDIA_BASE_FIELDS) + 1:
        return None
    index = _number(parts[1])
    if index is None:
        return None
    values = {key: _number(value) for key, value in zip(_NVIDIA_VALUE_KEYS, parts[2:], strict=True)}
    return SensorSample(t=t, component=f"gpu{int(index)}", values=values)


def decode_reasons(mask: float | None) -> list[str]:
    """Битовая маска причин снижения частот → список названий."""
    if mask is None:
        return []
    value = int(mask)
    return [name for bit, name in THROTTLE_BITS.items() if value & bit]


def parse_cpu_line(line: str, t: float) -> SensorSample | None:
    """Строка «процент_производительности,номинальная_частота,загрузка[,зона_°C]» → замер.

    Четвёртое поле — температура тепловой зоны ACPI (пусто, если недоступна)."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) not in (3, 4):
        return None
    perf, nominal, util = (_number(part) for part in parts[:3])
    if perf is None or nominal is None:
        return None
    values: dict[str, float | None] = {
        "clock_mhz": float(round(nominal * perf / 100)),
        "perf_pct": perf,
        "util_pct": util,
    }
    if len(parts) == 4 and parts[3]:
        values["zone_temp_c"] = _number(parts[3])  # точка: InvariantCulture в скрипте
    return SensorSample(t=t, component="cpu", values=values)


def cpu_temperature_support() -> tuple[bool, str]:
    """Можно ли читать температуру процессора, и если нет — почему (для «что не проверено»)."""
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    pawnio = windows / "System32" / "drivers" / "PawnIO.sys"
    lhm = get_paths().vendor / "lhm" / "LibreHardwareMonitorLib.dll"
    if not pawnio.is_file():
        return (
            False,
            "Температура процессора недоступна: на компьютере не установлен драйвер PawnIO.",
        )
    if not lhm.is_file() or importlib.util.find_spec("clr") is None:
        return False, "Температура процессора недоступна: нет библиотеки LibreHardwareMonitor."
    # Чтение через LibreHardwareMonitor не реализовано (см. docs/DECISIONS.md).
    return False, "Температура процессора недоступна: чтение через PawnIO пока не поддерживается."


class SensorPoller:
    """Запускает фоновые опросы датчиков и передаёт замеры в `on_sample`."""

    def __init__(
        self,
        on_sample: Callable[[SensorSample], None],
        run_fn: RunFn = runner.run,
        stream_factory: StreamFactory = StreamProcess,
        nvidia_smi: str | None = None,
        gpu: bool = True,
        cpu: bool = True,
        interval_ms: int | None = None,
        cpu_interval_ms: int | None = None,
    ) -> None:
        self.on_sample = on_sample
        self.run_fn = run_fn
        self.stream_factory = stream_factory
        self.nvidia_smi = nvidia_smi
        self.use_gpu = gpu
        self.use_cpu = cpu
        # Частота опроса — из thresholds.json. Частота процессора читается через WMI, а это
        # само по себе нагружает систему, поэтому её опрашиваем реже (задача 22.7).
        limits = load_thresholds()
        self.interval_ms = interval_ms or int(limits.get("sensors.gpu_poll_ms"))
        self.cpu_interval_ms = cpu_interval_ms or int(limits.get("sensors.cpu_poll_ms"))
        self.status: dict[str, str] = {}
        self._streams: list[Any] = []
        self._start = time.monotonic()
        self._lock = threading.Lock()

    def _elapsed(self) -> float:
        return round(time.monotonic() - self._start, 2)

    def _emit(self, sample: SensorSample | None) -> None:
        if sample is not None:
            with self._lock:
                self.on_sample(sample)

    def start(self) -> None:
        self._start = time.monotonic()
        if self.use_gpu:
            self._start_gpu()
        if self.use_cpu:
            self._start_cpu()
        _available, reason = cpu_temperature_support()
        self.status["cpu_temp"] = reason

    def _start_gpu(self) -> None:
        exe = self.nvidia_smi or find_nvidia_smi()
        try:
            field = detect_reason_field(exe, self.run_fn)
            cmd = nvidia_query_command(exe, field, self.interval_ms)
            stream = self.stream_factory(
                cmd,
                lambda line: self._emit(parse_nvidia_line(line, self._elapsed())),
                below_normal=True,
            )
        except (FileNotFoundError, OSError) as error:
            log.info("Опрос датчиков видеокарты недоступен: %s", error)
            self.status["gpu"] = GPU_UNAVAILABLE
            return
        self._streams.append(stream)
        self.status["gpu"] = STATUS_OK

    def _start_cpu(self) -> None:
        script = CPU_SCRIPT.replace("{interval}", str(self.cpu_interval_ms))
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
        try:
            stream = self.stream_factory(
                cmd,
                lambda line: self._emit(parse_cpu_line(line, self._elapsed())),
                below_normal=True,
            )
        except (FileNotFoundError, OSError) as error:
            log.info("Опрос частоты процессора недоступен: %s", error)
            self.status["cpu"] = CPU_UNAVAILABLE
            return
        self._streams.append(stream)
        self.status["cpu"] = STATUS_OK

    def stop(self) -> None:
        for stream in self._streams:
            stream.stop()
        self._streams.clear()


class SensorRecording:
    """Запись датчиков на время одного теста: `with SensorRecording(on_sample) as rec: ...`.

    Замеры пересылаются в `on_sample` (живые графики) и копятся в `rec.samples`.
    Пометки о недоступных датчиках — в `rec.notes()`.
    """

    def __init__(
        self,
        on_sample: Callable[[SensorSample], None] | None,
        enabled: bool = True,
        gpu: bool = True,
        cpu: bool = True,
        poller_factory: Callable[..., SensorPoller] = SensorPoller,
        extra_check: Callable[[SensorSample], None] | None = None,
    ) -> None:
        self.samples: list[SensorSample] = []
        self._on_sample = on_sample
        self._extra_check = extra_check
        self._poller = poller_factory(self._record, gpu=gpu, cpu=cpu) if enabled else None

    def _record(self, sample: SensorSample) -> None:
        self.samples.append(sample)
        if self._on_sample:
            self._on_sample(sample)
        if self._extra_check:
            self._extra_check(sample)

    def notes(self) -> list[str]:
        if self._poller is None:
            return []
        return [
            text
            for key, text in self._poller.status.items()
            if text != STATUS_OK and key != "cpu_temp"
        ]

    def __enter__(self) -> SensorRecording:
        if self._poller is not None:
            self._poller.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._poller is not None:
            self._poller.stop()
