"""Тест клавиатуры: схема клавиш, отметка нажатых, итог «не нажималось: …».

Клавиша определяется по скан-коду — номеру физической клавиши, он не зависит от
раскладки (на русской раскладке «Q» печатает «Й», но скан-код у неё тот же — 16).
Если скан-кода нет (бывает в тестах и на некоторых системах), используется код клавиши Qt.
Клавишу Fn программа увидеть не может — она обрабатывается самим ноутбуком.
Клавишу Win (и сочетания Ctrl+Alt+Del, Alt+Tab) Windows перехватывает до программы: на схеме
она помечена «проверяется отдельно» и не попадает в список ненажатых (задача 25.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt

from hwcheck.laptop.texts import ManualResult, laptop_finding

K = Qt.Key


@dataclass(frozen=True)
class KeyDef:
    label: str
    scan: int  # скан-код набора 1; у «расширенных» клавиш (стрелки и т.п.) — 0x100 + код
    qt_key: int
    width: float = 1.0  # ширина на схеме, в «обычных» клавишах
    separate: bool = False  # Windows перехватывает клавишу — проверяется отдельно


SEPARATE_KEYS = {"Win"}  # клавиши, которые Windows обрабатывает раньше программы


def _row(*keys: tuple[str, int, K] | tuple[str, int, K, float]) -> list[KeyDef]:
    return [
        KeyDef(k[0], k[1], int(k[2]), k[3] if len(k) == 4 else 1.0, k[0] in SEPARATE_KEYS)
        for k in keys
    ]


LAYOUT: list[list[KeyDef]] = [
    _row(("Esc", 1, K.Key_Escape),
         *((f"F{n}", 58 + n, getattr(K, f"Key_F{n}")) for n in range(1, 11)),
         ("F11", 87, K.Key_F11), ("F12", 88, K.Key_F12), ("Del", 0x153, K.Key_Delete)),
    _row(("`", 41, K.Key_QuoteLeft), ("1", 2, K.Key_1), ("2", 3, K.Key_2), ("3", 4, K.Key_3),
         ("4", 5, K.Key_4), ("5", 6, K.Key_5), ("6", 7, K.Key_6), ("7", 8, K.Key_7),
         ("8", 9, K.Key_8), ("9", 10, K.Key_9), ("0", 11, K.Key_0), ("-", 12, K.Key_Minus),
         ("=", 13, K.Key_Equal), ("Backspace", 14, K.Key_Backspace, 2.0)),
    _row(("Tab", 15, K.Key_Tab, 1.5), ("Q", 16, K.Key_Q), ("W", 17, K.Key_W), ("E", 18, K.Key_E),
         ("R", 19, K.Key_R), ("T", 20, K.Key_T), ("Y", 21, K.Key_Y), ("U", 22, K.Key_U),
         ("I", 23, K.Key_I), ("O", 24, K.Key_O), ("P", 25, K.Key_P), ("[", 26, K.Key_BracketLeft),
         ("]", 27, K.Key_BracketRight), ("\\", 43, K.Key_Backslash, 1.5)),
    _row(("Caps", 58, K.Key_CapsLock, 1.75), ("A", 30, K.Key_A), ("S", 31, K.Key_S),
         ("D", 32, K.Key_D), ("F", 33, K.Key_F), ("G", 34, K.Key_G), ("H", 35, K.Key_H),
         ("J", 36, K.Key_J), ("K", 37, K.Key_K), ("L", 38, K.Key_L), (";", 39, K.Key_Semicolon),
         ("'", 40, K.Key_Apostrophe), ("Enter", 28, K.Key_Return, 2.25)),
    _row(("Shift", 42, K.Key_Shift, 2.25), ("Z", 44, K.Key_Z), ("X", 45, K.Key_X),
         ("C", 46, K.Key_C), ("V", 47, K.Key_V), ("B", 48, K.Key_B), ("N", 49, K.Key_N),
         ("M", 50, K.Key_M), (",", 51, K.Key_Comma), (".", 52, K.Key_Period),
         ("/", 53, K.Key_Slash), ("Shift ", 54, K.Key_Shift, 1.75), ("↑", 0x148, K.Key_Up)),
    _row(("Ctrl", 29, K.Key_Control, 1.5), ("Win", 0x15B, K.Key_Meta), ("Alt", 56, K.Key_Alt),
         ("Пробел", 57, K.Key_Space, 6.0), ("Alt ", 0x138, K.Key_AltGr),
         ("Ctrl ", 0x11D, K.Key_Control),
         ("←", 0x14B, K.Key_Left), ("↓", 0x150, K.Key_Down), ("→", 0x14D, K.Key_Right)),
]  # fmt: skip

_BY_SCAN = {key.scan: key for row in LAYOUT for key in row}
_BY_QT: dict[int, KeyDef] = {}
for _row_keys in LAYOUT:
    for _key in _row_keys:
        _BY_QT.setdefault(_key.qt_key, _key)  # для парных клавиш (Shift, Ctrl) — левая


def display_name(key: KeyDef) -> str:
    """Название клавиши для текста: у правых Shift/Ctrl/Alt (подпись с пробелом) — «(правый)»."""
    name = key.label.strip()
    return f"{name} (правый)" if key.label != name else name


def key_count() -> int:
    return len(_BY_SCAN)


def find_key(scan: int, qt_key: int) -> KeyDef | None:
    """Клавиша схемы по скан-коду, а если его нет — по коду Qt."""
    if scan and scan in _BY_SCAN:
        return _BY_SCAN[scan]
    return _BY_QT.get(qt_key)


@dataclass
class KeyboardTest:
    """Состояние теста: какие клавиши уже нажимались."""

    pressed: set[int] = field(default_factory=set)  # скан-коды

    def press(self, scan: int, qt_key: int) -> KeyDef | None:
        key = find_key(scan, qt_key)
        if key is not None:
            self.pressed.add(key.scan)
        return key

    def missing(self) -> list[KeyDef]:
        """Ненажатые клавиши схемы (кроме тех, что проверяются отдельно)."""
        return [
            key
            for row in LAYOUT
            for key in row
            if key.scan not in self.pressed and not key.separate
        ]

    def finding(self) -> ManualResult:
        missing = self.missing()
        if not missing:
            return laptop_finding("keyboard_ok")
        return laptop_finding("keyboard_missing", keys=", ".join(display_name(k) for k in missing))
