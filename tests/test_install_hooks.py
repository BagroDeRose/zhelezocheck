"""Хук pre-commit (SPEC 1.1, 14.7): коммит с секретом блокируется, обычный — проходит."""

import subprocess
import sys
from pathlib import Path

from scripts import install_hooks

FAKE_TOKEN = "5" * 10 + ":" + "T" * 20 + "k" * 15


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    return repo


def test_hook_blocks_secret_and_allows_clean_commit(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    hook = install_hooks.install(repo, python=Path(sys.executable))
    assert hook.is_file() and "scan_secrets.py" in hook.read_text(encoding="utf-8")
    (repo / "ok.txt").write_text("обычный текст\n", encoding="utf-8")
    _git(repo, "add", "ok.txt")
    assert _git(repo, "commit", "-qm", "ok").returncode == 0
    (repo / "bad.py").write_text(f'TOKEN = "{FAKE_TOKEN}"\n', encoding="utf-8")
    _git(repo, "add", "bad.py")
    result = _git(repo, "commit", "-qm", "bad")
    assert result.returncode != 0
    assert FAKE_TOKEN not in result.stdout + result.stderr
    assert "bad.py" not in _git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout


def test_install_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = install_hooks.install(repo, python=Path(sys.executable)).read_text(encoding="utf-8")
    second = install_hooks.install(repo, python=Path(sys.executable)).read_text(encoding="utf-8")
    assert first == second


def test_hook_blocks_broken_documentation(tmp_path: Path) -> None:
    """24.2: коммит с битой ссылкой в документации отменяется."""
    repo = _repo(tmp_path)
    hook = install_hooks.install(repo, python=Path(sys.executable))
    assert "check_docs.py" in hook.read_text(encoding="utf-8")
    (repo / "README.md").write_text("[инструкция](docs/MISSING.md)", encoding="utf-8")
    _git(repo, "add", "README.md")
    result = _git(repo, "commit", "-qm", "docs")
    assert result.returncode != 0
    assert "docs/MISSING.md" in result.stdout + result.stderr  # строка об ошибке ссылки
