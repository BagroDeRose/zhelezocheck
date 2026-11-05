"""Расшифровка событий Windows (этап 46 v2.1): что значит событие, компонент и значимость;
тексты — в hwcheck/data/event_ids.yaml."""

from hwcheck.knowledge import events_db


def test_known_event_is_explained() -> None:
    info = events_db.describe("Microsoft-Windows-WHEA-Logger", 18, "whea")
    assert info.component and info.significance == "высокая"
    assert "неисправим" in info.title.lower()


def test_kernel_power_41_is_not_a_psu_verdict() -> None:
    info = events_db.describe("Microsoft-Windows-Kernel-Power", 41, "kernel_power_41")
    assert "не доказательство неисправности блока питания" in info.note


def test_unknown_id_falls_back_to_provider_then_group() -> None:
    by_provider = events_db.describe("nvlddmkm", 999, "gpu_driver")
    assert "NVIDIA" in by_provider.title
    by_group = events_db.describe("SomeVendorDriver", 1, "storage")
    assert by_group.title and by_group.significance


def test_group_titles_cover_spec_groups() -> None:
    for group in (
        "whea",
        "bugcheck",
        "kernel_power_41",
        "disk",
        "storage",
        "gpu_driver",
        "unexpected_shutdown",
    ):
        assert events_db.group_title(group), group
