"""Фирменные цвета и темы программы (SPEC 1.4, задача 31.3): цифры в docs/brand/README.md верны."""

from __future__ import annotations

from pathlib import Path

from hwcheck.ui.theme import COLORS, SEVERITY_COLORS

BRAND = ("#0F1B2D", "#22D3EE", "#22C55E", "#F97316")
README = Path(__file__).resolve().parent.parent / "docs" / "brand" / "README.md"


def _luminance(color: str) -> float:
    rgb = [int(color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _distance(a: str, b: str) -> float:
    pa = [int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    pb = [int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    return sum((x - y) ** 2 for x, y in zip(pa, pb, strict=True)) ** 0.5


def test_readme_lists_brand_colors_with_true_contrast() -> None:
    text = README.read_text(encoding="utf-8")
    light, dark = COLORS["light"]["bg"], COLORS["dark"]["bg"]
    for color in BRAND:
        row = next(line for line in text.splitlines() if line.startswith(f"| `{color}`"))
        assert f"| {round(contrast(color, light), 2):g} |" in row, row
        assert f"| {round(contrast(color, dark), 2):g} |" in row, row


def test_orange_is_the_one_close_to_warnings() -> None:
    """Правило из README: оранжевый близок к предупреждениям, остальные — нет."""
    warning = SEVERITY_COLORS["warning"]
    near = {color: _distance(color, warning) < 60 for color in BRAND}
    assert near == {"#0F1B2D": False, "#22D3EE": False, "#22C55E": False, "#F97316": True}
