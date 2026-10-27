r"""Список сторонних Python-пакетов программы и проверка их лицензий (SPEC 1.4, 30.3).

Берёт зависимости программы из `pyproject.toml` (без dev-зависимостей), проходит по ним вглубь
(`importlib.metadata`, с учётом условий платформы) и для каждого пакета находит лицензию: поле
`License-Expression`, `License`, классификатор или первая строка файла лицензии из пакета.

Несовместимой считается лицензия GPL/AGPL без исключения и без альтернативы (LGPL, MIT…),
а также неизвестная: такие библиотеки работают внутри нашего процесса, и их условия
распространились бы на всю программу.

Таблица записывается в `packaging/THIRD_PARTY_NOTICES.md` между маркерами.
Запуск: `.venv\Scripts\python scripts\third_party.py` (с `--check` — только проверить).
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "packaging" / "THIRD_PARTY_NOTICES.md"
START = "<!-- python-packages:start -->"
END = "<!-- python-packages:end -->"
_GPL = re.compile(r"(?<![L])(A?GPL|GNU (Affero )?General Public License)", re.IGNORECASE)
_LESSER = re.compile(r"LGPL|Lesser General Public", re.IGNORECASE)


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    license: str
    url: str


def incompatible(license_text: str) -> bool:
    """GPL/AGPL без исключения и без более мягкой альтернативы (OR) — нельзя внутри процесса."""
    text = license_text.strip()
    if not text:
        return True
    alternatives = re.split(r"\s+OR\s+", text)
    for option in alternatives:
        if "exception" in option.lower() or _LESSER.search(option) or not _GPL.search(option):
            return False  # есть вариант, совместимый с закрытой программой
    return True


def _license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    value = (meta.get("License-Expression") or "").strip()
    if not value:
        short = (meta.get("License") or "").strip().splitlines()
        value = short[0].strip() if short and len(short[0]) <= 80 else ""
    if not value:
        classifiers = [
            c.split("::")[-1].strip()
            for c in meta.get_all("Classifier") or []
            if c.startswith("License ::")
        ]
        value = " / ".join(classifiers)
    if not value:
        for file in dist.files or []:
            if "LICEN" in file.name.upper():
                lines = [ln.strip() for ln in file.read_text(encoding="utf-8").splitlines()]
                value = next((ln for ln in lines if ln), "")
                break
    return value


def _url(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    if meta.get("Home-page"):
        return str(meta["Home-page"])
    for entry in meta.get_all("Project-URL") or []:
        label, _, link = entry.partition(",")
        if label.strip().lower() in ("homepage", "source", "repository"):
            return link.strip()
    return ""


def runtime_requirements(pyproject: Path = ROOT / "pyproject.toml") -> list[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return [Requirement(item).name for item in data["project"]["dependencies"]]


def collect(names: list[str] | None = None) -> list[Package]:
    """Все пакеты, которые программа тянет за собой (без dev-зависимостей)."""
    todo = list(names or runtime_requirements())
    seen: dict[str, Package] = {}
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # пакет для другой платформы — в эту сборку не входит
        seen[key] = Package(dist.metadata["Name"], dist.version, _license(dist), _url(dist))
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                todo.append(requirement.name)
    return sorted(seen.values(), key=lambda package: package.name.lower())


def table(packages: list[Package]) -> str:
    lines = [
        "| Пакет | Версия | Лицензия | Источник |",
        "|---|---|---|---|",
        *(f"| {p.name} | {p.version} | {p.license} | {p.url} |" for p in packages),
    ]
    return "\n".join(lines)


def with_table(notices: str, packages: list[Package]) -> str:
    head, rest = notices.split(START, 1)
    tail = rest.split(END, 1)[1]
    return f"{head}{START}\n{table(packages)}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    packages = collect()
    bad = [p for p in packages if incompatible(p.license)]
    for package in bad:
        print(f"НЕСОВМЕСТИМО или неизвестно: {package.name} {package.version} — {package.license}")
    text = NOTICES.read_text(encoding="utf-8")
    new = with_table(text, packages)
    if "--check" in args:
        if new != text:
            print("THIRD_PARTY_NOTICES.md устарел — запустите scripts/third_party.py")
            return 1
    else:
        NOTICES.write_text(new, encoding="utf-8", newline="\n")
        print(f"Пакетов: {len(packages)}, несовместимых: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
