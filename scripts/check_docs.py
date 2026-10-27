r"""Проверка документации проектов ЖелезоЧек и бота (SPEC 1.3, задача 24.2).

Что проверяется в каждом проекте:
1. Относительные ссылки в .md (`[текст](путь)`, `![](картинка)`, `<img src>`) ведут на
   существующие файлы.
2. Каждый файл проекта упомянут в `docs/PROJECT_MAP.md` — своим путём или путём своей
   папки (`tests/fixtures/memtest/`); `__init__.py` — одной общей строкой. Каждая папка
   упомянута сама или через родителя.
3. Каждое изображение из `docs/images/` где-то используется (имя встречается в .md или
   скриптах), а каждое используемое — существует (это проверка ссылок из пункта 1).
4. В `docs/README.md` есть строка для каждого документа из `docs/`.
5. В корне нет файлов и папок вне разрешённого списка (SPEC 1.1, 14.8).

Файлы, которые git игнорирует, не проверяются. Скрипт использует только стандартную
библиотеку: его копия лежит в `..\tg_bot\scripts\check_docs.py` (CI бота), тест следит,
чтобы копии совпадали.

Запуск:
    .venv\Scripts\python scripts\check_docs.py               — оба проекта (бот — если рядом)
    .venv\Scripts\python scripts\check_docs.py ПАПКА [ПАПКА]  — указанные проекты
Код возврата: 0 — ошибок нет, 1 — есть ошибки (каждая напечатана отдельной строкой).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# Разрешённое содержимое корня (SPEC 1.1, 14.8). Проект определяется по pyproject.toml.
ALLOWED_ROOT = {
    "hwcheck": {
        "README.md", "CLAUDE.md", "PLAN.md", "pyproject.toml", ".gitignore", ".gitattributes",
        ".claude", ".github", "hwcheck", "licensing", "tests", "scripts", "tools", "vendor",
        "packaging", "docs", "LICENSE",
    },
    "zhelezocheck-bot": {
        "README.md", "CLAUDE.md", "pyproject.toml", "config.yaml", "run_bot.bat",
        "run_test_bot.bat", ".env.example", "LICENSE", ".gitignore", ".gitattributes", ".claude",
        ".github", "bot", "docs", "e2e", "scripts", "tests", "vendor",
        "app.py", "requirements.txt",
    },
}  # fmt: skip

# Без git (например, в тестовых фикстурах) эти папки не проверяются.
SKIP_DIRS = {".git", ".venv", ".tmp", "__pycache__", "dist", "build", "release", ".playwright"}
# Тестовые данные самого скрипта и примеры страниц не являются документацией проекта.
NOT_DOCS = ("tests/fixtures/",)
# Служебные файлы, которые достаточно описать в карте одной общей строкой.
GENERIC_FILES = {"__init__.py"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
USAGE_EXT = {".md", ".py", ".ps1", ".html", ".yml", ".yaml", ".txt"}

_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_IMG_SRC = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass
class Report:
    """Найденные ошибки одного проекта."""

    project: str
    errors: list[str] = field(default_factory=list)

    def add(self, kind: str, text: str) -> None:
        self.errors.append(f"{self.project}: {kind}: {text}")


def project_kind(root: Path) -> str:
    """Какой это проект — по имени в pyproject.toml (hwcheck / zhelezocheck-bot / '')."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return ""
    match = re.search(r'(?m)^name\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def project_files(root: Path) -> list[str]:
    """Файлы проекта (пути через «/»): отслеживаемые и новые, кроме игнорируемых git."""
    if (root / ".git").exists():
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files", "--cached", "--others",  # noqa: S607
             "--exclude-standard"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout  # fmt: skip
        return sorted({line for line in out.splitlines() if line and (root / line).is_file()})
    files = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS.intersection(rel.parts):
            files.append(rel.as_posix())
    return sorted(files)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def markdown_links(text: str) -> list[str]:
    """Цели ссылок в тексте .md (без блоков кода и `кода в строке`)."""
    text = _INLINE_CODE.sub("", _CODE_BLOCK.sub("", text))
    return _MD_LINK.findall(text) + _IMG_SRC.findall(text)


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)) or target.startswith(
        ("#", "//")
    )


def check_links(root: Path, files: list[str], report: Report) -> None:
    for name in files:
        if not name.endswith(".md") or name.startswith(NOT_DOCS):
            continue
        source = root / name
        for target in markdown_links(_read(source)):
            if _is_external(target):
                continue
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            path_part = path_part.replace("%20", " ")
            if not (source.parent / path_part).resolve().exists():
                report.add("битая ссылка", f"{name} → {target}")


def _mentioned(text: str, path: str) -> bool:
    return re.search(r"(?<![\w./-])" + re.escape(path) + r"(?![\w-])", text) is not None


def check_project_map(root: Path, files: list[str], report: Report) -> None:
    map_path = root / "docs" / "PROJECT_MAP.md"
    if not (root / "docs").is_dir() and project_kind(root) not in ALLOWED_ROOT:
        return  # не проект с документацией (например, пустой репозиторий в тестах)
    if not map_path.is_file():
        report.add("нет карты проекта", "docs/PROJECT_MAP.md")
        return
    text = _read(map_path)
    folders: set[str] = set()
    for name in files:
        parent = name.rsplit("/", 1)[0] + "/" if "/" in name else ""
        if parent:
            folders.add(parent)
        if _mentioned(text, name) or (parent and _mentioned(text, parent)):
            continue
        if name.rsplit("/", 1)[-1] in GENERIC_FILES and f"`{name.rsplit('/', 1)[-1]}`" in text:
            continue  # одна общая строка карты описывает все такие файлы
        report.add("нет в PROJECT_MAP", name)
    for folder in sorted(folders):
        parts = folder.rstrip("/").split("/")
        ancestors = ["/".join(parts[:i]) + "/" for i in range(1, len(parts) + 1)]
        if not any(_mentioned(text, item) for item in ancestors):
            report.add("папки нет в PROJECT_MAP", folder)


def check_images(root: Path, files: list[str], report: Report) -> None:
    images = [
        name
        for name in files
        if name.startswith("docs/images/") and Path(name).suffix.lower() in IMAGE_EXT
    ]
    if not images:
        return
    texts = [
        _read(root / name)
        for name in files
        if Path(name).suffix.lower() in USAGE_EXT and not name.startswith(NOT_DOCS)
    ]
    corpus = "\n".join(texts)
    for name in images:
        if Path(name).name not in corpus:
            report.add("изображение не используется", name)


def check_docs_index(root: Path, files: list[str], report: Report) -> None:
    index_path = root / "docs" / "README.md"
    documents = [
        name
        for name in files
        if name.startswith("docs/")
        and name.endswith(".md")
        and name != "docs/README.md"
        and not name.startswith("docs/archive/site/")
    ]
    if not documents:
        return
    if not index_path.is_file():
        report.add("нет оглавления", "docs/README.md")
        return
    index = _read(index_path)
    for name in documents:
        if name.removeprefix("docs/") not in index:
            report.add("нет в оглавлении docs/README.md", name)


def check_root(root: Path, files: list[str], report: Report) -> None:
    allowed = ALLOWED_ROOT.get(project_kind(root))
    if allowed is None:
        return
    for top in sorted({name.split("/", 1)[0] for name in files}):
        if top not in allowed:
            report.add("лишнее в корне", top)


def check_project(root: Path) -> list[str]:
    """Все ошибки документации проекта в папке `root`."""
    report = Report(root.name)
    files = project_files(root)
    check_links(root, files, report)
    check_project_map(root, files, report)
    check_images(root, files, report)
    check_docs_index(root, files, report)
    check_root(root, files, report)
    return report.errors


def default_projects() -> list[Path]:
    """Этот проект и соседний (бот или программа), если он лежит рядом."""
    projects = [HERE]
    for sibling in ("tg_bot", "ЖелезоЧек"):
        candidate = HERE.parent / sibling
        if candidate != HERE and (candidate / "pyproject.toml").is_file():
            projects.append(candidate)
    return projects


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    projects = [Path(arg).resolve() for arg in args] or default_projects()
    errors: list[str] = []
    for root in projects:
        found = check_project(root)
        errors.extend(found)
        print(f"{root.name}: {'ошибок нет' if not found else f'ошибок: {len(found)}'}")
    for line in errors:
        print("  " + line)
    return 1 if errors else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # TextIOWrapper
    sys.exit(main())
