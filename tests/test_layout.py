"""Порядок в папке проекта (SPEC 1.1, 14.8): в корне только нужное, у документов есть оглавление."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT = {
    "README.md", "CLAUDE.md", "PLAN.md", "pyproject.toml", ".gitignore", ".gitattributes",
    ".claude", ".github", "hwcheck", "licensing", "tests", "scripts", "tools", "vendor",
    "packaging", "docs", "LICENSE",  # LICENSE — SPEC 1.4, 30.2
}  # fmt: skip


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def test_root_has_only_allowed_entries() -> None:
    top = {name.split("/", 1)[0] for name in _tracked()}
    assert top <= ALLOWED_ROOT, sorted(top - ALLOWED_ROOT)


def test_docs_index_mentions_every_document() -> None:
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    documents = [
        name
        for name in _tracked()
        if name.startswith("docs/")
        and name.endswith(".md")
        and name != "docs/README.md"
        and not name.startswith("docs/archive/site/")
    ]
    missing = [name for name in documents if name.removeprefix("docs/") not in index]
    assert missing == []


def test_ci_checks_documentation() -> None:
    """24.2: проверка документации — в CI программы."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert (
        workflow.count("scripts/check_docs.py .") + workflow.count(r"scripts\check_docs.py .") == 2
    )
