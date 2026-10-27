"""Мелкие общие элементы страниц: заголовок, карточка, текст с переносом."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("title")
    label.setWordWrap(True)
    return label


def text_label(text: str = "", muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if muted:
        label.setObjectName("muted")
    return label


def card(*widgets: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def escape(text: str) -> str:
    """Экранирует текст для вставки в RichText-метку."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
