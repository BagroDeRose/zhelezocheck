"""Тесты сборщика накопителей: smartctl (основной путь) и средства Windows (запасной путь)."""

import json
from typing import Any

from hwcheck.collectors import disks
from hwcheck.platform.runner import RunResult
from tests.helpers import fixture_json, fixture_text


def _smart(name: str) -> Any:
    return fixture_json("smartctl", name)


def test_nvme_healthy() -> None:
    disk = disks.parse_smartctl(_smart("nvme_healthy.json"))
    assert disk.model == "Samsung SSD 980 1TB"
    assert disk.media_type == "ssd" and disk.bus_type == "nvme"
    assert round(disk.size_gb) == 1000
    assert disk.smart is not None
    assert disk.smart.power_on_hours == 3120
    assert disk.smart.wear_percent == 4.0
    assert disk.smart.media_errors == 0
    assert disk.smart.temperature_c == 38.0
    assert disk.smart.health_passed is True
    assert disk.smart.source == "smartctl"


def test_sata_ssd_healthy() -> None:
    disk = disks.parse_smartctl(_smart("sata_ssd_healthy.json"))
    assert disk.media_type == "ssd" and disk.bus_type == "sata"
    assert disk.smart is not None
    assert disk.smart.reallocated_sectors == 0
    assert disk.smart.wear_percent == 7.0  # Wear_Leveling_Count = 93 → израсходовано 7%
    assert disk.smart.crc_errors == 0
    assert disk.smart.power_on_hours == 15402


def test_hdd_reallocated() -> None:
    disk = disks.parse_smartctl(_smart("hdd_reallocated.json"))
    assert disk.media_type == "hdd"
    smart = disk.smart
    assert smart is not None
    assert smart.reallocated_sectors == 184
    assert smart.pending_sectors == 24
    assert smart.uncorrectable_sectors == 12
    assert smart.crc_errors == 3
    assert smart.power_on_hours == 46800
    assert smart.wear_percent is None
    # Ненулевой код smartctl (биты 6–7) — это не ошибка чтения, данные есть.
    assert smart.health_passed is True


def test_ssd_worn() -> None:
    disk = disks.parse_smartctl(_smart("ssd_worn.json"))
    assert disk.smart is not None
    assert disk.smart.wear_percent == 93.0


def test_nvme_written_spare_and_unsafe_shutdowns() -> None:
    """NVMe: сколько записано (единица — 512 000 байт), резерв ячеек и аварийные выключения."""
    smart = disks.parse_smartctl(_smart("real_ardor_nvme.json")).smart
    assert smart is not None
    assert smart.data_written_tb == 46.6  # 91 033 445 × 512 000 байт
    assert smart.available_spare_pct == 100 and smart.available_spare_threshold_pct == 1
    assert smart.unsafe_shutdowns == 34
    healthy = disks.parse_smartctl(_smart("nvme_healthy.json")).smart
    assert healthy is not None and healthy.data_written_tb == 15.4


def test_sata_written_not_guessed() -> None:
    """У SATA атрибут 241 в единицах производителя — «записано» не выдумываем."""
    for name in ("sata_ssd_healthy.json", "ssd_worn.json", "hdd_reallocated.json"):
        smart = disks.parse_smartctl(_smart(name)).smart
        assert smart is not None and smart.data_written_tb is None, name


def test_usb_without_smart() -> None:
    disk = disks.parse_smartctl(_smart("usb_no_smart.json"))
    assert disk.smart is None
    assert "S.M.A.R.T." in disk.note
    assert disk.device == "/dev/sdc"


def test_scan_lists_devices() -> None:
    devices = disks.parse_scan(_smart("scan_open.json"))
    assert [d["name"] for d in devices] == ["/dev/sda", "/dev/sdb", "/dev/nvme0", "/dev/sdc"]
    assert devices[0]["type"] == "sat"


class ScriptedRun:
    """Подмена запуска: отвечает по аргументам команды заранее заданным выводом."""

    def __init__(self, responses: dict[str, RunResult]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], timeout: float = 60.0, **kwargs: Any) -> RunResult:
        self.commands.append(cmd)
        for key, result in self.responses.items():
            if key in " ".join(cmd):
                return result
        return RunResult(None, "", "not found", 0.0, not_found=True)


def _ok(stdout: str, code: int = 0) -> RunResult:
    return RunResult(code, stdout, "", 0.1)


def test_collect_via_smartctl() -> None:
    fake = ScriptedRun(
        {
            "--scan-open": _ok(fixture_text("smartctl", "scan_open.json")),
            "/dev/sda": _ok(fixture_text("smartctl", "sata_ssd_healthy.json")),
            "/dev/sdb": _ok(fixture_text("smartctl", "hdd_reallocated.json"), code=192),
            "/dev/nvme0": _ok(fixture_text("smartctl", "nvme_healthy.json")),
            "/dev/sdc": _ok(fixture_text("smartctl", "usb_no_smart.json"), code=2),
        }
    )
    result = disks.collect(run_fn=fake, smartctl="smartctl.exe")
    assert [d.model for d in result][:3] == [
        "Samsung SSD 860 EVO 500GB",
        "WDC WD10EZEX-08WN4A0",
        "Samsung SSD 980 1TB",
    ]
    assert result[3].smart is None
    # Команда передаёт тип устройства из результатов сканирования.
    assert any(cmd[-3:] == ["-d", "sat", "/dev/sda"] for cmd in fake.commands)
    # Ни одна команда smartctl не запускает тесты/запись.
    for cmd in fake.commands:
        assert "-t" not in cmd and "--test" not in " ".join(cmd) and "-s" not in cmd


def test_fallback_when_no_smartctl() -> None:
    fake = ScriptedRun(
        {"Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_admin.json"))}
    )
    result = disks.collect(run_fn=fake, smartctl=None)
    ssd, hdd, usb = result
    assert ssd.media_type == "ssd" and ssd.bus_type == "sata"
    assert ssd.smart is not None and ssd.smart.wear_percent == 93.0
    assert ssd.smart.source == "windows"
    assert hdd.media_type == "hdd"
    assert hdd.smart is not None
    assert hdd.smart.health_passed is False  # HealthStatus = 1 (Warning)
    assert hdd.smart.uncorrectable_sectors == 17
    assert usb.bus_type == "usb"
    assert usb.smart is not None and usb.smart.power_on_hours is None


def test_fallback_without_admin_gives_partial() -> None:
    fake = ScriptedRun(
        {"Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_noadmin.json"))}
    )
    nvme, hdd = disks.collect(run_fn=fake, smartctl=None)
    assert nvme.bus_type == "nvme"
    assert nvme.smart is not None
    assert nvme.smart.health_passed is True
    assert nvme.smart.power_on_hours is None
    assert "администратор" in nvme.note


def test_fallback_when_smartctl_finds_nothing() -> None:
    empty_scan = json.dumps({"devices": []})
    fake = ScriptedRun(
        {
            "--scan-open": _ok(empty_scan),
            "Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_noadmin.json")),
        }
    )
    assert len(disks.collect(run_fn=fake, smartctl="smartctl.exe")) == 2


def test_smartctl_cannot_open_disks_falls_back_to_windows() -> None:
    # smartctl видит диски, но не может их открыть (бывает без прав администратора).
    fake = ScriptedRun(
        {
            "--scan-open": _ok(fixture_text("smartctl", "real_scan_open_noadmin.json")),
            "/dev/sd": _ok(fixture_text("smartctl", "open_failed.json"), code=2),
            "Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_noadmin.json")),
        }
    )
    result = disks.collect(run_fn=fake, smartctl="smartctl.exe")
    assert [d.model for d in result] == [
        "ARDOR GAMING m.2 NVME 256Gb AL1282",
        "WDC WD10EZEX-22MFCA0",
    ]
    assert all(d.smart is not None and d.smart.source == "windows" for d in result)


def test_real_smartctl_without_admin_enriched_from_windows() -> None:
    # Реальный вывод smartctl 7.5 (машина разработчика, без прав администратора):
    # у HDD нет объёма и скорости вращения — берём их из Windows.
    fake = ScriptedRun(
        {
            "--scan-open": _ok(fixture_text("smartctl", "real_scan_open_noadmin.json")),
            "/dev/sda": _ok(fixture_text("smartctl", "real_wd_hdd_ata.json"), code=4),
            "/dev/sdb": _ok(fixture_text("smartctl", "real_ardor_nvme.json")),
            "Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_noadmin.json")),
        }
    )
    hdd, nvme = disks.collect(run_fn=fake, smartctl="smartctl.exe")
    assert hdd.model == "WDC WD10EZEX-22MFCA0"
    assert hdd.size_gb == 1000.2 and hdd.media_type == "hdd" and hdd.bus_type == "sata"
    assert hdd.smart is not None and hdd.smart.reallocated_sectors == 0
    assert hdd.smart.source == "smartctl"
    assert nvme.media_type == "ssd" and nvme.smart is not None and nvme.smart.wear_percent == 16.0


def test_enrich_asks_windows_only_for_size_and_type() -> None:
    """Дополнение сведений smartctl — без счётчиков надёжности и с коротким ожиданием.

    С правами администратора `Get-StorageReliabilityCounter` по-настоящему опрашивает каждое
    устройство и на USB-флешке висел все 60 с (журнал владельца, 01.11.2026): сводка ждала
    минуту. Для дополнения нужны только объём и тип — их даёт `Get-PhysicalDisk`."""
    calls: list[tuple[str, float]] = []
    scripted = ScriptedRun(
        {
            "--scan-open": _ok(fixture_text("smartctl", "real_scan_open_noadmin.json")),
            "/dev/sda": _ok(fixture_text("smartctl", "real_wd_hdd_ata.json"), code=4),
            "/dev/sdb": _ok(fixture_text("smartctl", "real_ardor_nvme.json")),
            "Get-PhysicalDisk": _ok(fixture_text("powershell", "disks_fallback_noadmin.json")),
        }
    )

    def recording(cmd: list[str], timeout: float = 60.0, **kwargs: Any) -> RunResult:
        if "Get-PhysicalDisk" in " ".join(cmd):
            calls.append((" ".join(cmd), timeout))
        return scripted(cmd, timeout, **kwargs)

    hdd, _nvme = disks.collect(run_fn=recording, smartctl="smartctl.exe")
    assert hdd.size_gb == 1000.2  # объём по-прежнему берётся из Windows
    assert len(calls) == 1
    command, timeout = calls[0]
    assert "Get-StorageReliabilityCounter" not in command
    assert timeout <= disks.ENRICH_TIMEOUT_S <= 20


def test_fallback_reliability_skips_usb() -> None:
    """Полный запасной путь (smartctl нет): счётчики надёжности USB-устройств не спрашиваем —
    на них запрос может зависнуть, а S.M.A.R.T. флешки всё равно не отдают."""
    assert "BusType -ne 7" in disks.FALLBACK_SCRIPT


# ---------------------------------------------------------------- 15.7 устройство без названия


def test_smartctl_device_without_model_gets_readable_name() -> None:
    from hwcheck.collectors.disks import UNKNOWN_DISK_MODEL, collect_smartctl
    from hwcheck.platform.runner import RunResult

    def fake_run(args: list[str], **_kwargs: object) -> RunResult:
        if "--scan-open" in args:
            out = '{"devices": [{"name": "/dev/sdb", "type": "scsi"}]}'
        else:
            out = '{"smartctl": {"exit_status": 4}, "device": {}}'
        return RunResult(returncode=0, stdout=out, stderr="", duration=0.1)

    disks = collect_smartctl(fake_run, "smartctl")
    assert disks[0].device == "/dev/sdb"
    assert disks[0].model == f"{UNKNOWN_DISK_MODEL} (/dev/sdb)"


def test_smartctl_version_is_recorded() -> None:
    """Паспорт проверки (2.1): версия реально использованной утилиты."""
    smart = disks.parse_smartctl(_smart("real_ardor_nvme.json")).smart
    assert smart is not None and smart.tool_version == "7.5"


# ---------------------------------------------------------------- 2.1: полный SMART (этап 45)


def test_all_ata_attributes_are_kept() -> None:
    disk = disks.parse_smartctl(_smart("sata_ssd_healthy.json"))
    smart = disk.smart
    assert smart is not None and len(smart.attributes) == 14
    realloc = next(a for a in smart.attributes if a.id == 5)
    assert realloc.name == "Reallocated_Sector_Ct"
    assert (realloc.value, realloc.worst, realloc.threshold, realloc.raw) == (100, 100, 10, 0)
    assert disk.firmware == "RVT04B6Q" and disk.interface_speed == "6.0 Gb/s"


def test_real_hdd_without_admin_has_no_invented_thresholds() -> None:
    """smartctl без прав администратора не прочитал пороги — Threshold None, а не 0."""
    disk = disks.parse_smartctl(_smart("real_wd_hdd_ata.json"))
    smart = disk.smart
    assert smart is not None and len(smart.attributes) == 17
    assert all(a.threshold is None for a in smart.attributes)
    assert smart.self_test == "completed without error"
    assert disk.serial_number == "0000000000"  # в фикстуре обезличен


def test_full_nvme_health_log_is_kept() -> None:
    smart = disks.parse_smartctl(_smart("real_ardor_nvme.json")).smart
    assert smart is not None
    for key in (
        "data_units_read",
        "host_reads",
        "controller_busy_time",
        "num_err_log_entries",
        "critical_warning",
        "warning_temp_time",
        "critical_comp_time",
    ):
        assert key in smart.nvme_log, key
    assert smart.attributes == []
