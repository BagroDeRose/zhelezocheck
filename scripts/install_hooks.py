r"""Ставит хук pre-commit в оба проекта (SPEC 1.1, 14.7).

Перед каждым коммитом хук запускает `scan_secrets.py --staged` и `check_docs.py`
(SPEC 1.3, 24.2) для этого проекта. Если найден секрет, запрещённый файл или ошибка
документации (битая ссылка, файл не в карте проекта, лишнее изображение), коммит отменяется.

Запуск (из папки ЖелезоЧек):
    .venv\Scripts\python scripts\install_hooks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNER = ROOT / "scripts" / "scan_secrets.py"
DOCS_CHECKER = ROOT / "scripts" / "check_docs.py"
DEFAULT_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
DEFAULT_PROJECTS = [ROOT, ROOT.parent / "tg_bot"]

HOOK = """#!/bin/sh
# Хук установлен scripts/install_hooks.py (ЖелезоЧек): секреты и документация перед коммитом.
"{python}" "{scanner}" --staged "{repo}"
status=$?
if [ $status -ne 0 ]; then
  echo "Коммит отменён: найдены возможные секреты (см. выше). Значения не показываются."
  exit $status
fi
"{python}" "{docs_checker}" "{repo}"
status=$?
if [ $status -ne 0 ]; then
  echo "Коммит отменён: документация не в порядке (см. выше, Определение готовности)."
fi
exit $status
"""


def install(repo: Path, python: Path = DEFAULT_PYTHON) -> Path:
    """Записывает .git/hooks/pre-commit в репозиторий `repo` и возвращает путь к хуку."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    text = HOOK.format(
        python=python.as_posix(),
        scanner=SCANNER.as_posix(),
        docs_checker=DOCS_CHECKER.as_posix(),
        repo=repo.resolve().as_posix(),
    )
    hook.write_text(text, encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    return hook


def main() -> int:
    for project in DEFAULT_PROJECTS:
        if (project / ".git").exists():
            print(f"Хук установлен: {install(project)}")
        else:
            print(f"Пропущено (нет git): {project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
