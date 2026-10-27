"""Список сторонних Python-пакетов и проверка лицензий (SPEC 1.4, 30.3)."""

from __future__ import annotations

import sys

import pytest

from scripts import third_party as tp


@pytest.mark.parametrize(
    ("license_text", "bad"),
    [
        ("MIT", False),
        ("BSD-3-Clause", False),
        ("Apache-2.0 OR BSD-3-Clause", False),
        ("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", False),  # Qt: выбираем LGPL
        ("LGPL-3.0-only", False),
        ("GPL-3.0-only", True),
        ("GNU General Public License v2 (GPLv2)", True),
        ("GPL-2.0-or-later WITH Classpath-exception-2.0", False),
        ("AGPL-3.0", True),
        ("", True),  # лицензия неизвестна — тоже повод разобраться
    ],
)
def test_incompatible_licenses(license_text: str, bad: bool) -> None:
    assert tp.incompatible(license_text) is bad


def test_runtime_packages_have_compatible_licenses() -> None:
    packages = tp.collect()
    names = {package.name.lower() for package in packages}
    assert {"pyside6", "numpy", "psutil", "jinja2"} <= names
    bad = [f"{p.name}: {p.license}" for p in packages if tp.incompatible(p.license)]
    assert bad == [], f"несовместимые или неизвестные лицензии: {bad}"


def test_notices_section_is_generated_and_current() -> None:
    text = tp.NOTICES.read_text(encoding="utf-8")
    assert tp.START in text and tp.END in text
    if sys.platform != "win32":
        pytest.skip("состав пакетов сборки — Windows; на Linux CI набор другой")
    assert tp.with_table(text, tp.collect()) == text, "пересоберите: python scripts/third_party.py"


def test_notices_have_gpl_offer_and_lgpl_notes() -> None:
    text = tp.NOTICES.read_text(encoding="utf-8")
    assert "RELEASE_7_5" in text and "письменное предложение" in text.lower()
    assert "LGPL" in text and "заменить" in text
