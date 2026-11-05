"""Интерпретация SMART (этап 45 v2.1): нормализованный статус атрибута и поля NVMe с
расшифровкой; тексты и значимость — в hwcheck/data/smart_attributes.yaml."""

import pytest

from hwcheck.knowledge import smart
from hwcheck.models import SmartAttribute


@pytest.mark.parametrize(
    ("attribute", "code"),
    [
        (SmartAttribute(id=5, value=100, worst=100, threshold=10, raw=0), "ok"),
        (SmartAttribute(id=5, value=9, worst=9, threshold=10, raw=900), "failing"),
        (
            SmartAttribute(
                id=5, value=100, worst=5, threshold=10, raw=0, when_failed="In_the_past"
            ),
            "failed_in_past",
        ),
        (SmartAttribute(id=5, value=100, worst=100, threshold=None, raw=0), "no_threshold"),
        (
            SmartAttribute(id=1, value=100, worst=100, threshold=0, raw=5),
            "no_limit",
        ),  # порог 0 — у атрибута нет порога отказа, это счётчик
    ],
)
def test_attribute_status(attribute: SmartAttribute, code: str) -> None:
    assert smart.attribute_status(attribute)[0] == code


def test_key_attribute_raw_nonzero_is_explained() -> None:
    text = smart.interpret_attribute(
        SmartAttribute(id=197, value=100, worst=100, threshold=0, raw=8)
    )
    assert "8" in text and "переназначения" in text.lower()
    # Порог 0 не значит «в норме»: 8 нестабильных секторов — не норма (этап 50 v2.1).
    assert "в норме" not in text and "порога отказа нет" in text


def test_problem_raw_is_not_called_normal() -> None:
    """Нормализованное значение выше порога, но Raw ключевого атрибута ненулевой."""
    text = smart.interpret_attribute(
        SmartAttribute(id=5, value=154, worst=154, threshold=140, raw=184)
    )
    assert "в норме" not in text and "184" in text


def test_vendor_specific_raw_is_not_a_diagnosis() -> None:
    """Raw_Read_Error_Rate у Seagate огромный в норме — без диагноза по Raw."""
    text = smart.interpret_attribute(
        SmartAttribute(
            id=1, name="Raw_Read_Error_Rate", value=80, worst=64, threshold=44, raw=10**8
        )
    )
    assert "разное" in text and "норм" in text.lower()


def test_every_key_attribute_has_text() -> None:
    for attribute_id in (5, 9, 10, 12, 187, 188, 190, 194, 196, 197, 198, 199):
        assert smart.ata_info(attribute_id) is not None, attribute_id


def test_nvme_rows_format_and_interpret() -> None:
    log = {
        "critical_warning": 0,
        "data_units_read": 2_000_000,
        "data_units_written": 91_033_445,
        "available_spare": 100,
        "available_spare_threshold": 10,
        "controller_busy_time": 1500,
        "num_err_log_entries": 3,
        "media_errors": 0,
        "mystery_field": 7,
    }
    rows = {row.key: row for row in smart.nvme_rows(log)}
    assert rows["critical_warning"].value == "0 (нет предупреждений)"
    assert rows["data_units_read"].value == "1,0 ТБ (2000000 единиц по 512 000 байт)"
    assert rows["data_units_written"].value.startswith("46,6 ТБ")
    assert rows["controller_busy_time"].value == "1500 мин"
    assert "требует интерпретации" in rows["num_err_log_entries"].note
    assert rows["mystery_field"].value == "7"  # неизвестное поле не прячем


def test_nvme_critical_warning_bits() -> None:
    rows = {row.key: row for row in smart.nvme_rows({"critical_warning": 0x5})}
    value = rows["critical_warning"].value
    assert "резерв" in value and "надёжность" in value
