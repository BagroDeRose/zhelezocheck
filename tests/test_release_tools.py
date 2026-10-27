"""Тесты помощника выпуска версии (этап 18). Версия 2.0: программа бесплатная, лицензия MIT."""

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from scripts import release_tools as rt

ROOT = Path(__file__).resolve().parent.parent
RELEASE_PS1 = ROOT / "scripts" / "release.ps1"

MIT_HEAD = "MIT License\n\nCopyright (c) 2026 BagroDeRose\n"


def _project(tmp_path: Path) -> Path:
    (tmp_path / "hwcheck").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n', "utf-8")
    (tmp_path / "hwcheck" / "__init__.py").write_text('"""x"""\n\n__version__ = "1.0.0"\n', "utf-8")
    return tmp_path


def test_set_version(tmp_path: Path) -> None:
    root = _project(tmp_path)
    rt.set_version("2.1.0", root)
    assert 'version = "2.1.0"' in (root / "pyproject.toml").read_text("utf-8")
    assert '__version__ = "2.1.0"' in (root / "hwcheck" / "__init__.py").read_text("utf-8")
    with pytest.raises(rt.ReleaseError):
        rt.set_version("2.1", root)


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / rt.APP_NAME
    (dist / "_internal" / "vendor").mkdir(parents=True)
    (dist / f"{rt.APP_NAME}.exe").write_bytes(b"MZ")
    (dist / "ПРОЧТИ.txt").write_text("как запустить", encoding="utf-8")
    (dist / "LICENSE").write_text(MIT_HEAD, encoding="utf-8")
    (dist / "_internal" / "lib.dll").write_bytes(b"\0" * 10)
    (dist / "_internal" / "THIRD_PARTY_NOTICES.md").write_text("лицензии", encoding="utf-8")
    return dist


def test_clean_dist_passes(tmp_path: Path) -> None:
    assert rt.check_dist(_dist(tmp_path)) == []


def test_dist_with_extra_files_fails(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    (dist / "data" / "logs").mkdir(parents=True)
    (dist / "data" / "history.sqlite").write_text("x", encoding="utf-8")
    (dist / "_internal" / "key.pem").write_text("x", encoding="utf-8")
    token = "12345678" + ":" + "B" * 35
    (dist / "_internal" / "notes.txt").write_text(f"token {token}", encoding="utf-8")
    problems = " ".join(rt.check_dist(dist))
    assert "наверху" in problems and "key.pem" in problems
    assert "notes.txt" in problems
    assert rt.check_dist(tmp_path / "нет") != []


def test_dist_requires_license_and_notices(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    (dist / "LICENSE").unlink()
    (dist / "_internal" / "THIRD_PARTY_NOTICES.md").unlink()
    problems = " ".join(rt.check_dist(dist))
    assert "LICENSE" in problems and "THIRD_PARTY_NOTICES.md" in problems


def test_dist_license_must_be_mit(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    (dist / "LICENSE").write_text("что-то другое", encoding="utf-8")
    assert any("LICENSE" in problem for problem in rt.check_dist(dist))


def test_build_ps1_puts_license_into_archive_root() -> None:
    build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8-sig")
    assert "'LICENSE'" in build  # лицензия MIT — в корень архива рядом с exe
    assert "THIRD_PARTY_NOTICES.md" in build


def test_pack_layout_and_checksum(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    target, digest = rt.pack("2.1.0", dist, tmp_path / "release")
    assert target.name == "ЖелезоЧек-v2.1.0.zip"
    names = zipfile.ZipFile(target).namelist()
    assert "ЖелезоЧек/ЖелезоЧек.exe" in names and "ЖелезоЧек/ПРОЧТИ.txt" in names
    assert all(name.startswith("ЖелезоЧек/") for name in names)
    sha_file = tmp_path / "release" / "ЖелезоЧек-v2.1.0.zip.sha256"
    assert sha_file.read_text("utf-8").split()[0] == digest == rt.sha256(target)


def test_upload_copies_have_latin_names(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    _, digest = rt.pack("2.1.0", dist, tmp_path / "release")
    copy, sha_file = rt.upload_copies("2.1.0", tmp_path / "release")
    assert copy.name == "ZhelezoChek-v2.1.0.zip" and copy.name.isascii()
    assert sha_file.read_text("utf-8").split() == [digest, "ZhelezoChek-v2.1.0.zip"]


def test_release_notes(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Что умеет\n\n## Версия 2.0.0\n- новое\n\n## Этап 1\n- старое\n", "utf-8"
    )
    notes = rt.release_notes("2.0.0", changelog)
    assert "новое" in notes and "старое" not in notes


def test_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert rt.main([]) == 2
    assert rt.main(["prepare"]) == 1
    assert rt.main(["что-то"]) == 2


def test_notes_command_writes_utf8_file(tmp_path: Path) -> None:
    out = tmp_path / "notes.md"
    assert rt.main(["notes", "2.0.0", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() != ""


def test_candidate_versions() -> None:
    assert rt.check_version("2.0.0-rc1") == "2.0.0-rc1"
    assert rt.is_candidate("2.0.0-rc1") and not rt.is_candidate("2.0.0")
    assert rt.base_version("2.0.0-rc2") == "2.0.0"
    for bad in ("2.0", "2.0.0rc1", "2.0.0-beta1", "2.0.0-rc"):
        with pytest.raises(rt.ReleaseError):
            rt.check_version(bad)


def test_candidate_is_packed_into_candidates_folder(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    target, digest = rt.pack("2.0.0-rc1", dist, tmp_path / "release")
    assert target == tmp_path / "release" / "candidates" / "ЖелезоЧек-v2.0.0-rc1.zip"
    assert target.is_file() and len(digest) == 64
    final, _ = rt.pack("2.0.0", dist, tmp_path / "release")
    assert final.parent == tmp_path / "release"


def test_manual_qa_status(tmp_path: Path) -> None:
    assert not rt.manual_qa_passed("2.0.0", tmp_path)  # чек-листа нет
    qa = tmp_path / "MANUAL_QA_2.0.0.md"
    qa.write_text("# Чек-лист\n\nСтатус: не пройдено\n", encoding="utf-8")
    assert not rt.manual_qa_passed("2.0.0", tmp_path)
    qa.write_text("# Чек-лист\n\n**Статус: пройдено** (владелец)\n", encoding="utf-8")
    assert rt.manual_qa_passed("2.0.0", tmp_path)
    assert rt.manual_qa_passed("2.0.0-rc3", tmp_path)  # чек-лист один на версию


def test_approve_publish_writes_journal(tmp_path: Path) -> None:
    journal = tmp_path / "RELEASE_JOURNAL.md"
    when = datetime(2026, 10, 27, 15, 30)
    rt.approve_publish("2.0.0", "владелец (команда в чате)", journal, now=when)
    rt.approve_publish("2.0.1", "владелец", journal, now=when)
    text = journal.read_text("utf-8")
    assert "| 27.10.2026 15:30 | 2.0.0 (публикация) | владелец (команда в чате) |" in text
    assert text.count("| 27.10.2026 15:30 |") == 2  # записи добавляются, а не заменяются


def test_approve_publish_needs_who_approved(tmp_path: Path) -> None:
    with pytest.raises(rt.ReleaseError):
        rt.approve_publish("2.0.0", "  ", tmp_path / "j.md")


def test_release_script_runs_core_steps() -> None:
    script = RELEASE_PS1.read_text(encoding="utf-8-sig")
    for step in (
        "git status --porcelain",
        "pytest",
        "release_tools.py prepare",
        "scan_secrets.py",
        "build.ps1",
        "check_no_traces.ps1",
        "check-dist",
        "pack",
        "git tag -a",
        "gh release create",
    ):
        assert step in script, step
    # Монетизации больше нет: ни продажного бота, ни страницы Google Диск.
    for gone in ("build_legal", "update_revoked", "publish_download", "gdrive"):
        assert gone not in script, gone


def test_release_ps1_candidate_makes_no_tag_or_release() -> None:
    """Тег и GitHub Release — только после выхода из блока кандидата (exit 0)."""
    script = RELEASE_PS1.read_text(encoding="utf-8-sig")
    candidate_exit = script.index("exit 0")
    for action in ("git tag -a", "gh release create"):
        assert script.index(action) > candidate_exit
