r"""Иконка программы из `docs/brand/avatar.png` (SPEC 1.5, задача 36.1; 31.1).

- 48, 64, 128, 256 px — сам аватар, обрезанный по содержимому и уменьшенный со сглаживанием;
- 16, 24, 32 px — упрощённый вариант по мотиву аватара, нарисованный программно: тёмный фон
  фирменного цвета, бирюзовая лупа и зелёная галочка, без свечения и мелких деталей (уменьшенный
  аватар на таком размере превращается в пятно — см. `docs/qa/icon_compare.png`).

Результат — многоразмерный `hwcheck/data/icon.ico` (PNG-кадры, Windows 10/11) и превью
`docs/images/icon_sizes.png`. Запуск: `.venv\Scripts\python scripts\make_icon.py`.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AVATAR = ROOT / "docs" / "brand" / "avatar.png"
ICON = ROOT / "hwcheck" / "data" / "icon.ico"
PREVIEW = ROOT / "docs" / "images" / "icon_sizes.png"
COMPARE = ROOT / "docs" / "qa" / "icon_compare.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)
SMALL = (16, 24, 32)
# Область аватара с рисунком (без пустого фона по краям), квадрат.
CROP = (70, 70, 1114, 1114)
NAVY, CYAN, GREEN = "#0F1B2D", "#22D3EE", "#22C55E"


def _app() -> object:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.instance() or QGuiApplication(sys.argv[:1])


def large(size: int) -> object:
    """Аватар, обрезанный и уменьшенный (для 48 px и больше)."""
    _app()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    source = QImage(str(AVATAR)).copy(*CROP)
    return source.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    ).convertToFormat(QImage.Format.Format_ARGB32)


def small(size: int) -> object:
    """Упрощённая иконка: фон, лупа, галочка — читается на 16–32 px."""
    _app()
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(NAVY))
    painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.2, s * 0.2)
    # Лупа: кольцо и ручка.
    ring = QPen(QColor(CYAN), max(1.6, s * 0.11))
    ring.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(ring)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    center, radius = QPointF(s * 0.43, s * 0.43), s * 0.29
    painter.drawEllipse(center, radius, radius)
    handle = QPen(QColor(CYAN), max(2.0, s * 0.15))
    handle.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(handle)
    painter.drawLine(QPointF(s * 0.65, s * 0.65), QPointF(s * 0.86, s * 0.86))
    # Галочка внутри кольца.
    check = QPen(QColor(GREEN), max(1.6, s * 0.1))
    check.setCapStyle(Qt.PenCapStyle.RoundCap)
    check.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(check)
    path = QPainterPath(QPointF(s * 0.30, s * 0.44))
    path.lineTo(QPointF(s * 0.40, s * 0.54))
    path.lineTo(QPointF(s * 0.57, s * 0.33))
    painter.drawPath(path)
    painter.end()
    return image


def frame(size: int) -> object:
    return small(size) if size in SMALL else large(size)


def _png_bytes(image: object) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")  # type: ignore[attr-defined]  # QImage
    buffer.close()
    return bytes(data.data())


def ico_bytes(images: dict[int, bytes]) -> bytes:
    """ICO с PNG-кадрами: заголовок, каталог, данные (формат Windows Vista и новее)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, payload = b"", b""
    for size, png in sorted(images.items()):
        side = 0 if size >= 256 else size  # 0 означает 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    return header + entries + payload


def build() -> Path:
    _app()
    images = {size: _png_bytes(frame(size)) for size in SIZES}
    ICON.write_bytes(ico_bytes(images))
    _preview()
    return ICON


def _preview() -> None:
    """Превью: все размеры в натуральную величину и увеличенные 16–32 px; сравнение для QA."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    sheet = QImage(760, 300, QImage.Format.Format_ARGB32)
    sheet.fill(QColor("#f6f6f8"))
    painter = QPainter(sheet)
    x = 12
    for size in SIZES:
        painter.drawImage(x, 12, frame(size))  # type: ignore[arg-type]  # QImage
        x += size + 14
    x = 12
    for size in SMALL:  # маленькие — увеличены в 4 раза «пикселями», как видит глаз на 150 %
        painter.drawImage(QRectF(x, 160, size * 4, size * 4), frame(size))  # type: ignore[arg-type]
        x += size * 4 + 20
    painter.end()
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(PREVIEW))

    compare = QImage(420, 150, QImage.Format.Format_ARGB32)
    compare.fill(QColor("#f6f6f8"))
    painter = QPainter(compare)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    x = 12
    for size in SMALL:
        painter.drawImage(QRectF(x, 10, size * 2, size * 2), large(size))  # type: ignore[arg-type]
        painter.drawImage(QRectF(x, 80, size * 2, size * 2), small(size))  # type: ignore[arg-type]
        x += size * 2 + 30
    painter.setPen(Qt.GlobalColor.black)
    painter.end()
    COMPARE.parent.mkdir(parents=True, exist_ok=True)
    compare.save(str(COMPARE))


if __name__ == "__main__":
    print(build())
