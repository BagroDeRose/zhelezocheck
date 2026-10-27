"""Блок «Ноутбук» для страницы вердикта и отчёта (задача 15.12).

Собирает в одном месте то, что важно именно для ноутбука: состояние батареи (износ,
циклы, ёмкость), сколько ноутбук проработает от полной зарядки, и итоги ручных проверок
экрана и клавиатуры. Возвращает пары «название строки → текст», которые одинаково
показываются в окне программы и в HTML-отчёте.
"""

from __future__ import annotations

from hwcheck.models import CheckSession

NOT_CHECKED_SCREEN = "не проверялся"
NOT_CHECKED_KEYBOARD = "не проверялась"


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} ч {rest} мин" if hours else f"{rest} мин"


def laptop_details(session: CheckSession) -> list[tuple[str, str]]:
    """Строки блока «Ноутбук». Пустой список — это не ноутбук."""
    snap = session.snapshot
    is_laptop = snap.system is not None and snap.system.is_laptop
    if not is_laptop and snap.battery is None:
        return []
    rows: list[tuple[str, str]] = []
    battery = snap.battery
    if battery is None:
        rows.append(("Батарея", "не найдена или Windows не отдала сведения о ней"))
    else:
        parts = []
        if battery.wear_percent is not None:
            parts.append(f"износ {battery.wear_percent:.0f}%")
        if battery.cycle_count is not None:
            parts.append(f"циклов зарядки: {battery.cycle_count}")
        if battery.design_capacity_mwh:
            parts.append(
                f"ёмкость {_thousands(battery.full_charge_capacity_mwh)} из "
                f"{_thousands(battery.design_capacity_mwh)} мВт·ч"
            )
        rows.append(("Батарея", ", ".join(parts) or "сведения неполные"))
        if battery.runtime_minutes:
            runtime = f"около {_duration(battery.runtime_minutes)} от полной зарядки"
            if battery.design_runtime_minutes:
                runtime += f" (у новой батареи — {_duration(battery.design_runtime_minutes)})"
            rows.append(("Время работы", runtime))
    findings = session.verdict.findings if session.verdict else []
    screen = next((f for f in findings if f.id.startswith("laptop.screen")), None)
    keyboard = next((f for f in findings if f.id.startswith("laptop.keyboard")), None)
    rows.append(("Экран", screen.title if screen else NOT_CHECKED_SCREEN))
    rows.append(("Клавиатура", keyboard.title if keyboard else NOT_CHECKED_KEYBOARD))
    return rows
