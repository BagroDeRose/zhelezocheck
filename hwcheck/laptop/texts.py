"""Находки ручных проверок по текстам из `data/laptop_checks.yaml`."""

from __future__ import annotations

from functools import cache
from typing import Any

import yaml

from hwcheck.config import package_data_dir
from hwcheck.models import Finding, Severity

ManualResult = tuple[Finding, str | None]  # находка и аргумент для торга


@cache
def _texts() -> dict[str, Any]:
    return yaml.safe_load((package_data_dir() / "laptop_checks.yaml").read_text(encoding="utf-8"))


def laptop_finding(key: str, **values: Any) -> ManualResult:
    spec = _texts()[key]
    finding = Finding(
        id=f"laptop.{key}",
        severity=Severity(spec["severity"]),
        component="laptop",
        title=spec["title"].format(**values),
        explanation=spec["explanation"].format(**values),
        advice=spec.get("advice", "").format(**values),
        weight=float(spec.get("weight", 0)),
    )
    bargain = spec.get("bargain")
    return finding, bargain.format(**values) if bargain else None
