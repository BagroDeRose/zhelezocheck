"""Графики технического отчёта из реальных временных рядов (SPEC_V2_1, этап 44).

Графики строятся из сохранённых замеров теста (`schema.series_points`), а не из картинок:
их можно перерисовать из истории в любой момент. Правила:
- один график — одна группа датчиков с общей единицей («частоты ядра и памяти, МГц»);
- нет точек датчика — нет и серии; ни одной серии — нет графика (нули не рисуем);
- пропал датчик на время — линия рвётся (разрыв больше трёх обычных интервалов);
- подписи осей с единицами, легенда с мин/сред/макс, время начала и конца, отметки
  начала/конца нагрузки, прерываний и аварийных остановок;
- серии можно скрыть галочкой — чистым CSS, без скриптов (отчёт офлайн и без JS).

Живой график в окне программы (`ui/widgets/chart.py`) рисуется через Qt и в HTML не
переносится; общий у них — источник данных (замеры теста).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from hwcheck.models import CheckSession, SeriesMarker, TestResult
from hwcheck.schema import SeriesStats, sensor_by_name, series_points, series_stats
from hwcheck.thresholds import Thresholds, load_thresholds

TEST_TITLES = {
    "cpu_load": "Нагрузка процессора",
    "gpu_load": "Нагрузка видеокарты",
    "vram": "Тест видеопамяти",
    "ram_quick": "Тест памяти",
    "disk_read": "Тест чтения диска",
}

# Группы датчиков: (название графика, имена датчиков из реестра schema.py).
CPU_GROUPS = [
    ("частота", ["clock"]),
    ("загрузка", ["utilization"]),
    ("температура тепловой зоны", ["zone_temp"]),
]
GPU_GROUPS = [
    ("температура", ["temperature"]),
    ("частоты ядра и памяти", ["core_clock", "memory_clock"]),
    ("загрузка и вентилятор", ["utilization", "memory_utilization", "fan"]),
    ("потребление", ["power"]),
    ("занятая видеопамять", ["vram_used"]),
]
# Пороги, по которым программа делает выводы, — линиями на графике (из thresholds.json).
LIMITS = {
    ("gpu", "температура"): [
        ("gpu.warning_c", "порог «сильно греется»"),
        ("gpu.emergency_stop_c", "аварийная остановка"),
    ],
}
COLORS = ["#b3261e", "#3b5bab", "#1b7f3b", "#b26a00", "#6a3bab"]
MARKER_COLORS = {"start": "#888888", "end": "#888888", "interrupt": "#b26a00"}
GAP_FACTOR = 3.0  # разрыв линии, если между точками больше трёх обычных интервалов
FLAT_MIN_POINTS = 10  # ровный ряд из стольких точек — пометка «значение не менялось»

WIDTH, PLOT_HEIGHT = 760, 200
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 60, 16, 14, 30
LEGEND_LINE = 18
LEGEND_CHARS = 110  # примерно столько символов 11-го кегля помещается в строку легенды


@dataclass
class ChartSeries:
    sensor_id: str
    label: str
    color: str
    stats: SeriesStats
    segments: list[list[tuple[float, float]]] = field(default_factory=list)


@dataclass
class Chart:
    title: str
    unit: str
    series: list[ChartSeries]
    markers: list[SeriesMarker]
    period: str
    x_max: float
    limits: list[tuple[float, str]] = field(default_factory=list)  # пороги из thresholds.json


def _segments(points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Делит точки на непрерывные куски: большой пропуск по времени — новая линия."""
    if len(points) < 2:
        return [points] if points else []
    steps = [b[0] - a[0] for a, b in zip(points, points[1:], strict=False) if b[0] > a[0]]
    limit = GAP_FACTOR * statistics.median(steps) if steps else float("inf")
    segments = [[points[0]]]
    for previous, current in zip(points, points[1:], strict=False):
        if current[0] - previous[0] > limit:
            segments.append([])
        segments[-1].append(current)
    return segments


def _period(result: TestResult, x_max: float) -> str:
    if result.started_at:
        try:
            start = datetime.fromisoformat(result.started_at)
        except ValueError:
            start = None
        if start is not None:
            end = start + timedelta(seconds=x_max)
            return f"начало {start:%H:%M:%S}, конец {end:%H:%M:%S} ({x_max:.0f} с)"
    return f"время начала неизвестно; {x_max:.0f} с от начала теста"


def _limits(component: str, group_title: str, thresholds: Thresholds) -> list[tuple[float, str]]:
    kind = "gpu" if component.startswith("gpu") else component
    return [
        (float(thresholds.get(key)), label) for key, label in LIMITS.get((kind, group_title), [])
    ]


def _charts_for(result: TestResult, thresholds: Thresholds) -> list[Chart]:
    points = series_points(result)
    if not points:
        return []
    components = sorted({p.sensor_id.split(".")[0] for p in points})
    prefix = TEST_TITLES.get(result.name, result.name)
    end = max([p.elapsed_seconds for p in points] + [m.elapsed_seconds for m in result.markers])
    charts: list[Chart] = []
    for component in components:
        groups = CPU_GROUPS if component == "cpu" else GPU_GROUPS
        if not component.startswith(("cpu", "gpu")):
            continue
        multi = (
            component.startswith("gpu") and len([c for c in components if c.startswith("gpu")]) > 1
        )
        device = f" (GPU {int(component[3:]) + 1})" if multi else ""
        for group_title, names in groups:
            series: list[ChartSeries] = []
            unit = ""
            for name in names:
                identifier = f"{component}.{name}"
                own = [(p.elapsed_seconds, p.value) for p in points if p.sensor_id == identifier]
                stats = series_stats(result, identifier)
                if len(own) < 2 or stats is None:
                    continue  # датчик молчал или дал одну точку — линии нет
                definition = sensor_by_name(component, name)
                label = definition.label if definition else identifier
                unit = stats.unit
                series.append(
                    ChartSeries(
                        identifier, label, COLORS[len(series) % len(COLORS)], stats, _segments(own)
                    )
                )
            if series:
                charts.append(
                    Chart(
                        title=f"{prefix}{device}: {group_title}",
                        unit=unit,
                        series=series,
                        markers=list(result.markers),
                        period=_period(result, end),
                        x_max=end,
                        limits=_limits(component, group_title, thresholds),
                    )
                )
    return charts


def build_series_charts(session: CheckSession, thresholds: Thresholds | None = None) -> list[Chart]:
    """Все графики проверки по тестам, у которых есть замеры датчиков."""
    limits = thresholds or load_thresholds()
    charts: list[Chart] = []
    for result in session.results:
        charts += _charts_for(result, limits)
    return charts


# --------------------------------------------------------------------------
# Рисование (SVG) и HTML с переключателями серий
# --------------------------------------------------------------------------


def _number(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"


def _ticks(low: float, high: float, count: int = 5) -> list[float]:
    step = (high - low) / (count - 1)
    return [low + step * index for index in range(count)]


def _nice_step(span: float, count: int = 5) -> float:
    """Круглый шаг подписей оси: 1, 2, 2,5 или 5 × 10ⁿ (ручная проверка rc1: «1662, 2300…»)."""
    raw = span / max(count - 1, 1)
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= factor * power:
            return factor * power
    return 10.0 * power


def _value_axis(values: list[float]) -> tuple[float, float, list[float], int]:
    """Границы оси значений, круглые подписи и число знаков после запятой.

    Ровный ряд получает видимый диапазон (иначе подписи «28 28 28»); у величин, которые не
    бывают отрицательными, ось не уходит ниже нуля (иначе «−7.8 %»)."""
    low, high = min(values), max(values)
    if high - low < 1e-9:
        pad = max(abs(high) * 0.05, 1.0)
        low, high = low - pad, high + pad
    step = _nice_step(high - low)
    start = math.floor(low / step) * step
    end = math.ceil(high / step) * step
    if min(values) >= 0 and start < 0:
        start = 0.0
    ticks = []
    tick = start
    while tick <= end + step * 1e-6:
        ticks.append(round(tick, 6))
        tick += step
    digits = 0 if step >= 1 else len(f"{step:.6f}".rstrip("0").split(".")[1])
    return start, end, ticks, digits


def _axis_label(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def legend_lines(series: ChartSeries) -> list[str]:
    """Текст легенды серии: одна строка или две, если не помещается в ширину графика.

    Ручная проверка 2.1.0-rc2: у тепловой зоны строка с пометкой обрезалась на краю PDF."""
    stats = series.stats
    unit = f" {stats.unit}" if stats.unit else ""
    # Ровный ряд — повод не доверять датчику (зона ACPI 27,9 °C весь тест на rc1).
    # Только температура: ровные 99 % загрузки или 4001 МГц памяти — норма, а не сбой.
    flat = (
        " — значение не менялось"
        if stats.unit == "°C"
        and stats.count >= FLAT_MIN_POINTS
        and stats.maximum - stats.minimum < 1e-9
        else ""
    )
    main = (
        f"{series.label}: мин {_number(stats.minimum)} · сред {_number(stats.average)} · "
        f"макс {_number(stats.maximum)}{unit}"
    )
    tail = f"({_short_source(stats.source)}){flat}"
    if len(main) + 1 + len(tail) <= LEGEND_CHARS:
        return [f"{main} {tail}"]
    return [main, tail]


def _short_source(source: str) -> str:
    """Источник в легенде — без длинного пояснения в скобках (оно есть в таблице отчёта)."""
    return source.split(" (")[0]


def render_svg(chart: Chart, chart_id: str) -> str:
    """График как SVG-строка: оси с единицами, линии серий, отметки, легенда с мин/сред/макс."""
    values = [v for s in chart.series for seg in s.segments for _, v in seg]
    values += [value for value, _ in chart.limits]  # порог виден, даже если до него не дошли
    low, high, value_ticks, digits = _value_axis(values)
    x_max = chart.x_max or 1.0
    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    legends = [legend_lines(series) for series in chart.series]
    legend_rows = [sum(len(lines) for lines in legends[:index]) for index in range(len(legends))]
    legend_h = LEGEND_LINE * sum(len(lines) for lines in legends) + 8
    height = PAD_TOP + PLOT_HEIGHT + PAD_BOTTOM + legend_h

    def sx(x: float) -> float:
        return PAD_LEFT + x / x_max * plot_w

    def sy(y: float) -> float:
        return PAD_TOP + (1 - (y - low) / (high - low)) * PLOT_HEIGHT

    bottom = PAD_TOP + PLOT_HEIGHT
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="{escape(chart.title)}">',
        f'<rect x="0" y="0" width="{WIDTH}" height="{height}" fill="#ffffff"/>',
    ]
    for tick in value_ticks:
        y = sy(tick)
        parts.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{PAD_LEFT + plot_w}" y2="{y:.1f}" '
            'stroke="#eeeeee"/>'
            f'<text x="{PAD_LEFT - 6}" y="{y + 4:.1f}" font-size="11" fill="#444" '
            f'text-anchor="end">{_axis_label(tick, digits)}</text>'
        )
    for tick in _ticks(0.0, x_max, 6):
        x = sx(tick)
        parts.append(
            f'<text x="{x:.1f}" y="{bottom + 16}" font-size="11" fill="#444" '
            f'text-anchor="middle">{tick:.0f} с</text>'
        )
    parts.append(
        f'<line x1="{PAD_LEFT}" y1="{bottom}" x2="{PAD_LEFT + plot_w}" y2="{bottom}" '
        'stroke="#999"/>'
        f'<line x1="{PAD_LEFT}" y1="{PAD_TOP}" x2="{PAD_LEFT}" y2="{bottom}" stroke="#999"/>'
        f'<text x="8" y="{PAD_TOP + 10}" font-size="11" fill="#222">{escape(chart.unit)}</text>'
    )
    for value, label in chart.limits:
        y = sy(value)
        parts.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{PAD_LEFT + plot_w}" y2="{y:.1f}" '
            'stroke="#b3261e" stroke-width="1" stroke-dasharray="6 4"/>'
            # Подпись порога — слева: справа вверху подписи отметок «Конец нагрузки»
            # (на ручной проверке rc1 они наезжали друг на друга).
            f'<text x="{PAD_LEFT + 6}" y="{y - 4:.1f}" font-size="10" fill="#b3261e" '
            f'text-anchor="start">{escape(label)}: {_number(value)} {escape(chart.unit)}</text>'
        )
    for marker in chart.markers:
        x = sx(min(marker.elapsed_seconds, x_max))
        color = MARKER_COLORS.get(marker.kind, "#b3261e")
        parts.append(
            f'<line x1="{x:.1f}" y1="{PAD_TOP}" x2="{x:.1f}" y2="{bottom}" stroke="{color}" '
            'stroke-dasharray="4 3"/>'
        )
        if marker.kind != "start":
            parts.append(
                f'<text x="{x - 4:.1f}" y="{PAD_TOP + 12}" font-size="10" fill="{color}" '
                f'text-anchor="end">{escape(marker.text)}</text>'
            )
    for index, series in enumerate(chart.series):
        css = f"s-{chart_id}s{index}"
        group = [f'<g class="{css}">']
        for segment in series.segments:
            if len(segment) == 1:
                x, y = segment[0]
                group.append(
                    f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2" fill="{series.color}"/>'
                )
                continue
            path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in segment)
            group.append(
                f'<polyline fill="none" stroke="{series.color}" stroke-width="2" points="{path}"/>'
            )
        legend_y = bottom + PAD_BOTTOM + LEGEND_LINE * legend_rows[index] + 12
        group.append(
            f'<line x1="{PAD_LEFT}" y1="{legend_y - 4}" x2="{PAD_LEFT + 18}" y2="{legend_y - 4}" '
            f'stroke="{series.color}" stroke-width="3"/>'
        )
        for row, text in enumerate(legends[index]):
            group.append(
                f'<text x="{PAD_LEFT + 24}" y="{legend_y + LEGEND_LINE * row}" font-size="11" '
                f'fill="#222">{escape(text)}</text>'
            )
        group.append("</g>")
        parts += group
    parts.append("</svg>")
    return "".join(parts)


def chart_html(chart: Chart, chart_id: str) -> str:
    """График с галочками «показать серию»: скрытие работает на CSS, без скриптов."""
    ids = [f"{chart_id}s{index}" for index in range(len(chart.series))]
    rules = " ".join(
        f"#{toggle}:not(:checked) ~ svg .s-{toggle} {{ display: none; }}" for toggle in ids
    )
    toggles = "".join(
        f'<input type="checkbox" id="{toggle}" checked>'
        f'<label for="{toggle}" style="color: {series.color}">{escape(series.label)}</label> '
        for toggle, series in zip(ids, chart.series, strict=True)
    )
    return (
        f'<div class="chart-box"><div class="chart-title"><b>{escape(chart.title)}</b>, '
        f"{escape(chart.unit)} — {escape(chart.period)}</div>"
        f"<style>{rules}</style>{toggles}{render_svg(chart, chart_id)}</div>"
    )
