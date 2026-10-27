"""Светлая и тёмная темы оформления (таблицы стилей Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

COLORS = {
    "light": {
        "bg": "#f6f6f8", "panel": "#ffffff", "text": "#1d1d1f", "muted": "#5f6368",
        "accent": "#2f5bd3", "border": "#d9d9de", "nav": "#ececf1", "nav_sel": "#dfe5fb",
    },
    "dark": {
        "bg": "#1e1f22", "panel": "#2b2d31", "text": "#ececf1", "muted": "#a0a4ab",
        "accent": "#7aa2ff", "border": "#3d4047", "nav": "#25272b", "nav_sel": "#33415f",
    },
}  # fmt: skip

DECISION_COLORS = {"buy": "#1b7f3b", "negotiate": "#b26a00", "walk_away": "#b3261e"}
SEVERITY_COLORS = {"critical": "#d93025", "warning": "#e08600", "info": "#4a6fd1", "ok": "#2e9d52"}


def stylesheet(theme: str) -> str:
    c = COLORS.get(theme, COLORS["light"])
    return f"""
    QWidget {{ background: {c["bg"]}; color: {c["text"]}; font-size: 14px; }}
    QLabel, QRadioButton, QCheckBox {{ background: transparent; }}
    QLabel#title {{ font-size: 22px; font-weight: 600; }}
    QLabel#muted {{ color: {c["muted"]}; }}
    QLabel#badge {{ background: #fff3cd; color: #5a4300; padding: 4px 8px; border-radius: 4px; }}
    QFrame#card {{ background: {c["panel"]}; border: 1px solid {c["border"]}; border-radius: 8px; }}
    QFrame#summaryCard {{ background: {c["bg"]}; border: 1px solid {c["border"]};
                         border-radius: 8px; }}
    QLabel#cardIcon {{ font-size: 20px; }}
    QLabel#cardTitle {{ font-weight: 600; }}
    QLabel#cardStatus {{ font-weight: 600; }}
    QLabel#proPlaque {{ background: {c["nav_sel"]}; color: {c["text"]}; border-radius: 6px;
                       padding: 8px 12px; }}
    QListWidget#nav {{ background: {c["nav"]}; border: none; padding: 6px; }}
    QListWidget#nav::item {{ padding: 10px 8px; border-radius: 6px; }}
    QListWidget#nav::item:selected {{ background: {c["nav_sel"]}; color: {c["text"]}; }}
    QListWidget#nav::item:focus, QListWidget#nav:focus {{ outline: none; }}
    QPushButton {{ background: {c["panel"]}; border: 1px solid {c["border"]}; border-radius: 6px;
                  padding: 8px 16px; }}
    QPushButton:disabled {{ color: {c["muted"]}; }}
    QPushButton#primary {{ background: {c["accent"]}; color: #ffffff;
                          border: 1px solid {c["accent"]}; font-weight: 600; }}
    QProgressBar {{ border: 1px solid {c["border"]}; border-radius: 6px; text-align: center;
                   background: {c["panel"]}; height: 22px; }}
    QProgressBar::chunk {{ background: {c["accent"]}; border-radius: 6px; }}
    QTableWidget, QTextBrowser, QListWidget {{ background: {c["panel"]};
                                              border: 1px solid {c["border"]}; }}
    QTableWidget {{ gridline-color: {c["border"]}; }}
    QTableWidget::item:selected, QListWidget::item:selected {{ background: {c["nav_sel"]};
                                                              color: {c["text"]}; }}
    QHeaderView::section {{ background: {c["nav"]}; color: {c["text"]}; padding: 4px 6px;
                           border: none; border-right: 1px solid {c["border"]};
                           border-bottom: 1px solid {c["border"]}; font-weight: 600; }}
    QTableCornerButton::section {{ background: {c["nav"]}; border: none; }}
    QComboBox {{ background: {c["panel"]}; border: 1px solid {c["border"]}; border-radius: 6px;
                padding: 4px 8px; min-width: 120px; }}
    QComboBox QAbstractItemView {{ background: {c["panel"]}; color: {c["text"]};
                                  selection-background-color: {c["nav_sel"]};
                                  selection-color: {c["text"]}; border: 1px solid {c["border"]};
                                  outline: none; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; border: none; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; border: none; }}
    QScrollBar::handle:vertical {{ background: {c["border"]}; border-radius: 3px;
                                  min-height: 32px; }}
    QScrollBar::handle:horizontal {{ background: {c["border"]}; border-radius: 3px;
                                    min-width: 32px; }}
    QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {c["muted"]}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none;
                                                 background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QAbstractScrollArea::corner {{ background: transparent; }}
    QPushButton:focus {{ outline: none; border: 1px solid {c["accent"]};
                        background: {c["nav_sel"]}; }}
    QPushButton#primary:disabled {{ background: {c["border"]}; color: {c["muted"]};
                                   border: 1px solid {c["border"]}; }}
    QPushButton#primary:focus {{ outline: none; border: 1px solid {c["text"]};
                                background: {c["accent"]}; }}
    QCheckBox:focus, QRadioButton:focus {{ outline: none; color: {c["accent"]}; }}
    QComboBox:focus {{ outline: none; border: 1px solid {c["accent"]}; }}
    QPlainTextEdit, QTextEdit {{ background: {c["panel"]}; color: {c["text"]};
                                border: 1px solid {c["border"]}; border-radius: 6px; }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {c["accent"]}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {c["panel"]};
                                          border: 1px solid {c["border"]};
                                          border-radius: 6px; padding: 4px 6px; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ outline: none;
                                                             border: 1px solid {c["accent"]}; }}
    QTableWidget, QTextBrowser, QListWidget, QTreeWidget, QAbstractItemView {{ outline: none; }}
    QTableWidget:focus, QTextBrowser:focus, QListWidget:focus {{ border: 1px solid {c["accent"]}; }}
    QListWidget#nav:focus {{ border: none; }}
    QToolButton:focus, QTabBar::tab:focus {{ outline: none; }}
    """


def apply_theme(app: QApplication, theme: str) -> None:
    app.setStyleSheet(stylesheet(theme))
