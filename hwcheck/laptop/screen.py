"""Тест экрана: по очереди показываются однотонные цвета и градиент, на них хорошо видны
битые пиксели, засветы и полосы. В конце пользователь отвечает, видел ли дефекты."""

from __future__ import annotations

from dataclasses import dataclass

from hwcheck.laptop.texts import ManualResult, laptop_finding


@dataclass(frozen=True)
class ScreenColor:
    key: str
    title: str
    color: str | None  # None — градиент


COLORS = [
    ScreenColor("black", "Чёрный", "#000000"),
    ScreenColor("white", "Белый", "#ffffff"),
    ScreenColor("red", "Красный", "#ff0000"),
    ScreenColor("green", "Зелёный", "#00ff00"),
    ScreenColor("blue", "Синий", "#0000ff"),
    ScreenColor("gradient", "Градиент", None),
]


class ScreenTest:
    """Перебор цветов по клику или клавише."""

    def __init__(self) -> None:
        self.index = 0

    @property
    def finished(self) -> bool:
        return self.index >= len(COLORS)

    @property
    def current(self) -> ScreenColor:
        return COLORS[min(self.index, len(COLORS) - 1)]

    def advance(self) -> None:
        if not self.finished:
            self.index += 1


def screen_finding(defects: bool) -> ManualResult:
    """Находка по ответу на вопрос «Видели битые пиксели или полосы?»."""
    return laptop_finding("screen_defects" if defects else "screen_ok")
