"""Проверки настроек сборки: без требования прав администратора, без инструментов владельца,
с данными программы, со всеми лицензиями."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_spec_settings() -> None:
    spec = (ROOT / "packaging" / "hwcheck.spec").read_text(encoding="utf-8")
    assert "uac_admin=False" in spec
    assert "console=False" in spec
    assert 'collect_data_files("hwcheck")' in spec
    assert "icon.ico" in spec and "SPECPATH" in spec
    assert (ROOT / "hwcheck" / "data" / "icon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_build_script_copies_vendor_and_runs_smoke_test() -> None:
    script = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8-sig")
    assert "CHECKSUMS.txt" in script and "THIRD_PARTY_NOTICES.md" in script
    assert "--smoke-test" in script
    assert "HWCHECK_ROOT" in script  # данные самопроверки — во временной папке
    assert "PYINSTALLER_CONFIG_DIR" in script and "GetTempPath" not in script


def test_notices_mention_all_components() -> None:
    notices = (ROOT / "packaging" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name in (
        "memtest_vulkan",
        "zlib",
        "smartmontools",
        "GPL v2.0",
        "LGPL-3.0",
        "PySide6",
        "BSD-3-Clause",
        "pci.ids",
        "wgpu",
        "numpy",
        "beautifulsoup4",
    ):
        assert name in notices, name


def _workflow(name: str) -> dict:
    import yaml

    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow[True] if True in workflow else workflow["on"]  # YAML читает «on» как True


def test_release_workflow_disabled() -> None:
    # SPEC 1.1, 14.10: релизы собираются локально (scripts/release.ps1), CI-релиз отключён.
    triggers = _triggers(_workflow("release.yml"))
    assert set(triggers) == {"workflow_dispatch"}


def test_tests_workflow_saves_windows_minutes() -> None:
    workflow = _workflow("tests.yml")
    triggers = _triggers(workflow)
    assert "push" in triggers and "workflow_dispatch" in triggers
    jobs = workflow["jobs"]
    assert jobs["linux"]["runs-on"] == "ubuntu-latest"
    windows = jobs["windows"]
    assert windows["runs-on"] == "windows-latest"
    assert "refs/tags/" in windows["if"] and "workflow_dispatch" in windows["if"]


def test_release_layout_and_readme() -> None:
    """Наверху архива exe, ПРОЧТИ.txt, LICENSE и _internal (версия 2.0, лицензия MIT)."""
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "build.ps1").read_text(encoding="utf-8-sig")
    assert "$Internal = Join-Path $Dist '_internal'" in script
    assert "-Destination $Dist\n" not in script.replace("\r\n", "\n")  # ничего лишнего наверх
    assert "ПРОЧТИ.txt" in script and "LICENSE" in script
    template = (root / "packaging" / "ПРОЧТИ.txt").read_text(encoding="utf-8")
    assert "{VERSION}" in template and "LICENSE" in template


def test_spec_drops_webengine_and_debug_resources() -> None:
    """25.4: движка браузера в сборке нет; 18.3: отладочные копии ресурсов не попадают."""
    root = Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "hwcheck.spec").read_text(encoding="utf-8")
    assert '"PySide6.QtWebEngineCore"' in spec and '"Qt6WebEngine"' in spec
    assert ".debug.pak" in spec


def test_build_saves_smoke_output_as_evidence() -> None:
    """SPEC 1.3, 24.3: полный вывод самопроверки exe — в docs/qa/smoke_<версия>.txt,
    выпуск коммитит этот файл вместе с версией."""
    build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8-sig")
    assert r"docs\qa\smoke_$Version.txt" in build and "Код выхода" in build
    release = (ROOT / "scripts" / "release.ps1").read_text(encoding="utf-8-sig")
    assert r'"docs\qa\smoke_$Version*"' in release  # вывод и снимки клавиатуры из exe
    assert "keyboard_*.png" in build
