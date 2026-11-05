"""Фундамент схемы данных 2.1 (этап 41 v2.1): метаданные параметра, временные ряды,
версия схемы и чтение старых проверок без потерь."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from hwcheck import schema
from hwcheck.models import (
    SCHEMA_VERSION,
    Availability,
    CheckSession,
    CheckState,
    HardwareSnapshot,
    Param,
    SensorSample,
    SeriesMarker,
    TestResult,
    TestStatus,
    check_state,
)
from hwcheck.storage.history import History

OLD_SESSION = Path(__file__).parent / "fixtures" / "sessions" / "session_2_0_1.json"


# ---------------------------------------------------------------- старые проверки


def test_old_session_opens_and_is_upgraded() -> None:
    """Проверка, сохранённая версией 2.0.1 (без schema_version), открывается целиком."""
    raw = json.loads(OLD_SESSION.read_text(encoding="utf-8"))
    assert "schema_version" not in raw
    session = schema.load_session(OLD_SESSION.read_text(encoding="utf-8"))
    assert session.schema_version == SCHEMA_VERSION
    assert session.snapshot.schema_version == SCHEMA_VERSION
    # Старые данные не потерялись.
    assert len(session.results) == len(raw["results"])
    assert sum(len(r.samples) for r in session.results) == sum(
        len(r["samples"]) for r in raw["results"]
    )
    assert session.verdict is not None and session.verdict.findings
    # Новые поля — пустые по умолчанию, а не выдуманные.
    assert session.snapshot.params == {}
    assert all(r.markers == [] and r.started_at == "" for r in session.results)


def test_upgrade_does_not_change_the_input() -> None:
    raw = json.loads(OLD_SESSION.read_text(encoding="utf-8"))
    before = json.dumps(raw, sort_keys=True)
    upgraded = schema.upgrade_session_dict(raw)
    assert json.dumps(raw, sort_keys=True) == before  # исходный словарь не тронут
    assert upgraded["schema_version"] == SCHEMA_VERSION
    assert upgraded["migrated_from"] == 1


def test_future_version_is_read_best_effort() -> None:
    """Проверка из будущей версии программы: читаем что понимаем, версию не занижаем."""
    raw = json.loads(OLD_SESSION.read_text(encoding="utf-8"))
    raw["schema_version"] = SCHEMA_VERSION + 5
    raw["unknown_future_field"] = {"x": 1}
    session = schema.load_session(json.dumps(raw))
    assert session.schema_version == SCHEMA_VERSION + 5
    assert session.results


@pytest.mark.parametrize("text", ["", "не json", "[1, 2]", '{"schema_version": "два"}'])
def test_broken_session_raises_clear_error(text: str) -> None:
    with pytest.raises(schema.SchemaError):
        schema.load_session(text)


def test_history_keeps_rows_when_one_is_broken(tmp_path: Path) -> None:
    """Ошибка чтения одной записи истории не теряет и не ломает остальные."""
    history = History(tmp_path / "history.sqlite")
    good = schema.load_session(OLD_SESSION.read_text(encoding="utf-8"))
    good.id = "good"
    history.save(good)
    with sqlite3.connect(tmp_path / "history.sqlite") as db:
        db.execute(
            "INSERT INTO checks (id, created_at, mode, decision, computer, summary, "
            "report_path, session_json) VALUES ('bad', '2026-10-01', 'quick', 'buy', 'ПК', '', "
            "NULL, '{испорчено')"
        )
    assert {entry.id for entry in history.list()} == {"good", "bad"}
    assert history.load_session("bad") is None
    loaded = history.load_session("good")
    assert loaded is not None and loaded.schema_version == SCHEMA_VERSION
    with sqlite3.connect(tmp_path / "history.sqlite") as db:
        (text,) = db.execute("SELECT session_json FROM checks WHERE id = 'bad'").fetchone()
    assert text == "{испорчено"  # испорченная запись не удалена и не перезаписана


def test_old_history_row_opens(tmp_path: Path) -> None:
    """Запись истории, сохранённая версией 2.0.1, открывается и получает новую схему."""
    history = History(tmp_path / "history.sqlite")
    raw = OLD_SESSION.read_text(encoding="utf-8")
    with sqlite3.connect(tmp_path / "history.sqlite") as db:
        db.execute(
            "INSERT INTO checks (id, created_at, mode, decision, computer, summary, "
            "report_path, session_json) VALUES ('old', '2026-10-01', 'quick', 'negotiate', "
            "'ПК', '', NULL, ?)",
            (raw,),
        )
    session = history.load_session("old")
    assert session is not None and session.schema_version == SCHEMA_VERSION
    assert len(session.results) == len(json.loads(raw)["results"])


# ---------------------------------------------------------------- новые поля


def test_param_round_trip_with_status() -> None:
    snapshot = HardwareSnapshot()
    snapshot.params["cpu.l3_cache"] = Param(
        value=9216, unit="КБ", source="Win32_Processor", obtained_at="2026-11-05T10:00:00"
    )
    snapshot.params["cpu.package_temp"] = Param(
        status=Availability.UNAVAILABLE,
        source="—",
        reason="Нужен драйвер ядра; программа драйверы не устанавливает.",
    )
    restored = HardwareSnapshot.from_json(snapshot.to_json())
    assert restored.params["cpu.l3_cache"].value == 9216
    assert restored.params["cpu.l3_cache"].status is Availability.AVAILABLE
    unavailable = restored.params["cpu.package_temp"]
    assert unavailable.status is Availability.UNAVAILABLE and unavailable.value is None
    assert "драйвер" in unavailable.reason


def test_unavailable_param_never_has_a_value() -> None:
    """Принцип честности: у недоступного параметра нет значения (никаких подставленных нулей)."""
    with pytest.raises(ValueError):
        Param(value=0, status=Availability.UNAVAILABLE, reason="нет датчика")
    with pytest.raises(ValueError):
        Param(status=Availability.UNSUPPORTED)  # причина обязательна


def test_markers_and_start_time_round_trip() -> None:
    result = TestResult(name="gpu_load", started_at="2026-11-05T10:00:00")
    result.markers.append(SeriesMarker(elapsed_seconds=0.0, kind="start", text="Нагрузка"))
    result.markers.append(
        SeriesMarker(elapsed_seconds=42.5, kind="interrupt", text="Остановлено пользователем")
    )
    restored = TestResult.from_json(result.to_json())
    assert restored.started_at == "2026-11-05T10:00:00"
    assert [m.kind for m in restored.markers] == ["start", "interrupt"]


def test_new_session_carries_schema_version() -> None:
    data = json.loads(CheckSession().to_json())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["snapshot"]["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------- временные ряды


def test_series_points_from_samples() -> None:
    result = TestResult(name="gpu_load", started_at="2026-11-05T10:00:00")
    result.samples = [
        SensorSample(t=0.0, component="gpu0", values={"temp_c": 40.0, "fan_pct": None}),
        SensorSample(t=1.0, component="gpu0", values={"temp_c": 41.0, "fan_pct": 30.0}),
    ]
    points = schema.series_points(result)
    temps = [p for p in points if p.sensor_id == "gpu0.temperature"]
    assert [p.value for p in temps] == [40.0, 41.0]
    assert temps[1].elapsed_seconds == 1.0
    assert temps[1].timestamp == "2026-11-05T10:00:01"
    assert temps[0].unit == "°C" and temps[0].source == "nvidia-smi"
    assert all(p.quality == "measured" for p in points)
    # Пропуск датчика — не точка с нулём, а отсутствие точки.
    fans = [p for p in points if p.sensor_id == "gpu0.fan"]
    assert [p.value for p in fans] == [30.0]


def test_series_points_skip_non_numbers() -> None:
    """NaN, бесконечность и не-числа от датчика — не точки ряда (этап 50 v2.1)."""
    result = TestResult(name="gpu_load")
    bad: dict[str, Any] = {"temp_c": float("nan"), "fan_pct": float("inf"), "power_w": "45"}
    result.samples = [
        SensorSample(t=0.0, component="gpu0", values=bad),
        SensorSample(t=1.0, component="gpu0", values={"temp_c": 50.0, "util_pct": True}),
    ]
    points = schema.series_points(result)
    assert [(p.sensor_id, p.value) for p in points] == [("gpu0.temperature", 50.0)]
    stats = schema.series_stats(result, "gpu0.temperature")
    assert stats is not None and stats.count == 1 and stats.maximum == 50.0


def test_series_without_start_time_has_no_invented_timestamp() -> None:
    """Старые проверки не знают часового времени начала теста — не выдумываем его."""
    result = TestResult(name="cpu_load")
    result.samples = [SensorSample(t=2.0, component="cpu", values={"clock_mhz": 3900.0})]
    (point,) = schema.series_points(result)
    assert point.timestamp == "" and point.elapsed_seconds == 2.0
    assert point.sensor_id == "cpu.clock" and point.unit == "МГц"


def test_unknown_sensor_keeps_raw_name() -> None:
    result = TestResult(name="x")
    result.samples = [SensorSample(t=0.0, component="gpu0", values={"new_metric": 5.0})]
    (point,) = schema.series_points(result)
    assert point.sensor_id == "gpu0.new_metric" and point.unit == ""


def test_sensor_source_override() -> None:
    """Источник датчика может отличаться от умолчания (например, тепловая зона через perf)."""
    result = TestResult(name="cpu_load", sensor_sources={"cpu.zone_temp": "perf:ThermalZone"})
    result.samples = [SensorSample(t=0.0, component="cpu", values={"zone_temp_c": 45.0})]
    (point,) = schema.series_points(result)
    assert point.source == "perf:ThermalZone"


# ---------------------------------------------------------------- четыре состояния теста


@pytest.mark.parametrize(
    ("result", "state"),
    [
        (TestResult(status=TestStatus.PASSED), CheckState.PASSED),
        (TestResult(status=TestStatus.FAILED), CheckState.PROBLEMS),
        (TestResult(status=TestStatus.WARNING), CheckState.PROBLEMS),
        (TestResult(status=TestStatus.SKIPPED), CheckState.NOT_CHECKED),
        (
            TestResult(
                status=TestStatus.SKIPPED,
                notes=["Не запускался: проверка остановлена пользователем."],
            ),
            CheckState.NOT_CHECKED,
        ),
        (
            TestResult(status=TestStatus.SKIPPED, metrics={"cancelled": True}),
            CheckState.INTERRUPTED,
        ),
        (
            TestResult(status=TestStatus.SKIPPED, notes=["Тест остановлен пользователем."]),
            CheckState.INTERRUPTED,
        ),
        (
            TestResult(status=TestStatus.FAILED, metrics={"emergency_stop": True}),
            CheckState.INTERRUPTED,
        ),
        (TestResult(status=TestStatus.ERROR), CheckState.INTERRUPTED),
    ],
)
def test_check_state(result: TestResult, state: CheckState) -> None:
    """«Не проверено», «ошибок нет», «обнаружены проблемы», «прервана» — не путаются."""
    assert check_state(result) is state


def test_not_checked_is_never_success() -> None:
    for status in TestStatus:
        if status is not TestStatus.PASSED:
            assert check_state(TestResult(status=status)) is not CheckState.PASSED
