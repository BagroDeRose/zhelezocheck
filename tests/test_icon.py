"""Иконка программы (SPEC 1.5, задача 36.1): многоразмерный .ico из фирменного аватара."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtGui import QIcon, QImage
from pytestqt.qtbot import QtBot

from scripts import make_icon

ICON = Path(__file__).resolve().parent.parent / "hwcheck" / "data" / "icon.ico"


def _entries(data: bytes) -> list[int]:
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1
    return [data[6 + 16 * i] or 256 for i in range(count)]


def test_icon_has_all_sizes() -> None:
    assert sorted(_entries(ICON.read_bytes())) == [16, 24, 32, 48, 64, 128, 256]


def test_qt_loads_every_size(qtbot: QtBot) -> None:
    icon = QIcon(str(ICON))
    sizes = sorted(size.width() for size in icon.availableSizes())
    assert sizes == [16, 24, 32, 48, 64, 128, 256]


def test_small_sizes_are_simplified_and_large_come_from_avatar(qtbot: QtBot) -> None:
    small = make_icon.frame(16)
    large = make_icon.frame(256)
    assert isinstance(small, QImage) and isinstance(large, QImage)
    # Маленькая иконка — упрощённая: фон фирменного тёмно-синего цвета, без свечения.
    edge = small.pixelColor(2, 13)  # фон у левого нижнего угла — ни кольца, ни ручки
    assert edge.name().lower() == make_icon.NAVY.lower()
    assert (large.width(), large.height()) == (256, 256)


def test_committed_icon_matches_generator(qtbot: QtBot) -> None:
    images = {size: make_icon._png_bytes(make_icon.frame(size)) for size in make_icon.SIZES}
    assert _entries(make_icon.ico_bytes(images)) == _entries(ICON.read_bytes())
