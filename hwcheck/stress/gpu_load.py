"""Нагрузка ядра видеокарты и анализ её поведения под нагрузкой.

Нагрузка: тяжёлый вычислительный шейдер через wgpu (WebGPU поверх Vulkan/D3D12) в ОТДЕЛЬНОМ
процессе — если драйвер видеокарты «упадёт», программа останется жива. Шейдер запускается
короткими порциями (десятки миллисекунд), чтобы Windows не посчитала видеокарту зависшей.

Параллельно опрашиваются датчики (nvidia-smi). По графику считаем:
- максимальную и среднюю температуру (среднюю — на установившемся участке);
- падение частоты от начала к концу нагрузки и её стабильность;
- причины снижения частот (перегрев / лимит мощности);
- работу вентилятора: не раскручивается при нагреве или, наоборот, крутится на максимуме
  при умеренной температуре.

Если wgpu недоступен — тест «пропущен» с объяснением; вердикт опирается на тест видеопамяти.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import statistics
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from hwcheck.backends.base import STRESS_GPU_LOAD, ProgressCallback, SampleCallback
from hwcheck.models import SensorSample, TestResult, TestStatus
from hwcheck.platform.priority import lower_own_priority
from hwcheck.stress.sensors import SensorRecording, decode_reasons
from hwcheck.thresholds import Thresholds, load_thresholds

log = logging.getLogger(__name__)

THERMAL_REASONS = {"sw_thermal_slowdown", "hw_thermal_slowdown", "hw_slowdown"}
POWER_REASONS = {"sw_power_cap", "hw_power_brake_slowdown"}
IGNORED_REASONS = {"gpu_idle", "applications_clocks_setting", "display_clock_setting"}

UNAVAILABLE_NOTE = (
    "Нагрузку на видеокарту создать не удалось (WebGPU недоступен). "
    "Вердикт по видеокарте опирается на тест видеопамяти."
)

# ---------------------------------------------------------------------------
# Анализ графиков датчиков
# ---------------------------------------------------------------------------


def _values(samples: list[SensorSample], key: str) -> list[float]:
    return [v for s in samples if (v := s.values.get(key)) is not None]


def pick_loaded_gpu(samples: list[SensorSample]) -> str | None:
    """Какая из видеокарт реально была под нагрузкой (по средней загрузке)."""
    by_gpu: dict[str, list[float]] = {}
    for sample in samples:
        if sample.component.startswith("gpu"):
            util = sample.values.get("util_pct")
            by_gpu.setdefault(sample.component, []).append(util or 0.0)
    if not by_gpu:
        return None
    return max(by_gpu, key=lambda key: statistics.fmean(by_gpu[key]))


def analyze_gpu_series(
    samples: list[SensorSample], thresholds: Thresholds | None = None
) -> dict[str, Any]:
    """Считает метрики поведения видеокарты по замерам одной карты."""
    th = thresholds or load_thresholds()
    metrics: dict[str, Any] = {"samples": len(samples)}
    temps = _values(samples, "temp_c")
    # Частоты считаем только там, где карта реально загружена (без разгона и простоя).
    loaded = [s for s in samples if (s.values.get("util_pct") or 0) >= 50] or samples
    clocks = _values(loaded, "clock_mhz")
    fans = _values(samples, "fan_pct")
    powers = _values(samples, "power_w")

    if temps:
        steady = temps[len(temps) // 2 :] or temps
        metrics["max_temp_c"] = max(temps)
        metrics["avg_temp_c"] = round(statistics.fmean(steady), 1)
        metrics["overheating"] = max(temps) >= th.get("gpu.warning_c")
    if clocks and len(clocks) >= 4:
        head = clocks[: max(1, len(clocks) // 5)]
        tail = clocks[-max(1, len(clocks) * 3 // 10) :]
        start, end = statistics.median(head), statistics.median(tail)
        metrics["start_clock_mhz"] = start
        metrics["end_clock_mhz"] = end
        metrics["clock_drop_pct"] = (
            round(max(0.0, (start - end) / start * 100), 1) if start else 0.0
        )
        spread = statistics.pstdev(tail) / statistics.fmean(tail) if statistics.fmean(tail) else 0
        metrics["clock_stable"] = spread < 0.05
    if fans:
        metrics["max_fan_pct"] = max(fans)
        metrics["fan_high_at_moderate_temp"] = bool(
            temps
            and max(fans) >= th.get("gpu.fan_high_pct")
            and max(temps) < th.get("gpu.fan_moderate_temp_c")
        )
        metrics["fan_not_spinning"] = bool(
            temps
            and max(temps) >= th.get("gpu.fan_moderate_temp_c")
            and max(fans) <= fans[0]
            and max(fans) < 30
        )
    else:
        metrics["max_fan_pct"] = None
    if powers:
        metrics["max_power_w"] = max(powers)

    reasons: set[str] = set()
    for sample in samples:
        reasons.update(decode_reasons(sample.values.get("throttle_mask")))
    active = sorted(reasons - IGNORED_REASONS)
    metrics["throttle_reasons"] = active
    metrics["thermal_throttle"] = bool(set(active) & THERMAL_REASONS)
    metrics["power_throttle"] = bool(set(active) & POWER_REASONS)
    return metrics


def status_from_metrics(
    metrics: dict[str, Any], thresholds: Thresholds | None = None
) -> TestStatus:
    """PASSED, если поведение нормальное; WARNING, если есть повод насторожиться."""
    th = thresholds or load_thresholds()
    problems = [
        metrics.get("overheating"),
        metrics.get("thermal_throttle"),
        metrics.get("fan_not_spinning"),
        metrics.get("fan_high_at_moderate_temp"),
        (metrics.get("clock_drop_pct") or 0) > th.get("gpu.clock_drop_pct"),
    ]
    return TestStatus.WARNING if any(problems) else TestStatus.PASSED


# ---------------------------------------------------------------------------
# Нагрузка (отдельный процесс)
# ---------------------------------------------------------------------------

WGSL = """
@group(0) @binding(0) var<storage, read_write> data: array<f32>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    var x = data[id.x];
    var y = f32(id.x) * 0.0001;
    for (var i = 0u; i < 4096u; i = i + 1u) {
        x = fma(x, 1.000001, y);
        y = fma(y, 0.999999, x * 0.000001);
    }
    data[id.x] = x + y;
}
"""


INTEGRATED_NOTE = (
    "Отдельной видеокарты нет: встроенную графику под нагрузку не ставим — она делит память "
    "и питание с процессором, и ноутбук может зависнуть. Графику проверяют сводка и журнал "
    "ошибок Windows."
)


def gpu_worker(stop: Any, queue: Any, max_seconds: float) -> None:
    """Код дочернего процесса: крутит шейдер, пока не попросят остановиться."""
    lower_own_priority()  # подготовка кадров не должна отнимать процессор у окна (22.7)
    try:
        import wgpu

        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if adapter.info.get("adapter_type") != "DiscreteGPU":
            # Встроенная графика делит память и питание с процессором: нагрузка на неё
            # подвешивает ноутбук, а отдельной видеокарты для проверки нет (задача 22.7).
            queue.put({"integrated": adapter.info.get("device", "")})
            return
        device = adapter.request_device_sync()
        count = 1 << 20
        buffer = device.create_buffer(
            size=count * 4, usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC
        )
        shader = device.create_shader_module(code=WGSL)
        pipeline = device.create_compute_pipeline(
            layout="auto", compute={"module": shader, "entry_point": "main"}
        )
        bind_group = device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": buffer, "offset": 0, "size": count * 4}}
            ],
        )
        queue.put({"adapter": adapter.info.get("device", "")})
        dispatches = 0
        started = time.monotonic()
        while not stop.is_set() and time.monotonic() - started < max_seconds:
            encoder = device.create_command_encoder()
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(pipeline)
            compute.set_bind_group(0, bind_group)
            compute.dispatch_workgroups(count // 256)
            compute.end()
            device.queue.submit([encoder.finish()])
            # Ждём окончания порции, прочитав 4 байта (on_submitted_work_done_sync в wgpu 0.32
            # не работает). Так очередь не разрастается и остановка срабатывает быстро.
            device.queue.read_buffer(buffer, 0, 4)
            dispatches += 1
        queue.put({"done": True, "dispatches": dispatches})
    except Exception as error:  # сообщаем причину в основной процесс
        queue.put({"error": f"{type(error).__name__}: {error}"})


class LoadWorker(Protocol):
    """Интерфейс процесса нагрузки (настоящего или подменного в тестах)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_alive(self) -> bool: ...
    def messages(self) -> list[dict[str, Any]]: ...


class ProcessWorker:
    """Процесс нагрузки на multiprocessing (работает и в собранной программе)."""

    def __init__(self, target: Callable[..., None], max_seconds: float) -> None:
        ctx = mp.get_context("spawn")
        self._stop = ctx.Event()
        self._queue = ctx.Queue()
        self._process = ctx.Process(
            target=target, args=(self._stop, self._queue, max_seconds), daemon=True
        )
        self._messages: list[dict[str, Any]] = []

    def start(self) -> None:
        self._process.start()

    def stop(self) -> None:
        self._stop.set()
        self._process.join(timeout=2.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)

    def is_alive(self) -> bool:
        return self._process.is_alive()

    def messages(self) -> list[dict[str, Any]]:
        while True:
            try:
                self._messages.append(self._queue.get_nowait())
            except Exception:  # очередь пуста
                break
        return self._messages


def run_gpu_load(
    duration: float,
    cancel_event: threading.Event,
    on_progress: ProgressCallback | None = None,
    on_sample: SampleCallback | None = None,
    worker_factory: Callable[[float], LoadWorker] | None = None,
    use_sensors: bool = True,
    thresholds: Thresholds | None = None,
) -> TestResult:
    """Нагружает видеокарту `duration` секунд и анализирует её поведение."""
    factory = worker_factory or (lambda seconds: ProcessWorker(gpu_worker, seconds))
    worker = factory(duration + 10)
    cancelled = False
    with SensorRecording(on_sample, enabled=use_sensors, cpu=False) as sensors:
        start = time.monotonic()
        worker.start()
        while True:
            if cancel_event.wait(0.2):
                cancelled = True
                break
            elapsed = time.monotonic() - start
            if on_progress:
                on_progress(min(elapsed / duration, 1.0) if duration > 0 else 1.0)
            messages = worker.messages()
            if any("error" in m or "integrated" in m for m in messages) or not worker.is_alive():
                break
            if elapsed >= duration:
                break
        worker.stop()
        elapsed = time.monotonic() - start

    messages = worker.messages()
    error = next((m["error"] for m in messages if "error" in m), None)
    adapter = next((m["adapter"] for m in messages if "adapter" in m), "")
    integrated = next((m["integrated"] for m in messages if "integrated" in m), None)
    if cancelled:
        return TestResult(
            name=STRESS_GPU_LOAD,
            status=TestStatus.SKIPPED,
            component="gpu0",
            duration_s=elapsed,
            metrics={"cancelled": True},
            samples=sensors.samples,
            notes=["Тест остановлен пользователем."],
        )
    if integrated is not None:
        log.info("Нагрузка GPU пропущена: доступна только встроенная графика %s", integrated)
        return TestResult(
            name=STRESS_GPU_LOAD,
            status=TestStatus.SKIPPED,
            component="gpu0",
            duration_s=elapsed,
            metrics={"integrated": integrated},
            notes=[INTEGRATED_NOTE],
        )
    if error:
        log.warning("Нагрузка GPU недоступна: %s", error)
        return TestResult(
            name=STRESS_GPU_LOAD,
            status=TestStatus.SKIPPED,
            component="gpu0",
            duration_s=elapsed,
            metrics={"error": error},
            notes=[UNAVAILABLE_NOTE],
        )
    component = pick_loaded_gpu(sensors.samples) or "gpu0"
    own = [s for s in sensors.samples if s.component == component]
    metrics = analyze_gpu_series(own, thresholds)
    metrics["adapter"] = adapter
    result = TestResult(
        name=STRESS_GPU_LOAD,
        status=status_from_metrics(metrics, thresholds),
        component=component,
        duration_s=elapsed,
        metrics=metrics,
        samples=sensors.samples,
        notes=sensors.notes(),
    )
    if not own:
        result.notes.append("Датчики видеокарты недоступны: температура под нагрузкой неизвестна.")
    return result
