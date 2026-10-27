"""Тесты опроса датчиков: разбор потока nvidia-smi и CPU, недоступные датчики."""

from collections.abc import Callable
from typing import Any

from hwcheck.models import SensorSample
from hwcheck.platform.runner import RunResult
from hwcheck.stress import sensors
from hwcheck.thresholds import load_thresholds
from tests.helpers import FakeRun, fixture_text


def _lines() -> list[str]:
    return fixture_text("nvidia_smi", "query_stream.csv").splitlines()


def test_parse_normal_line() -> None:
    sample = sensors.parse_nvidia_line(_lines()[1], t=1.0)
    assert sample is not None
    assert sample.component == "gpu0"
    assert sample.t == 1.0
    assert sample.values == {
        "temp_c": 61.0,
        "clock_mhz": 1890.0,
        "mem_clock_mhz": 4001.0,
        "power_w": 118.2,
        "fan_pct": 45.0,
        "util_pct": 99.0,
        "throttle_mask": 4.0,
    }


def test_parse_second_gpu_with_na() -> None:
    sample = sensors.parse_nvidia_line(_lines()[2], t=1.0)
    assert sample is not None
    assert sample.component == "gpu1"
    assert sample.values["power_w"] is None
    assert sample.values["fan_pct"] == 100.0


def test_parse_all_na_and_garbage() -> None:
    sample = sensors.parse_nvidia_line(_lines()[4], t=3.0)
    assert sample is not None
    assert all(v is None for v in sample.values.values())
    assert sensors.parse_nvidia_line(_lines()[5], t=4.0) is None
    assert sensors.parse_nvidia_line("", t=0) is None


def test_decode_throttle_mask() -> None:
    assert sensors.decode_reasons(0x24) == ["sw_power_cap", "sw_thermal_slowdown"]
    assert sensors.decode_reasons(0x1) == ["gpu_idle"]
    assert sensors.decode_reasons(None) == []


def test_detect_reason_field() -> None:
    new = FakeRun(fixture_text("nvidia_smi", "help_query_new.txt"))
    old = FakeRun(fixture_text("nvidia_smi", "help_query_old.txt"))
    assert sensors.detect_reason_field("nvidia-smi", run_fn=new) == "clocks_event_reasons.active"
    assert sensors.detect_reason_field("nvidia-smi", run_fn=old) == "clocks_throttle_reasons.active"


def test_query_command() -> None:
    cmd = sensors.nvidia_query_command("nvidia-smi", "clocks_event_reasons.active", 1000)
    assert cmd[0] == "nvidia-smi"
    assert "--format=csv,noheader,nounits" in cmd
    assert cmd[-2:] == ["-lms", "1000"]
    assert cmd[1].startswith("--query-gpu=timestamp,index,temperature.gpu")


def test_parse_cpu_line() -> None:
    sample = sensors.parse_cpu_line("128,2904,8", t=2.0)
    assert sample is not None
    assert sample.component == "cpu"
    assert sample.values["clock_mhz"] == round(2904 * 1.28)
    assert sample.values["perf_pct"] == 128.0
    assert sample.values["util_pct"] == 8.0
    assert sensors.parse_cpu_line("ошибка", t=0) is None


class FakeStream:
    """Подмена StreamProcess: сразу «выдаёт» заранее заданные строки."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.stopped = False

    def factory(self) -> Callable[..., Any]:
        def make(cmd: list[str], on_line: Callable[[str], None], **kwargs: Any) -> "FakeStream":
            for line in self.lines:
                on_line(line)
            return self

        return make

    def stop(self, grace: float = 1.0) -> None:
        self.stopped = True


def test_poller_collects_gpu_and_cpu_samples() -> None:
    got: list[SensorSample] = []
    gpu_stream = FakeStream(_lines()[:2])
    cpu_stream = FakeStream(["130,2904,99"])

    def stream_factory(cmd: list[str], on_line: Callable[[str], None], **kwargs: Any) -> Any:
        source = gpu_stream if "nvidia" in cmd[0] else cpu_stream
        return source.factory()(cmd, on_line)

    poller = sensors.SensorPoller(
        got.append,
        run_fn=FakeRun(fixture_text("nvidia_smi", "help_query_new.txt")),
        stream_factory=stream_factory,
        nvidia_smi="nvidia-smi",
    )
    poller.start()
    poller.stop()
    assert [s.component for s in got] == ["gpu0", "gpu0", "cpu"]
    assert gpu_stream.stopped and cpu_stream.stopped
    assert poller.status["gpu"] == sensors.STATUS_OK


def test_poller_unavailable_sensors_are_notes_not_errors() -> None:
    def missing(cmd: list[str], on_line: Callable[[str], None], **kwargs: Any) -> Any:
        raise FileNotFoundError(cmd[0])

    poller = sensors.SensorPoller(
        lambda s: None,
        run_fn=FakeRun("", returncode=None, not_found=True),
        stream_factory=missing,
        nvidia_smi="nvidia-smi",
    )
    poller.start()
    poller.stop()
    assert "недоступн" in poller.status["gpu"]
    assert "недоступн" in poller.status["cpu"]
    assert "недоступн" in poller.status["cpu_temp"]


def test_cpu_temperature_not_available_without_pawnio() -> None:
    available, reason = sensors.cpu_temperature_support()
    assert available is False
    assert "PawnIO" in reason


def test_help_query_failure_falls_back_to_old_name() -> None:
    fake = FakeRun("", returncode=None, not_found=True)
    assert (
        sensors.detect_reason_field("nvidia-smi", run_fn=fake) == "clocks_throttle_reasons.active"
    )


def test_run_result_import_used() -> None:
    assert RunResult(0, "", "", 0.0).ok


def test_poll_intervals_come_from_thresholds() -> None:
    """Частота процессора (WMI) опрашивается реже видеокарты — это нагружает систему (22.7)."""
    commands: list[list[str]] = []

    def stream_factory(cmd: list[str], on_line: Callable[[str], None], **kwargs: Any) -> Any:
        commands.append(cmd)
        return FakeStream([]).factory()(cmd, on_line)

    poller = sensors.SensorPoller(
        lambda s: None,
        run_fn=FakeRun(fixture_text("nvidia_smi", "help_query_new.txt")),
        stream_factory=stream_factory,
        nvidia_smi="nvidia-smi",
    )
    limits = load_thresholds()
    assert poller.cpu_interval_ms == limits.get("sensors.cpu_poll_ms") >= 2000
    assert poller.interval_ms == limits.get("sensors.gpu_poll_ms")
    poller.start()
    poller.stop()
    gpu_cmd = next(c for c in commands if "nvidia" in c[0])
    cpu_cmd = next(c for c in commands if c[0] == "powershell.exe")
    assert gpu_cmd[-1] == str(poller.interval_ms)
    assert f"Start-Sleep -Milliseconds {poller.cpu_interval_ms}" in cpu_cmd[-1]


def test_cpu_line_with_thermal_zone() -> None:
    """25.3: четвёртое поле — температура тепловой зоны ACPI (°C) или пусто."""
    sample = sensors.parse_cpu_line("128,2904,8,61.5", t=1.0)
    assert sample is not None and sample.values["zone_temp_c"] == 61.5
    empty = sensors.parse_cpu_line("128,2904,8,", t=1.0)
    assert empty is not None and "zone_temp_c" not in empty.values


def test_cpu_script_reads_thermal_zone_once_and_invariant() -> None:
    script = sensors.CPU_SCRIPT
    assert "MSAcpi_ThermalZoneTemperature" in script and "root/wmi" in script
    assert "$zoneOk = $false" in script  # после первой неудачи класс больше не спрашивается
    assert "InvariantCulture" in script  # «61.5», а не «61,5» на русской Windows
