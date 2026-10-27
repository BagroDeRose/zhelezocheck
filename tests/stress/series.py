"""Построение синтетических графиков датчиков для тестов анализа."""

from collections.abc import Sequence

from hwcheck.models import SensorSample


def ramp(start: float, end: float, n: int, plateau_from: float = 0.5) -> list[float]:
    """Рост от start до end за первую часть графика, дальше — ровно end."""
    rise = max(1, int(n * plateau_from))
    return [start + (end - start) * min(i / rise, 1.0) for i in range(n)]


def gpu_samples(
    n: int = 60, component: str = "gpu0", **series: Sequence[float | None]
) -> list[SensorSample]:
    samples = []
    for i in range(n):
        values = {
            key: (values_list[i] if i < len(values_list) else None)
            for key, values_list in series.items()
        }
        values.setdefault("util_pct", 99.0)
        samples.append(SensorSample(t=float(i), component=component, values=values))
    return samples
