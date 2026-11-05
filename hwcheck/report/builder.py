"""Отчёт о проверке: HTML (шаблон Jinja2) и PDF.

HTML-отчёт полностью самодостаточный: стили и графики (SVG) встроены прямо в файл,
внешних ссылок на картинки, шрифты и скрипты нет — отчёт открывается без интернета
и одинаково выглядит на любом компьютере.

У каждого отчёта есть номер (UUID проверки) и SHA-256 содержимого проверки: по нему
можно убедиться, что данные проверки не меняли после её окончания.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from hwcheck import __version__
from hwcheck.knowledge.events_db import describe, group_title
from hwcheck.laptop.details import laptop_details
from hwcheck.models import (
    CheckSession,
)
from hwcheck.report.buyer import buyer_context
from hwcheck.report.charts import build_series_charts, chart_html, render_svg
from hwcheck.report.privacy import mask_identifiers
from hwcheck.report.specialist import specialist_context
from hwcheck.ui import strings
from hwcheck.ui.summary_cards import (
    EVENT_PARAMS,
    moment,
)

TEMPLATES = Path(__file__).resolve().parent / "templates"

MODE_TITLES = strings.MODE_TITLES
DECISION_COLORS = {"buy": "#1b7f3b", "negotiate": "#b26a00", "walk_away": "#b3261e"}
SEVERITY_COLORS = {"critical": "#b3261e", "warning": "#b26a00", "info": "#3b5bab", "ok": "#1b7f3b"}


def session_digest(session: CheckSession) -> str:
    """SHA-256 содержимого проверки (JSON с упорядоченными ключами)."""
    canonical = json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Графики
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Данные для шаблона
# ---------------------------------------------------------------------------


def _date_text(text: str | None, with_time: bool = False) -> str:
    """Дата из снимка → «14.03.2024» (или «05.10.2026 09:01»). Не разобрали → пусто."""
    value = moment(text)
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


EVENT_LEVELS = {1: "критическое", 2: "ошибка", 3: "предупреждение", 4: "сведения"}
# Группы, которые собираются с 2.1: в старых проверках их нет — строк не показываем.
NEW_EVENT_GROUPS = ("storage", "gpu_driver", "unexpected_shutdown")
UNREAD = "не прочитано"


def _event_when(last_seen: str, started_at: str) -> str:
    """Было ли событие во время проверки или только раньше (в истории Windows)."""
    if last_seen and started_at and last_seen >= started_at:
        return "в том числе во время проверки"
    return "в истории Windows (до проверки)"


def _event_context(session: CheckSession) -> dict[str, Any] | None:
    """Журнал Windows: сводка по группам и (с 2.1) каждый вид события с расшифровкой.

    Группа, которую не удалось прочитать, — «не прочитано», а не ноль.
    """
    events = session.snapshot.events
    if events is None:
        return None
    names = [*EVENT_PARAMS, ("disk_removable", "Ошибки съёмных дисков")]
    names += [(key, group_title(key)) for key in NEW_EVENT_GROUPS]
    optional = {"disk_removable", *NEW_EVENT_GROUPS}
    rows = [
        {
            "name": name,
            "count": events.counts.get(key, UNREAD),
            "last": _date_text(events.last_for(key), with_time=True) or "—",
        }
        for key, name in names
        if key in events.counts or key not in optional
    ]
    items = []
    for item in events.items:
        info = describe(item.provider, item.event_id, item.group)
        items.append(
            {
                "group": group_title(item.group),
                "log": item.log,
                "provider": item.provider,
                "event_id": item.event_id,
                "level": EVENT_LEVELS.get(item.level or 0, "—"),
                "count": item.count,
                "first": _date_text(item.first_seen, with_time=True) or "—",
                "last": _date_text(item.last_seen, with_time=True) or "—",
                "title": info.title,
                "component": info.component or "—",
                "significance": info.significance,
                "note": info.note,
                "message": item.message,
                "when": _event_when(item.last_seen, session.started_at),
            }
        )
    return {
        "days": events.days,
        "partial": events.partial,
        "note": events.note,
        "rows": rows,
        "items": items,
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


REPORT_MODES = ("buyer", "specialist")


def report_context(
    session: CheckSession, generated_at: datetime | None = None, mode: str = "buyer"
) -> dict[str, Any]:
    """Контекст общего отчёта: вид покупателя и вид специалиста из одного снимка."""
    if mode not in REPORT_MODES:
        raise ValueError(f"Неизвестный режим отчёта: {mode}")
    verdict = session.verdict
    decision = verdict.decision.value if verdict else "negotiate"
    context = specialist_context(session)
    context.update(
        app_name=strings.APP_NAME,
        version=session.app_version or __version__,
        report_id=session.id,
        digest=session_digest(session),
        generated_at=(generated_at or datetime.now()).strftime("%d.%m.%Y %H:%M"),
        started_at=session.started_at.replace("T", " "),
        demo=session.demo_scenario,
        mode=mode,
        mode_buyer_title=strings.REPORT_MODE_BUYER,
        mode_specialist_title=strings.REPORT_MODE_SPECIALIST,
        buyer=buyer_context(session),
        decision_color=DECISION_COLORS[decision],
        laptop=laptop_details(session),
        events=_event_context(session),
        listing=_listing_context(session),
        charts=[
            chart_html(chart, f"c{index}")
            for index, chart in enumerate(build_series_charts(session))
        ],
        json_href=json_data_uri(session),
        json_name=f"{report_file_name(session)}.json",
    )
    return context


def json_data_uri(session: CheckSession) -> str:
    """Полный снимок проверки как ссылка data: — отчёт остаётся одним самодостаточным файлом."""
    data = base64.b64encode(session.to_json(indent=None).encode("utf-8")).decode("ascii")
    return f"data:application/json;base64,{data}"


def build_html(
    session: CheckSession, generated_at: datetime | None = None, mode: str = "buyer"
) -> str:
    """HTML-отчёт: оба режима в одном файле, `mode` — какой открыт сразу (переключение без
    повторных тестов: оба вида строятся из одного снимка)."""
    template = _environment().get_template("report.html.j2")
    return template.render(**report_context(session, generated_at, mode))


def build_specialist_html(session: CheckSession, generated_at: datetime | None = None) -> str:
    """Тот же отчёт, открытый в режиме «Для специалиста»."""
    return build_html(session, generated_at, mode="specialist")


def build_inapp_specialist_html(session: CheckSession) -> str:
    """Вид специалиста для окна программы: те же данные, простые таблицы без графиков."""
    context = specialist_context(session)
    context["hint"] = strings.VERDICT_SPECIALIST_HINT
    return _environment().get_template("report_inapp.html.j2").render(**context)


PRINT_CHART_WIDTH = 640  # ширина графика в PDF (точки); высота — по пропорциям SVG


def build_print_html(
    session: CheckSession, generated_at: datetime | None = None
) -> tuple[str, list[str]]:
    """PDF-версия отчёта для QTextDocument: HTML и SVG графиков (для `report/pdf.py`).

    Содержимое — как в HTML: вид покупателя, затем технический протокол. Графики в разметке —
    ссылки `chart_N.png`, сами картинки рисуются из SVG.
    """
    context = report_context(session, generated_at)
    charts = build_series_charts(session)
    svgs = [render_svg(chart, f"p{index}") for index, chart in enumerate(charts)]
    images = []
    for index, (chart, svg) in enumerate(zip(charts, svgs, strict=True)):
        width, height = _svg_size(svg)
        images.append(
            {
                "src": f"chart_{index}.png",
                "title": chart.title,
                "unit": chart.unit,
                "period": chart.period,
                "width": PRINT_CHART_WIDTH,
                "height": round(height * PRINT_CHART_WIDTH / width),
            }
        )
    context["chart_images"] = images
    html = _environment().get_template("report_print.html.j2").render(**context)
    return html, svgs


def _svg_size(svg: str) -> tuple[float, float]:
    match = re.search(r'width="(\d+)" height="(\d+)"', svg)
    return (float(match.group(1)), float(match.group(2))) if match else (760.0, 260.0)


def report_file_name(session: CheckSession) -> str:
    stamp = (session.started_at or datetime.now().isoformat()).replace(":", "-").replace("T", "_")
    return f"report_{stamp[:16]}_{session.id[:8]}"


def _exported(session: CheckSession, hide_identifiers: bool) -> CheckSession:
    return mask_identifiers(session) if hide_identifiers else session


def save_html(
    session: CheckSession, folder: Path, mode: str = "buyer", hide_identifiers: bool = True
) -> Path:
    """Сохраняет HTML-отчёт в папку отчётов и возвращает путь к файлу (`mode` — какой режим
    открыт сразу; второй — переключателем в самом отчёте). Идентификаторы по умолчанию скрыты."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report_file_name(session)}.html"
    exported = _exported(session, hide_identifiers)
    path.write_text(build_html(exported, mode=mode), encoding="utf-8")
    return path


def save_json(session: CheckSession, folder: Path, hide_identifiers: bool = True) -> Path:
    """Полный технический снимок проверки в JSON (рядом с отчётом). Идентификаторы по умолчанию
    скрыты. Открывается обратно через `schema.load_session`."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report_file_name(session)}.json"
    path.write_text(_exported(session, hide_identifiers).to_json(), encoding="utf-8")
    return path
