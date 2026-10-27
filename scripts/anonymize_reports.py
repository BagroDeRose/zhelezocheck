r"""Заменяет серийные номера в отчётах ручной проверки на `XXXX` (SPEC 1.1, задача 15.3).

Обрабатывает HTML и текстовые файлы в `docs/qa/manual_check/`. Модели устройств не трогает.
Запуск: .venv\Scripts\python scripts\anonymize_reports.py [папка]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FOLDER = ROOT / "docs" / "qa" / "manual_check"
MASK = "XXXX"

# Подпись поля серийного номера и само значение (буквы, цифры, дефисы, от 4 символов).
_SERIAL = re.compile(
    r"""(?P<label>\b(?:серийный\s+номер|serial[\s_-]?(?:number|no)?|s/n|sn)\b"?"""
    r"""(?:\s*[:=]\s*"?|\s+))"""
    r"""(?P<value>[A-Za-z0-9][A-Za-z0-9._-]{3,})""",
    re.IGNORECASE,
)


def find_serials(text: str) -> list[str]:
    return [m.group("value") for m in _SERIAL.finditer(text) if m.group("value") != MASK]


def anonymize_text(text: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        if match.group("value") == MASK:
            return match.group(0)
        count += 1
        return match.group("label") + MASK

    return _SERIAL.sub(replace, text), count


def anonymize_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    new_text, count = anonymize_text(text)
    if count:
        path.write_text(new_text, encoding="utf-8")
    return count


def main(argv: list[str] | None = None) -> int:
    folder = Path(argv[0]) if argv else DEFAULT_FOLDER
    total = 0
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() in (".html", ".htm", ".txt", ".md", ".json"):
            total += anonymize_file(path)
    print(f"Заменено серийных номеров: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
