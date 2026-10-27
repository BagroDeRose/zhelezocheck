"""Отчёт о проверке: HTML (шаблон Jinja2) и PDF.

HTML-отчёт полностью самодостаточный: стили и графики (SVG) встроены прямо в файл,
внешних ссылок на картинки, шрифты и скрипты нет — отчёт открывается без интернета
и одинаково выглядит на любом компьютере.

У каждого отчёта есть номер (UUID проверки) и SHA-256 содержимого проверки: по нему
можно убедиться, что данные проверки не меняли после её окончания.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hwcheck import __version__
from hwcheck.knowledge.gpu_db import identify
from hwcheck.laptop.details import laptop_details
from hwcheck.models import CheckSession, SensorSample, Severity, TestResult, vram_text
from hwcheck.thresholds import Thresholds, load_thresholds
from hwcheck.ui import strings

TEMPLATES = Path(__file__).resolve().parent / "templates"

MODE_TITLES = {"quick": "Быстрая проверка", "full": "Полная проверка", "short": "Короткий прогон"}
DECISION_COLORS = {"buy": "#1b7f3b", "negotiate": "#b26a00", "walk_away": "#b3261e"}
SEVERITY_COLORS = {"critical": "#b3261e", "warning": "#b26a00", "info": "#3b5bab", "ok": "#1b7f3b"}


def session_digest(session: CheckSession) -> str:
    """SHA-256 содержимого проверки (JSON с упорядоченными ключами)."""
    canonical = json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Графики
# ---------------------------------------------------------------------------


def svg_line_chart(
    points: list[tuple[float, float]],
    title: str,
    unit: str,
    limit: float | None = None,
    width: int = 640,
    height: int = 180,
    color: str = "#b3261e",
) -> str:
    """Простой линейный график в виде SVG-строки (без внешних библиотек)."""
    if len(points) < 2:
        return ""
    pad_left, pad_right, pad_top, pad_bottom = 48, 12, 24, 28
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_values = ys + ([limit] if limit is not None else [])
    y_min = min(y_values)
    y_max = max(y_values)
    spread = (y_max - y_min) or 1.0
    y_min -= spread * 0.1
    y_max += spread * 0.1
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    def sx(x: float) -> float:
        return pad_left + (x - x_min) / ((x_max - x_min) or 1.0) * plot_w

    def sy(y: float) -> float:
        return pad_top + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in points)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{title}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{pad_left}" y="16" font-size="13" fill="#222">{title}</text>',
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" '
        f'y2="{pad_top + plot_h}" stroke="#999"/>',
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" '
        f'y2="{pad_top + plot_h}" stroke="#999"/>',
    ]
    for value in (min(ys), max(ys)):
        parts.append(
            f'<text x="{pad_left - 6}" y="{sy(value) + 4:.1f}" font-size="11" fill="#444" '
            f'text-anchor="end">{value:.0f}</text>'
        )
    parts.append(
        f'<text x="{pad_left + plot_w}" y="{height - 8}" font-size="11" fill="#444" '
        f'text-anchor="end">{x_max - x_min:.0f} с</text>'
    )
    parts.append(f'<text x="{pad_left}" y="{height - 8}" font-size="11" fill="#444">{unit}</text>')
    if limit is not None:
        parts.append(
            f'<line x1="{pad_left}" y1="{sy(limit):.1f}" x2="{pad_left + plot_w}" '
            f'y2="{sy(limit):.1f}" stroke="#b3261e" stroke-dasharray="4 3"/>'
        )
    parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{path}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _series(
    samples: list[SensorSample], component_prefix: str, key: str
) -> list[tuple[float, float]]:
    return [
        (s.t, float(v))
        for s in samples
        if s.component.startswith(component_prefix) and (v := s.values.get(key)) is not None
    ]


def build_charts(session: CheckSession, thresholds: Thresholds | None = None) -> list[str]:
    """Графики температуры видеокарты и частоты процессора под нагрузкой."""
    th = thresholds or load_thresholds()
    charts: list[str] = []
    results = {r.name: r for r in session.results}
    gpu = results.get("gpu_load")
    if gpu is not None:
        chart = svg_line_chart(
            _series(gpu.samples, "gpu", "temp_c"),
            "Температура видеокарты под нагрузкой",
            "°C",
            limit=th.get("gpu.warning_c"),
        )
        if chart:
            charts.append(chart)
    cpu = results.get("cpu_load")
    if cpu is not None:
        chart = svg_line_chart(
            _series(cpu.samples, "cpu", "clock_mhz"),
            "Частота процессора под нагрузкой",
            "МГц",
            color="#3b5bab",
        )
        if chart:
            charts.append(chart)
    return charts


# ---------------------------------------------------------------------------
# Данные для шаблона
# ---------------------------------------------------------------------------


def metrics_summary(result: TestResult) -> str:
    """Главные цифры теста одной строкой."""
    m = result.metrics
    parts: list[str] = []
    if result.name == "vram":
        if m.get("errors") is not None:
            parts.append(f"ошибок: {m['errors']}")
        if m.get("speed_gbps"):
            parts.append(f"скорость {m['speed_gbps']:.0f} ГБ/с")
    elif result.name == "gpu_load":
        if m.get("max_temp_c") is not None:
            parts.append(f"макс. {m['max_temp_c']:.0f} °C")
        if m.get("max_fan_pct") is not None:
            parts.append(f"вентилятор до {m['max_fan_pct']:.0f}%")
        if m.get("clock_drop_pct") is not None:
            parts.append(f"падение частоты {m['clock_drop_pct']:.0f}%")
    elif result.name == "cpu_load":
        if m.get("checksum_ok") is not None:
            parts.append("вычисления верны" if m["checksum_ok"] else "ОШИБКИ вычислений")
        if m.get("clock_drop_pct") is not None:
            parts.append(f"падение частоты {m['clock_drop_pct']:.0f}%")
    elif result.name == "ram_quick":
        if m.get("tested_mb"):
            parts.append(f"проверено {m['tested_mb'] / 1024:.1f} ГБ")
        if m.get("errors") is not None:
            parts.append(f"ошибок: {m['errors']}")
    elif result.name == "disk_read":
        if m.get("read_mb") is not None:
            parts.append(f"прочитано {m['read_mb']} МБ")
        if m.get("speed_mbps"):
            parts.append(f"{m['speed_mbps']:.0f} МБ/с")
        if m.get("read_errors"):
            parts.append(f"ошибок чтения: {m['read_errors']}")
    return ", ".join(parts)


def _gpu_rows(session: CheckSession) -> list[dict[str, Any]]:
    rows = []
    for gpu in session.snapshot.gpus:
        ident = identify(gpu)
        rows.append(
            {
                "name": gpu.name,
                "chip": ident.real_chip or "—",
                "vram": vram_text(gpu) or "—",
                "vbios": gpu.vbios_version or "—",
                "driver": gpu.driver_version or "—",
                "power": f"{gpu.default_power_limit_w:.0f} Вт"
                if gpu.default_power_limit_w
                else "—",
                "ids": f"{gpu.pci_vendor_id}:{gpu.pci_device_id}",
            }
        )
    return rows


def _disk_rows(session: CheckSession) -> list[dict[str, Any]]:
    rows = []
    for disk in session.snapshot.disks:
        smart = disk.smart
        rows.append(
            {
                "model": disk.model,
                "size": f"{disk.size_gb:.0f} ГБ" if disk.size_gb else "—",
                "type": {"ssd": "SSD", "hdd": "HDD"}.get(disk.media_type, "—"),
                "hours": smart.power_on_hours
                if smart and smart.power_on_hours is not None
                else "—",
                "wear": f"{smart.wear_percent:.0f}%"
                if smart and smart.wear_percent is not None
                else "—",
                "sectors": (
                    (smart.reallocated_sectors or 0) + (smart.pending_sectors or 0)
                    if smart
                    and (smart.reallocated_sectors is not None or smart.pending_sectors is not None)
                    else "—"
                ),
                "health": "—"
                if not smart or smart.health_passed is None
                else ("в норме" if smart.health_passed else "НЕИСПРАВЕН"),
            }
        )
    return rows


def build_context(session: CheckSession, generated_at: datetime | None = None) -> dict[str, Any]:
    """Всё, что нужно шаблону отчёта."""
    verdict = session.verdict
    decision = verdict.decision.value if verdict else "negotiate"
    findings = verdict.findings if verdict else []
    snap = session.snapshot
    return {
        "app_name": strings.APP_NAME,
        "version": session.app_version or __version__,
        "report_id": session.id,
        "digest": session_digest(session),
        "generated_at": (generated_at or datetime.now()).strftime("%d.%m.%Y %H:%M"),
        "started_at": session.started_at.replace("T", " "),
        "mode": MODE_TITLES.get(session.mode, session.mode),
        "demo": session.demo_scenario,
        "decision": decision,
        "decision_title": strings.DECISION_TITLES[decision],
        "decision_color": DECISION_COLORS[decision],
        "summary": verdict.summary if verdict else "",
        "problems": [f for f in findings if f.severity is not Severity.OK],
        "good": [f for f in findings if f.severity is Severity.OK],
        "severity_names": strings.SEVERITY_NAMES,
        "severity_colors": SEVERITY_COLORS,
        "bargaining": verdict.bargaining_points if verdict else [],
        "not_checked": verdict.not_checked if verdict else [],
        "system": snap.system,
        "cpu": snap.cpu,
        "memory": snap.memory,
        "board": snap.board,
        "gpus": _gpu_rows(session),
        "disks": _disk_rows(session),
        "battery": snap.battery,
        "laptop": laptop_details(session),
        "tests": [
            {
                "name": strings.TEST_NAMES.get(r.name, r.name),
                "status": strings.STATUS_NAMES.get(r.status.value, r.status.value),
                "status_key": r.status.value,
                "duration": f"{r.duration_s:.0f} с",
                "summary": metrics_summary(r),
                "notes": r.notes,
            }
            for r in session.results
        ],
        "charts": build_charts(session),
        "listing": _listing_context(session),
    }


def rub(value: int | None) -> str:
    """23500 → «23 500 ₽»."""
    return f"{value:,} ₽".replace(",", " ") if value else "—"


def _listing_context(session: CheckSession) -> dict[str, Any] | None:
    """Объявление, с которым сверялась проверка (если было)."""
    claims = session.listing
    if claims is None:
        return None
    claimed = ", ".join(
        part
        for part in (
            claims.gpu_model + (f" {claims.gpu_vram_gb:g} ГБ" if claims.gpu_vram_gb else ""),
            claims.cpu_model,
            f"ОЗУ {claims.ram_gb:g} ГБ" if claims.ram_gb else "",
        )
        if part.strip()
    )
    return {
        "title": claims.title or "—",
        "url": claims.url,
        "price": rub(claims.price_rub),
        "market": rub(claims.market_median_rub),
        "market_count": claims.market_count,
        "city": claims.city,
        "claimed": claimed or "—",
    }


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_html(session: CheckSession, generated_at: datetime | None = None) -> str:
    """HTML-отчёт по проверке."""
    template = _environment().get_template("report.html.j2")
    return template.render(**build_context(session, generated_at))


CHART_SIZE = (640, 180)  # размер графиков svg_line_chart по умолчанию


def build_print_html(
    session: CheckSession, generated_at: datetime | None = None
) -> tuple[str, list[str]]:
    """PDF-версия отчёта для QTextDocument (25.4): HTML и SVG графиков.

    Графики в HTML — ссылки `chart_N.png`; сами картинки рисует `report/pdf.py` из SVG.
    """
    context = build_context(session, generated_at)
    charts: list[str] = list(context.get("charts", []))
    context["chart_images"] = [f"chart_{index}.png" for index in range(len(charts))]
    context["chart_width"], context["chart_height"] = CHART_SIZE
    html = _environment().get_template("report_print.html.j2").render(**context)
    return html, charts


def report_file_name(session: CheckSession) -> str:
    stamp = (session.started_at or datetime.now().isoformat()).replace(":", "-").replace("T", "_")
    return f"report_{stamp[:16]}_{session.id[:8]}"


def save_html(session: CheckSession, folder: Path) -> Path:
    """Сохраняет HTML-отчёт в папку отчётов и возвращает путь к файлу."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report_file_name(session)}.html"
    path.write_text(build_html(session), encoding="utf-8")
    return path
