"""Все секреты и артефакты из SPEC 1.1 (14.1, 14.4) игнорируются git в обоих проектах."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT.parent / "tg_bot"

COMMON = [
    ".env", "x.pem", "x.key", "x.sqlite", "a.session", ".tmp/x", ".playwright/x", "dist/x",
    "build/x", "release/x.zip", ".coverage", "pkg.egg-info/x", ".ruff_cache/x", ".idea/x",
]  # fmt: skip
PROJECT = [
    "tools/keygen/private_key.pem", "tools/keygen/issued.csv", "data/license.txt",
    "data/history.sqlite", "data/x", "vendor/memtest_vulkan/memtest_vulkan.exe",
]  # fmt: skip
BOT_ONLY = [
    "data/bot.sqlite",
    "e2e/.env.e2e",
    "e2e/test.session",
    "e2e/test_account.session",
    "e2e/test_account.session-journal",
    "e2e/.tmp/qr.png",
    "tg_key.txt",
]


def _ignored(repo: Path, path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", path], cwd=repo, capture_output=True
    )
    return result.returncode == 0


@pytest.mark.parametrize("path", COMMON + PROJECT)
def test_project_ignores(path: str) -> None:
    assert _ignored(ROOT, path), path


def test_checksums_not_ignored() -> None:
    assert not _ignored(ROOT, "vendor/CHECKSUMS.txt")


@pytest.mark.skipif(not (BOT / ".git").exists(), reason="папки бота нет рядом")
@pytest.mark.parametrize("path", COMMON + BOT_ONLY)
def test_bot_ignores(path: str) -> None:
    assert _ignored(BOT, path), path


@pytest.mark.skipif(not (BOT / ".git").exists(), reason="папки бота нет рядом")
def test_bot_env_example_not_ignored() -> None:
    assert not _ignored(BOT, ".env.example")


@pytest.mark.skipif(not (BOT / ".git").exists(), reason="папки бота нет рядом")
def test_test_account_files_are_not_tracked() -> None:
    """20.2: сессия тестового аккаунта и его данные входа не попадают в git."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "e2e"], cwd=BOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert not [n for n in tracked if n.endswith((".session", ".env.e2e", "-journal"))]
