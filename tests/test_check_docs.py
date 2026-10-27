"""Проверка документации (SPEC 1.3, задача 24.2): каждая ошибка ловится на маленьком проекте."""

from pathlib import Path

import pytest

from scripts import check_docs

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT.parent / "tg_bot"

GOOD_MAP = """# Карта
| `README.md` | описание |
| `pyproject.toml` | настройки |
| `docs/README.md` | оглавление |
| `docs/PROJECT_MAP.md` | карта |
| `docs/GUIDE.md` | инструкция |
| `docs/images/` | скриншоты |
| `hwcheck/` | код |
| `docs/` | документы |
| `__init__.py` | пакет |
"""


def make_project(tmp_path: Path) -> Path:
    """Маленький правильный проект (без git — файлы перебираются по папкам)."""
    root = tmp_path / "proj"
    files = {
        "README.md": "# Проект\n![Окно](docs/images/main.png)\nСм. [инструкцию](docs/GUIDE.md).\n",
        "pyproject.toml": '[project]\nname = "hwcheck"\n',
        "docs/README.md": "| `GUIDE.md` | инструкция |\n| `PROJECT_MAP.md` | карта |\n",
        "docs/PROJECT_MAP.md": GOOD_MAP,
        "docs/GUIDE.md": "Назад: [README](../README.md#раздел), сайт: [x](https://example.com)\n",
        "hwcheck/__init__.py": "",
        "hwcheck/module.py": "x = 1\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "docs" / "images").mkdir(parents=True)
    (root / "docs" / "images" / "main.png").write_bytes(b"png")
    return root


def test_clean_project_has_no_errors(tmp_path: Path) -> None:
    assert check_docs.check_project(make_project(tmp_path)) == []


def test_broken_link_is_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "docs" / "GUIDE.md").write_text("[нет](missing.md) `[в коде](no.md)`", encoding="utf-8")
    errors = check_docs.check_project(root)
    assert errors == ["proj: битая ссылка: docs/GUIDE.md → missing.md"]


def test_missing_image_link_is_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "docs" / "images" / "main.png").unlink()
    errors = check_docs.check_project(root)
    assert "proj: битая ссылка: README.md → docs/images/main.png" in errors


def test_unused_image_is_reported(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "docs" / "images" / "old_v12.png").write_bytes(b"png")
    errors = check_docs.check_project(root)
    assert errors == ["proj: изображение не используется: docs/images/old_v12.png"]


def test_file_missing_from_project_map(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "tools").mkdir()
    (root / "tools" / "helper.py").write_text("", encoding="utf-8")
    errors = check_docs.check_project(root)
    assert "proj: нет в PROJECT_MAP: tools/helper.py" in errors
    assert "proj: папки нет в PROJECT_MAP: tools/" in errors


def test_folder_mention_covers_its_files(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "hwcheck" / "other.py").write_text("", encoding="utf-8")
    assert check_docs.check_project(root) == []  # `hwcheck/` есть в карте


def test_document_missing_from_index(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "docs" / "NEW.md").write_text("текст", encoding="utf-8")
    text = (root / "docs" / "PROJECT_MAP.md").read_text(encoding="utf-8")
    (root / "docs" / "PROJECT_MAP.md").write_text(text + "| `docs/NEW.md` | x |\n", "utf-8")
    errors = check_docs.check_project(root)
    assert errors == ["proj: нет в оглавлении docs/README.md: docs/NEW.md"]


def test_unexpected_root_entry(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "notes.txt").write_text("заметка", encoding="utf-8")
    text = (root / "docs" / "PROJECT_MAP.md").read_text(encoding="utf-8")
    (root / "docs" / "PROJECT_MAP.md").write_text(text + "| `notes.txt` | x |\n", "utf-8")
    errors = check_docs.check_project(root)
    assert errors == ["proj: лишнее в корне: notes.txt"]


def test_missing_project_map(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    (root / "docs" / "PROJECT_MAP.md").unlink()
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    (root / "docs" / "README.md").write_text(text.replace("PROJECT_MAP", "x"), "utf-8")
    assert check_docs.check_project(root) == ["proj: нет карты проекта: docs/PROJECT_MAP.md"]


def test_main_returns_one_on_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_project(tmp_path)
    assert check_docs.main([str(root)]) == 0
    (root / "docs" / "GUIDE.md").write_text("[нет](missing.md)", encoding="utf-8")
    assert check_docs.main([str(root)]) == 1
    assert "битая ссылка" in capsys.readouterr().out


def test_bot_copy_is_identical() -> None:
    """Копия скрипта в боте (для его CI) совпадает с этой."""
    copy = BOT / "scripts" / "check_docs.py"
    if not copy.is_file():
        pytest.skip("бот не лежит рядом (CI программы) — сравнивать не с чем")
    original = (ROOT / "scripts" / "check_docs.py").read_bytes().replace(b"\r\n", b"\n")
    assert copy.read_bytes().replace(b"\r\n", b"\n") == original


def test_real_projects_pass() -> None:
    """Документация этого проекта (и бота, если он рядом) в порядке."""
    errors = check_docs.check_project(ROOT)
    if BOT.is_dir():
        errors += check_docs.check_project(BOT)
    assert errors == []
