"""Сканер секретов (SPEC 1.1, 14.5): находит секреты в рабочем дереве, в истории git и в списке
файлов, но никогда не печатает их значения.

Фейковые секреты собираются в коде, чтобы в исходниках тестов не было строк, похожих на секреты.
"""

import subprocess
from pathlib import Path

import pytest

from scripts import scan_secrets
from scripts import scan_secrets as ss

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT.parent / "tg_bot"

FAKE_TOKEN = "7" * 10 + ":" + "Q" * 20 + "w" * 15
FAKE_YK = "live" + "_" + "R" * 16 + "7" * 16
FAKE_PEM = "-----" + "BEGIN " + "PRIVATE KEY" + "-----\nMIIabc\n-----END PRIVATE KEY-----\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("Проект без секретов.\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    code = scan_secrets.main(list(args))
    return code, capsys.readouterr().out


def test_clean_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, str(_repo(tmp_path)))
    assert code == 0, out
    assert "секретов не найдено" in out


def test_token_in_history_found_without_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "bot.py").write_text(f'TOKEN = "{FAKE_TOKEN}"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "oops")
    commit = _git(repo, "rev-parse", "--short", "HEAD").strip()
    (repo / "bot.py").write_text("TOKEN = read_env()\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "fix")
    code, out = _run(capsys, str(repo))
    assert code == 1
    assert commit in out and "bot.py" in out and "telegram" in out.lower()
    assert FAKE_TOKEN not in out and "Q" * 20 not in out


def test_yookassa_key_and_pem_in_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / "keys.txt").write_text(FAKE_YK + "\n" + FAKE_PEM, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "keys")
    code, out = _run(capsys, str(repo))
    assert code == 1
    assert "yookassa" in out.lower() and "private" in out.lower()
    assert FAKE_YK not in out and "MIIabc" not in out


def test_untracked_working_tree_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    (repo / "notes.txt").write_text(f"токен {FAKE_TOKEN}\n", encoding="utf-8")
    code, out = _run(capsys, str(repo))
    assert code == 1 and "notes.txt" in out and FAKE_TOKEN not in out


def test_ignored_files_not_scanned_in_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (repo / ".env").write_text(f"BOT_TOKEN={FAKE_TOKEN}\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore")
    code, out = _run(capsys, str(repo))
    assert code == 0, out


def test_forbidden_file_tracked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    keygen = repo / "tools" / "keygen"
    keygen.mkdir(parents=True)
    (keygen / "issued.csv").write_text("issued,type\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "csv")
    code, out = _run(capsys, str(repo))
    assert code == 1 and "issued.csv" in out


def test_staged_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    (repo / "config.py").write_text(f'KEY = "{FAKE_YK}"\n', encoding="utf-8")
    _git(repo, "add", "config.py")
    code, out = _run(capsys, "--staged", str(repo))
    assert code == 1 and "config.py" in out and FAKE_YK not in out
    _git(repo, "reset", "-q")
    code, _ = _run(capsys, "--staged", str(repo))
    assert code == 0


def test_staged_forbidden_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    (repo / "bot.session").write_bytes(b"\x00session")
    _git(repo, "add", "-f", "bot.session")
    code, out = _run(capsys, "--staged", str(repo))
    assert code == 1 and "bot.session" in out


# Полный скан двух настоящих проектов: detect-secrets тратит 2–3 с на каждую длинную русскую
# строку (например, в docs/qa/MANUAL_QA.md), всего ~75 с — больше общего лимита теста (60 с).
@pytest.mark.timeout(300)
def test_real_projects_are_clean(capsys: pytest.CaptureFixture[str]) -> None:
    targets = [str(ROOT)] + ([str(BOT)] if (BOT / ".git").exists() else [])
    code, out = _run(capsys, *targets)
    assert code == 0, out


def test_detect_secrets_reads_russian_markdown(tmp_path: Path) -> None:
    """На русской Windows detect-secrets сам открывал бы файл в cp1251 и молча пропускал."""
    header = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "заметки.md").write_text(
        f"# Заметки — шифрование и ключи\n\nключ:\n{header}\n", encoding="utf-8"
    )
    found = scan_secrets.detect_secrets_scan(tmp_path, ["заметки.md"])
    assert any(f.location == "заметки.md:4" for f in found)


# --- SPEC 1.5, 33.1: личных данных владельца нет в юридических шаблонах и конфигурации ------


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("docs/legal/templates/OFFER.md", "Продавец: {{ФИО}}"),
        ("docs/legal/templates/EULA.md", "ИНН {{ИНН}}"),
        ("docs/legal/owner_details.yaml", 'fio: ""'),
        ("docs/legal/owner_details.yaml", "inn: 123456789012"),
        ("config.yaml", "passport_number: x"),
        ("docs/legal/PRIVACY.md", "Оператор — ИНН: 123456789012"),
        ("docs/legal/OFFER.md", "Дата рождения: 01.01.1990"),
    ],
)
def test_personal_data_fields_are_found(name: str, text: str) -> None:
    assert ss.personal_data_findings(name, text), text


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("docs/legal/owner_details.yaml", "holder: BagroDeRose\nemail: a@b.c"),
        # Правило словами — не поле с данными.
        ("docs/legal/README.md", "ФИО, дата рождения, ИНН, паспортные данные не указываются"),
        ("hwcheck/data/rules.yaml", "info: инструкция"),  # «info», «инструкция» — не fio/inn
        ("src/app.py", "fio: ''"),  # вне юридических файлов и конфигурации не проверяется
    ],
)
def test_personal_data_ok(name: str, text: str) -> None:
    assert ss.personal_data_findings(name, text) == []


def test_real_legal_files_have_no_personal_data() -> None:
    files = ss.working_tree_files(ROOT)
    findings = ss.personal_data_scan(ROOT, files)
    assert findings == [], findings
