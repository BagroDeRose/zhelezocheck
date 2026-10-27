r"""Поиск секретов в проектах ЖелезоЧек и бота (SPEC 1.1, задача 14.5).

Что проверяется в каждом проекте:
1. рабочее дерево (отслеживаемые и новые, не игнорируемые файлы) — detect-secrets и свои шаблоны;
2. ВСЯ история git (`git log -p --all`) — токен Telegram, ключи ЮKassa, закрытые ключи;
3. `git ls-files` — не попал ли в git файл, который должен быть только локальным
   (закрытый ключ лицензий, журнал ключей, `.env`, базы, сессии Telegram и т.п.).

Режим `--staged` (для хука pre-commit) проверяет только то, что сейчас подготовлено к коммиту.

Выводятся ТОЛЬКО имена файлов, строки и коммиты — никогда сами значения.
Код выхода: 0 — секретов нет, 1 — найдены.

Запуск:
    .venv\Scripts\python scripts\scan_secrets.py                 — оба проекта
    .venv\Scripts\python scripts\scan_secrets.py ..\tg_bot       — один проект
    .venv\Scripts\python scripts\scan_secrets.py --staged .      — подготовленное к коммиту
"""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECTS = [ROOT, ROOT.parent / "tg_bot"]

# Шаблоны секретов (SPEC 1.1, 14.5). Закрытый ключ ищется по полной строке заголовка PEM.
PATTERNS: dict[str, re.Pattern[str]] = {
    "Telegram bot token": re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}"),
    # Шаблоны SPEC `live_…`/`test_…` уточнены: настоящий ключ содержит заглавную букву и цифру,
    # а имена функций вроде test_missing_values_keep_sources — нет (см. DECISIONS.md).
    "YooKassa live key": re.compile(
        r"(?<![A-Za-z0-9_])live_(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"
    ),
    "YooKassa test key": re.compile(
        r"(?<![A-Za-z0-9_])test_(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"
    ),
    "Private key (PEM)": re.compile("-----" + r"BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY" + "-----"),
}

# Файлы, которые никогда не должны попадать в git (SPEC 1.1, 14.1).
FORBIDDEN_FILES = re.compile(
    r"(^|/)(tools/keygen/private_key\.pem|tools/keygen/issued\.csv|data/license[^/]*"
    r"|data/history\.sqlite|\.env|e2e/\.env\.e2e|tg_key\.txt|test_shop_yookassa\.txt)$"
    r"|\.(pem|key|sqlite|session)$"
)

# Плагины detect-secrets: все стандартные, кроме «высокой энтропии» — они срабатывают на любые
# хэши и контрольные суммы (SHA-256 в CHECKSUMS.txt, открытый ключ лицензий), см. DECISIONS.md.
EXCLUDED_PLUGINS = {"HexHighEntropyString", "Base64HighEntropyString"}


@dataclass(frozen=True)
class Finding:
    where: str  # «рабочее дерево», «история», «индекс», «к коммиту»
    location: str  # файл[:строка] или «коммит abc123, файл x»
    kind: str

    def __str__(self) -> str:
        return f"  [{self.where}] {self.location} — {self.kind}"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 — фиксированная команда git, аргументы списком
        ["git", *args], cwd=repo, capture_output=True, check=False
    )
    return result.stdout.decode("utf-8", errors="replace")


def _match_kinds(text: str) -> list[str]:
    return [kind for kind, pattern in PATTERNS.items() if pattern.search(text)]


# --------------------------------------------------------------------------- рабочее дерево


def _plugins() -> list[dict[str, str]]:
    from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class

    names = {cls.__name__ for cls in get_mapping_from_secret_type_to_class().values()}
    return [{"name": name} for name in sorted(names - EXCLUDED_PLUGINS)]


def detect_secrets_scan(repo: Path, files: list[str]) -> list[Finding]:
    from detect_secrets.core import scan as ds_scan
    from detect_secrets.core.secrets_collection import SecretsCollection
    from detect_secrets.settings import transient_settings

    existing = [name for name in files if (repo / name).is_file()]
    findings: list[Finding] = []
    # detect-secrets открывает файлы кодировкой системы (на русской Windows — cp1251) и молча
    # пропускает те, что не прочитались, — то есть почти все русские .md. Подставляем ему
    # чтение в UTF-8 (как в CI на Linux); настоящие двоичные файлы по-прежнему пропускаются.
    ds_scan.open = functools.partial(open, encoding="utf-8")  # type: ignore[attr-defined]  # подмена встроенной open только внутри модуля detect-secrets
    try:
        with transient_settings({"plugins_used": _plugins()}):
            collection = SecretsCollection(root=str(repo))
            for name in existing:  # по одному файлу: без пула процессов Windows
                collection.scan_file(name)
            for filename, secret in collection:
                rel = Path(filename).as_posix()
                findings.append(
                    Finding("рабочее дерево", f"{rel}:{secret.line_number}", secret.type)
                )
    finally:
        del ds_scan.open  # type: ignore[attr-defined]  # вернуть встроенную open
    return findings


def pattern_scan(repo: Path, files: list[str], where: str) -> list[Finding]:
    findings: list[Finding] = []
    for name in files:
        path = repo / name
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            for kind in _match_kinds(line):
                findings.append(Finding(where, f"{name}:{number}", kind))
    return findings


def working_tree_files(repo: Path) -> list[str]:
    return [
        line for line in _git(repo, "ls-files", "-co", "--exclude-standard").splitlines() if line
    ]


# --------------------------------------------------------------------------- история git


def history_scan(repo: Path) -> list[Finding]:
    """Ищет шаблоны во всех версиях всех файлов во всех ветках."""
    log = _git(repo, "log", "-p", "--all", "--no-color", "--no-ext-diff", "--format=commit %h")
    findings: set[Finding] = set()
    commit = "?"
    filename = "?"
    for line in log.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
        elif line.startswith("diff --git "):
            filename = line.rsplit(" b/", 1)[-1]
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            for kind in _match_kinds(line):
                findings.add(Finding("история", f"коммит {commit}, файл {filename}", kind))
    return sorted(findings, key=str)


def forbidden_tracked(repo: Path) -> list[Finding]:
    files = _git(repo, "ls-files").splitlines()
    return [
        Finding("в git", name, "файл не должен быть в git")
        for name in files
        if FORBIDDEN_FILES.search(name)
    ]


# --------------------------------------------------------------------------- проверки


# Анонимность владельца (SPEC 1.5, 33.1): в юридических шаблонах, документах и конфигурации
# не должно быть полей и плейсхолдеров с личными данными — ФИО, ИНН, дата рождения, паспорт.
# Слова в описании правила («ФИО, ИНН … не указываются») полем не считаются.
PERSONAL_DATA = {
    "плейсхолдер личных данных": re.compile(
        r"\{\{[^{}]*(ФИО|ИНН|РОЖДЕН|ПАСПОРТ)[^{}]*\}\}", re.IGNORECASE
    ),
    "поле личных данных в конфигурации": re.compile(
        r"^\s*[\"']?(fio|inn|birth\w*|passport\w*|фио|инн)[\"']?\s*:", re.IGNORECASE | re.MULTILINE
    ),
    "поле личных данных в документе": re.compile(
        r"(ФИО|ИНН|Дата рождения|Паспорт\w*)\s*:\s*\S|ИНН\s+\d{10,12}", re.IGNORECASE
    ),
}
_CONFIG_SUFFIXES = (".yaml", ".yml", ".toml", ".json", ".ini", ".cfg")


def _personal_scope(name: str) -> bool:
    """Юридические файлы и конфигурация — где такие поля могли бы появиться."""
    posix = name.replace("\\", "/")
    return (
        "legal/" in posix
        or posix.endswith(_CONFIG_SUFFIXES)
        or posix.split("/")[-1]
        in (
            "LICENSE",
            "ЛИЦЕНЗИЯ.txt",
        )
    )


def personal_data_findings(name: str, text: str) -> list[str]:
    if not _personal_scope(name):
        return []
    return [kind for kind, pattern in PERSONAL_DATA.items() if pattern.search(text)]


def personal_data_scan(repo: Path, files: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for name in files:
        path = repo / name
        if not path.is_file() or not _personal_scope(name) or path.stat().st_size > 2_000_000:
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        findings += [
            Finding("рабочее дерево", name, kind) for kind in personal_data_findings(name, text)
        ]
    return findings


def scan_project(repo: Path) -> list[Finding]:
    files = working_tree_files(repo)
    return (
        detect_secrets_scan(repo, files)
        + pattern_scan(repo, files, "рабочее дерево")
        + personal_data_scan(repo, files)
        + history_scan(repo)
        + forbidden_tracked(repo)
    )


def scan_staged(repo: Path) -> list[Finding]:
    names = [
        n
        for n in _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
        if n
    ]
    findings = [
        Finding("к коммиту", n, "файл не должен быть в git")
        for n in names
        if FORBIDDEN_FILES.search(n)
    ]
    filename = "?"
    for line in _git(repo, "diff", "--cached", "-U0", "--no-color").splitlines():
        if line.startswith("diff --git "):
            filename = line.rsplit(" b/", 1)[-1]
        elif line.startswith("+") and not line.startswith("+++"):
            findings += [Finding("к коммиту", filename, kind) for kind in _match_kinds(line)]
    findings += [Finding("к коммиту", f.location, f.kind) for f in detect_secrets_scan(repo, names)]
    findings += [Finding("к коммиту", f.location, f.kind) for f in personal_data_scan(repo, names)]
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Поиск секретов (выводит только имена файлов)")
    parser.add_argument("projects", nargs="*", type=Path, help="папки проектов (git)")
    parser.add_argument("--staged", action="store_true", help="только подготовленное к коммиту")
    args = parser.parse_args(argv)
    projects = args.projects or [p for p in DEFAULT_PROJECTS if (p / ".git").exists()]
    total = 0
    for project in projects:
        repo = project.resolve()
        findings = scan_staged(repo) if args.staged else scan_project(repo)
        unique = list(dict.fromkeys(findings))
        if unique:
            print(f"{repo.name}: НАЙДЕНЫ возможные секреты ({len(unique)}):")
            for finding in unique:
                print(finding)
        else:
            print(f"{repo.name}: секретов не найдено")
        total += len(unique)
    return 1 if total else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # TextIOWrapper
    sys.exit(main())
