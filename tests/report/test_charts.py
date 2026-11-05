"""Графики из реальных временных рядов (этап 44 v2.1): оси, единицы, легенда, мин/сред/макс,
время начала и конца, отметки прерываний, скрытие серий; нет датчика — нет графика."""

import re
from pathlib import Path

from hwcheck import schema
from hwcheck.models import CheckSession, SensorSample, SeriesMarker, TestResult
from hwcheck.report import builder
from hwcheck.report.charts import build_series_charts, legend_lines, render_svg
from tests.report.helpers import demo_session

OLD_SESSION = Path(__file__).parent.parent / "fixtures" / "sessions" / "session_2_0_1.json"


def titles(session: CheckSession) -> list[str]:
    return [chart.title for chart in build_series_charts(session)]


def test_cpu_and_gpu_charts_from_series() -> None:
    session = demo_session("healthy_gaming_pc")
    names = titles(session)
    assert any("Нагрузка процессора" in t and "частота" in t for t in names), names
    assert any("Нагрузка видеокарты" in t and "температура" in t for t in names), names
    assert any("Нагрузка видеокарты" in t and "загрузка" in t for t in names), names


def test_stats_in_legend_match_series() -> None:
    session = demo_session("healthy_gaming_pc")
    gpu = next(r for r in session.results if r.name == "gpu_load")
    chart = next(
        c
        for c in build_series_charts(session)
        if "температура" in c.title and "видеокарты" in c.title
    )
    stats = schema.series_stats(gpu, "gpu0.temperature")
    assert stats is not None
    series = chart.series[0]
    assert series.stats == stats
    svg = render_svg(chart, "c0")
    assert f"макс {stats.maximum:.0f}" in svg and "°C" in svg
    assert "<text" in svg and "с</text>" in svg  # подпись оси времени в секундах


def test_missing_sensor_has_no_series_and_no_chart() -> None:
    session = demo_session("healthy_gaming_pc")
    for result in session.results:
        for sample in result.samples:
            if sample.component.startswith("gpu"):
                sample.values["fan_pct"] = None
                sample.values["power_w"] = None
    charts = build_series_charts(session)
    labels = [s.label for c in charts for s in c.series]
    assert not any("Вентилятор" in label for label in labels)
    assert not any("Потребление" in c.title for c in charts)


def test_no_samples_no_charts() -> None:
    session = demo_session("healthy_gaming_pc")
    for result in session.results:
        result.samples = []
    assert build_series_charts(session) == []


def test_gap_in_sensor_breaks_the_line() -> None:
    """Датчик пропал на время — линия рвётся, а не соединяет точки через пропуск."""
    result = TestResult(name="gpu_load")
    times = [0, 1, 2, 3, 10, 11, 12]
    result.samples = [
        SensorSample(t=float(t), component="gpu0", values={"temp_c": 50.0 + t}) for t in times
    ]
    session = demo_session("healthy_gaming_pc")
    session.results = [result]
    (chart,) = [c for c in build_series_charts(session) if "температура" in c.title]
    assert len(chart.series[0].segments) == 2
    assert render_svg(chart, "c0").count("<polyline") == 2


def test_markers_and_times_are_shown() -> None:
    session = demo_session("mining_gpu")
    gpu = next(r for r in session.results if r.name == "gpu_load")
    gpu.started_at = "2026-10-05T12:00:00"
    end = gpu.samples[-1].t
    gpu.markers = [
        SeriesMarker(0.0, "start", "Начало нагрузки"),
        SeriesMarker(end, "interrupt", "Тест остановлен пользователем"),
    ]
    chart = next(c for c in build_series_charts(session) if "видеокарты" in c.title)
    svg = render_svg(chart, "c0")
    assert "остановлен" in svg and "stroke-dasharray" in svg
    assert "12:00:00" in chart.period


def test_series_can_be_hidden_without_scripts() -> None:
    html = builder.build_specialist_html(demo_session("healthy_gaming_pc"))
    assert "<script" not in html
    toggles = re.findall(r'<input type="checkbox" id="(c\d+s\d+)"', html)
    assert toggles
    for toggle in toggles[:3]:
        assert f'class="s-{toggle}"' in html  # серия на графике
        assert f"#{toggle}:not(:checked)" in html  # правило CSS, которое её прячет


def test_old_session_charts_without_start_time() -> None:
    session = schema.load_session(OLD_SESSION.read_text(encoding="utf-8"))
    charts = build_series_charts(session)
    assert charts
    assert all("время начала неизвестно" in c.period for c in charts)


def test_no_zero_points_drawn_for_missing_values() -> None:
    result = TestResult(name="cpu_load")
    result.samples = [
        SensorSample(t=0.0, component="cpu", values={"clock_mhz": 3800.0, "zone_temp_c": None}),
        SensorSample(t=2.0, component="cpu", values={"clock_mhz": 3700.0, "zone_temp_c": None}),
    ]
    session = demo_session("healthy_gaming_pc")
    session.results = [result]
    charts = build_series_charts(session)
    assert not any("тепловой зоны" in c.title for c in charts)
    assert any("частота" in c.title for c in charts)


# ---------------------------------------------------------------- ручная проверка 2.1.0-rc1


def _cpu_session(values: list[float], key: str = "zone_temp_c") -> CheckSession:
    session = demo_session("healthy_gaming_pc")
    result = TestResult(name="cpu_load", started_at="2026-11-05T17:37:06")
    result.samples = [
        SensorSample(t=float(t), component="cpu", values={key: value})
        for t, value in enumerate(values)
    ]
    session.results = [result]
    return session


def _axis_labels(svg: str) -> list[str]:
    return re.findall(r'text-anchor="end">([^<]+)</text>', svg.split("<polyline")[0])


def test_flat_series_axis_has_distinct_labels_and_note() -> None:
    """Зона ACPI весь тест 27,9 °C: подписи оси были «28 28 28 28 28»."""
    (chart,) = build_series_charts(_cpu_session([27.9] * 20))
    svg = render_svg(chart, "c")
    labels = [label for label in _axis_labels(svg) if label[0].isdigit() or label[0] == "-"]
    assert len(labels) == len(set(labels)) >= 3, labels
    assert "значение не менялось" in svg


def test_percent_axis_does_not_go_below_zero() -> None:
    """Загрузка GPU 2–100 %: ось начиналась с −7.8 %."""
    (chart,) = build_series_charts(_cpu_session([2.0, 50.0, 100.0, 99.0], "util_pct"))
    labels = _axis_labels(render_svg(chart, "c"))
    numbers = [float(label.replace(",", ".")) for label in labels if label[0].isdigit()]
    assert min(numbers) >= 0 and not any(label.startswith("-") for label in labels)


def test_axis_ticks_are_round_numbers() -> None:
    """Частоты 1875–4001 МГц: подписи были 1662, 2300, 2938…"""
    (chart,) = build_series_charts(_cpu_session([1875.0, 4001.0, 3000.0], "clock_mhz"))
    numbers = [
        float(label.replace(",", "."))
        for label in _axis_labels(render_svg(chart, "c"))
        if label[0].isdigit()
    ]
    steps = {round(b - a, 6) for a, b in zip(numbers, numbers[1:], strict=False)}
    assert len(steps) == 1
    (step,) = steps
    mantissa = abs(step) / 10 ** int(f"{abs(step):e}".split("e")[1])
    assert round(mantissa, 6) in (1.0, 2.0, 2.5, 5.0), numbers


def test_legend_source_is_short() -> None:
    (chart,) = build_series_charts(_cpu_session([30.0, 31.0, 32.0]))
    svg = render_svg(chart, "c")
    assert "ThermalZoneInformation" not in svg and "ACPI-тепловая зона" in svg


def test_steady_load_is_not_marked_as_stuck() -> None:
    """Ровные 99 % загрузки — норма под нагрузкой, пометка «не менялось» только у температур."""
    (chart,) = build_series_charts(_cpu_session([99.0] * 20, "util_pct"))
    assert "не менялось" not in render_svg(chart, "c")


def test_long_legend_wraps_instead_of_being_cut() -> None:
    """Ручная проверка rc2: подпись тепловой зоны с пометкой обрезалась на краю PDF."""
    (chart,) = build_series_charts(_cpu_session([27.9] * 20))
    (lines,) = [legend_lines(series) for series in chart.series]
    assert len(lines) == 2 and all(len(line) <= 110 for line in lines)
    svg = render_svg(chart, "c")
    assert "значение не менялось" in svg
    heights = re.search(r'height="(\d+)"', svg)
    assert heights is not None and int(heights.group(1)) > 280  # место под вторую строку
