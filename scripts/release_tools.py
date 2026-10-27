r"""Помощник выпуска версии (SPEC 1.1, этап 18). Его вызывает `scripts\release.ps1`.

Команды:
    prepare X.Y.Z   — записать версию (pyproject.toml, hwcheck/__init__.py);
    check-dist      — проверить готовую папку dist\ЖелезоЧек: наверху только exe, ПРОЧТИ.txt,
                      LICENSE и _internal; нет секретов и данных пользователя;
    pack X.Y.Z      — упаковать dist\ЖелезоЧек в release\ЖелезоЧек-vX.Y.Z.zip и записать SHA-256;
    notes X.Y.Z ФАЙЛ — текст релиза из docs/CHANGELOG.md (что нового) для GitHub, в ФАЙЛ.
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scan_secrets import FORBIDDEN_FILES, PATTERNS  # noqa: E402 — после настройки sys.path

APP_NAME = "ЖелезоЧек"
DIST = ROOT / "dist" / APP_NAME
RELEASE = ROOT / "release"
RELEASE_JOURNAL = ROOT / "docs" / "qa" / "RELEASE_JOURNAL.md"
TOP_LEVEL = {f"{APP_NAME}.exe", "ПРОЧТИ.txt", "LICENSE", "_internal"}
LICENSE_MARK = "MIT License"  # свободная лицензия MIT (версия 2.0)
# X.Y.Z — финальный выпуск, X.Y.Z-rcN — кандидат (SPEC 1.5, 33.4).
_VERSION = re.compile(r"^\d+\.\d+\.\d+(-rc[1-9]\d*)?$")
QA_DIR = ROOT / "docs" / "qa"
TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml", ".ini", ".cfg", ".env", ".csv", ".html"}


class ReleaseError(Exception):
    """Выпуск остановлен: текст — что не так."""


def check_version(version: str) -> str:
    if not _VERSION.match(version):
        raise ReleaseError(f"версия должна быть вида 1.2.3 или 1.2.3-rc1, а не «{version}»")
    return version


def is_candidate(version: str) -> bool:
    return "-rc" in check_version(version)


def base_version(version: str) -> str:
    """1.5.0-rc2 → 1.5.0 (чек-лист ручной проверки один на версию)."""
    return check_version(version).split("-", 1)[0]


def manual_qa_passed(version: str, qa_dir: Path = QA_DIR) -> bool:
    """Владелец прошёл чек-лист `MANUAL_QA_<версия>.md`: в нём строка «Статус: пройдено»."""
    path = qa_dir / f"MANUAL_QA_{base_version(version)}.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8").replace("*", "")
    return re.search(r"(?mi)^\s*Статус:\s*пройдено\b", text) is not None


def set_version(version: str, root: Path = ROOT) -> None:
    check_version(version)
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new_text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text, count=1)
    if count != 1:
        raise ReleaseError("в pyproject.toml не найдена строка version")
    pyproject.write_text(new_text, encoding="utf-8", newline="\n")
    init = root / "hwcheck" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    new_text, count = re.subn(r'(?m)^__version__ = "[^"]+"$', f'__version__ = "{version}"', text)
    if count != 1:
        raise ReleaseError("в hwcheck/__init__.py не найдена строка __version__")
    init.write_text(new_text, encoding="utf-8", newline="\n")


def check_dist(dist: Path = DIST) -> list[str]:
    """Проблемы готовой папки программы (пустой список — всё в порядке)."""
    if not dist.is_dir():
        return [f"нет папки сборки {dist}"]
    problems: list[str] = []
    top = {item.name for item in dist.iterdir()}
    if top != TOP_LEVEL:
        problems.append(
            f"наверху папки должны быть только {sorted(TOP_LEVEL)}, а есть {sorted(top)}"
        )
    license_file = dist / "LICENSE"
    if not license_file.is_file():
        problems.append("нет файла LICENSE в корне")
    elif LICENSE_MARK not in license_file.read_text(encoding="utf-8-sig")[:400]:
        problems.append("LICENSE — не лицензия MIT")
    if not (dist / "_internal" / "THIRD_PARTY_NOTICES.md").is_file():
        problems.append("нет _internal/THIRD_PARTY_NOTICES.md (лицензии сторонних компонентов)")
    for path in dist.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(dist).as_posix()
        if FORBIDDEN_FILES.search(rel) or rel.startswith(("data/", "_internal/data/")):
            problems.append(f"лишний файл: {rel}")
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size < 5_000_000:
            text = path.read_bytes().decode("utf-8", errors="replace")
            kinds = [kind for kind, pattern in PATTERNS.items() if pattern.search(text)]
            if kinds:
                problems.append(f"похоже на секрет ({', '.join(kinds)}): {rel}")
    return problems


def archive_name(version: str) -> str:
    return f"{APP_NAME}-v{check_version(version)}.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack(version: str, dist: Path = DIST, release: Path = RELEASE) -> tuple[Path, str]:
    """Архив `ЖелезоЧек-vX.Y.Z.zip` с папкой ЖелезоЧек внутри и файл с его SHA-256.

    Кандидат (`-rcN`) кладётся в `release/candidates/` (SPEC 1.5, 33.4).
    """
    if is_candidate(version):
        release = release / "candidates"
    release.mkdir(parents=True, exist_ok=True)
    target = release / archive_name(version)
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                zf.write(path, f"{APP_NAME}/{path.relative_to(dist).as_posix()}")
    digest = sha256(target)
    # Переводы строк LF: файл проверяется и `sha256sum -c`, и вручную в PowerShell.
    (release / f"{target.name}.sha256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8", newline="\n"
    )
    return target, digest


ASCII_NAME = "ZhelezoChek"


def upload_copies(version: str, release: Path = RELEASE) -> tuple[Path, Path]:
    """Копии архива с латинским именем для GitHub: он удаляет кириллицу из имён вложений.

    Русское имя показывается подписью вложения (label) — см. release.ps1 и publish_download.py.
    """
    source = release / archive_name(version)
    folder = release / "upload"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{ASCII_NAME}-v{version}.zip"
    target.write_bytes(source.read_bytes())
    sha_file = folder / f"{target.name}.sha256"
    sha_file.write_text(f"{sha256(target)}  {target.name}\n", encoding="utf-8", newline="\n")
    return target, sha_file


def release_notes(version: str, changelog: Path = ROOT / "docs" / "CHANGELOG.md") -> str:
    """Что нового — разделы CHANGELOG с пометкой версии (или последние этапы)."""
    text = changelog.read_text(encoding="utf-8")
    marker = f"## Версия {version}"
    if marker in text:
        section = text.split(marker, 1)[1].split("\n## ", 1)[0]
        return f"{marker}{section}".strip()
    return text.strip().rsplit("\n## ", 1)[-1]


JOURNAL_HEADER = (
    "# Журнал выпуска: одобрения публикаций\n\n"
    "Публикация в открытый доступ — только по прямой команде владельца "
    "(CLAUDE.md, раздел 5; SPEC 1.4, 29.1).\n"
    'Запись делает `release.ps1 -Publish -IConfirmOwnerApproved -ApprovedBy "…"`.\n\n'
    "| Когда | Версия | Кто одобрил |\n|---|---|---|\n"
)


def approve_publish(
    version: str,
    approved_by: str,
    journal: Path = RELEASE_JOURNAL,
    now: datetime | None = None,
    action: str = "публикация",
) -> str:
    """Запись в журнал выпуска: кто и когда одобрил публикацию (SPEC 1.4, 29.1).

    Без этой записи release.ps1 в открытый доступ ничего не публикует.
    """
    check_version(version)
    who = approved_by.strip()
    if not who:
        raise ReleaseError("не указано, кто одобрил публикацию (-ApprovedBy)")
    if not journal.exists():
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(JOURNAL_HEADER, encoding="utf-8")
    line = f"| {(now or datetime.now()):%d.%m.%Y %H:%M} | {version} ({action}) | {who} |"
    with journal.open("a", encoding="utf-8") as file:
        file.write(line + "\n")
    return line


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    command, rest = args[0], args[1:]
    try:
        if command == "prepare":
            set_version(rest[0])
            print(f"Версия {rest[0]}")
        elif command == "check-dist":
            problems = check_dist()
            for problem in problems:
                print(f"ПРОБЛЕМА: {problem}")
            if problems:
                return 1
            print("Папка программы чистая")
        elif command == "pack":
            target, digest = pack(rest[0])
            print(f"{target}\nSHA-256: {digest}")
        elif command == "upload-copies":
            target, sha_file = upload_copies(rest[0])
            print(f"{target}\n{sha_file}")
        elif command == "notes":
            # В файл (UTF-8): в консоли Windows символы вроде «₽» могут не печататься.
            Path(rest[1]).write_text(release_notes(rest[0]) + "\n", encoding="utf-8")
        elif command == "approve-publish":
            print(f"Журнал выпуска: {approve_publish(rest[0], ' '.join(rest[1:]))}")
        elif command == "approve-final":
            line = approve_publish(rest[0], " ".join(rest[1:]), action="финальный выпуск")
            print(f"Журнал выпуска: {line}")
        elif command == "manual-qa":
            if not manual_qa_passed(rest[0]):
                name = f"docs/qa/MANUAL_QA_{base_version(rest[0])}.md"
                print(f"Финальный выпуск отменён: в {name} нет «Статус: пройдено»")
                return 1
            print("Ручная проверка пройдена")
        else:
            print(__doc__)
            return 2
    except (ReleaseError, IndexError) as error:
        print(f"Ошибка: {error or 'не хватает аргументов'}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
