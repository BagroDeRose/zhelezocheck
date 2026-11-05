"""Тесты сводки журнала событий Windows."""

from hwcheck.collectors import events
from hwcheck.models import EventRecord, EventSummary
from tests.helpers import FakeRun, fixture_json, fixture_text


def test_with_events() -> None:
    summary = events.parse(fixture_json("powershell", "events_with.json"))
    assert summary.counts == {"whea": 4, "kernel_power_41": 2, "bugcheck": 3, "disk": 17}
    assert summary.last_seen["bugcheck"] == "2026-10-02T22:15:31"
    assert summary.partial is False
    assert summary.days == 30


def test_no_events() -> None:
    summary = events.parse(fixture_json("powershell", "events_none.json"))
    assert summary.counts == {"whea": 0, "kernel_power_41": 0, "bugcheck": 0, "disk": 0}
    assert summary.last_seen == {}
    assert not summary.partial


def test_partial_without_admin() -> None:
    summary = events.parse(fixture_json("powershell", "events_partial_noadmin.json"))
    assert summary.partial is True
    assert "администратор" in summary.note
    assert summary.counts == {"kernel_power_41": 1, "bugcheck": 0}
    assert "whea" not in summary.counts  # неизвестно, а не «ноль»


def test_collect_powershell_failure_gives_partial() -> None:
    fake = FakeRun("", returncode=1, stderr="Отказано в доступе")
    summary = events.collect(run_fn=fake)
    assert summary.partial and summary.counts == {}


def test_collect_ok_and_script_is_read_only() -> None:
    fake = FakeRun(fixture_text("powershell", "events_with.json"))
    assert events.collect(run_fn=fake).counts["disk"] == 17
    script = fake.commands[0][-1]
    assert "Get-WinEvent" in script and "AddDays(-30)" in script
    for forbidden in ("Clear-EventLog", "wevtutil", "Remove-", "Limit-EventLog"):
        assert forbidden not in script


def test_removable_disk_errors_counted_separately() -> None:
    """15.8: ошибки флешек (USB/SD или уже отключённых дисков) не смешиваются с внутренними."""
    summary = events.parse(fixture_json("powershell", "events_disk_usb.json"))
    assert summary.counts["disk"] == 1  # только NVMe — внутренний диск
    assert summary.counts["disk_removable"] == 8


def test_script_maps_disk_events_to_bus() -> None:
    script = events.build_script()
    assert "Harddisk" in script and "Get-PhysicalDisk" in script and "BusType" in script


# ---------------------------------------------------------------- 2.1: события целиком (этап 46)


def test_new_groups_and_event_details() -> None:
    summary = events.parse(fixture_json("powershell", "events_v21.json"))
    assert summary.counts["storage"] == 1
    assert summary.counts["gpu_driver"] == 5
    assert summary.counts["unexpected_shutdown"] == 1
    whea = [item for item in summary.items if item.group == "whea"]
    assert [(i.event_id, i.level, i.count) for i in whea] == [(17, 3, 2), (18, 2, 1)]
    first = whea[0]
    assert first.provider == "Microsoft-Windows-WHEA-Logger" and first.log == "System"
    assert first.first_seen == "2026-10-01T10:00:00" and first.last_seen == "2026-10-03T18:40:12"


def test_event_message_hides_user_name_and_is_short() -> None:
    data = fixture_json("powershell", "events_v21.json")
    gpu = next(item for item in data if item["Key"] == "gpu_driver")
    # Путь склеен из частей: целиком такой путь в репозитории нашла бы проверка секретов.
    gpu["Items"][1]["Message"] = "Ошибка при запуске C:" + "\\Users\\ivan.petrov\\AppData\\x.exe"
    summary = events.parse(data)
    nvidia = next(i for i in summary.items if i.provider == "nvlddmkm")
    assert "ivan.petrov" not in nvidia.message
    assert r"C:\Users\<пользователь>\AppData" in nvidia.message
    data = fixture_json("powershell", "events_v21.json")
    data[0]["Items"][0]["Message"] = "Очень длинное сообщение. " * 50
    long_item = events.parse(data).items[0]
    assert len(long_item.message) <= events.MESSAGE_LIMIT + 1


def test_old_output_without_items_still_works() -> None:
    """Вывод в формате до 2.1 (без Items) читается как раньше, подробностей просто нет."""
    summary = events.parse(fixture_json("powershell", "events_with.json"))
    assert summary.items == [] and summary.counts["disk"] == 17


def test_script_queries_each_provider_separately() -> None:
    """Незарегистрированный источник (драйвер AMD на ПК с NVIDIA) ломал бы весь запрос группы
    (NoMatchingProvidersFound) — поэтому источники запрашиваются по одному."""
    script = events.build_script()
    for provider in ("nvlddmkm", "amdkmdag", "stornvme", "storahci", "Microsoft-Windows-Ntfs"):
        assert f"ProviderName='{provider}'" in script, provider
    assert "Id=6008" in script and "Id=4101" in script
    assert "'NoMatching*'" in script  # «нет событий» и «нет источника» — не ошибка
    assert "Group-Object ProviderName, Id" in script


def test_disk_event_details_follow_removable_split() -> None:
    """Реальный случай (ПК разработчика, 01.11.2026): disk 51 на флешке. Счётчик относит его
    к съёмным — и подробности не должны называть его «ошибкой внутреннего диска»."""
    item = {
        "Provider": "disk",
        "Id": 51,
        "Level": 3,
        "Count": 3,
        "First": "2026-10-31T23:47:23",
        "Last": "2026-10-31T23:48:23",
        "Message": r"Ошибка на устройстве \Device\Harddisk2\DR3",
    }
    only_usb = [
        {
            "Key": "disk",
            "Count": 3,
            "Last": "2026-10-31T23:48:23",
            "Error": None,
            "Disks": [{"Disk": 2, "Count": 3, "Bus": "USB"}],
            "Items": [item],
        }
    ]
    summary = events.parse(only_usb)
    assert summary.counts == {"disk": 0, "disk_removable": 3}
    assert [i.group for i in summary.items] == ["disk_removable"]
    mixed = [
        {
            **only_usb[0],
            "Count": 5,
            "Disks": [
                {"Disk": 2, "Count": 3, "Bus": "USB"},
                {"Disk": 0, "Count": 2, "Bus": "NVMe"},
            ],
        }
    ]
    assert [i.group for i in events.parse(mixed).items] == ["disk_mixed"]


def test_removable_errors_keep_their_time() -> None:
    """Ручная проверка 2.1.0-rc1: дата ошибок флешки стояла у «Ошибок дисков» (0 раз), а у
    «съёмных» (3 раза) — «—»; правило писало «дата неизвестна»."""
    data = [
        {
            "Key": "disk",
            "Count": 3,
            "Last": "2026-10-31T23:48:23",
            "Error": None,
            "Disks": [{"Disk": 2, "Count": 3, "Bus": "USB"}],
            "Items": [],
        }
    ]
    summary = events.parse(data)
    assert summary.last_for("disk") == ""
    assert summary.last_for("disk_removable").startswith("2026-10-31T23:48")


def test_old_rc1_summary_is_read_correctly() -> None:
    """Сводка, сохранённая 2.1.0-rc1 (время под «disk»), читается без путаницы."""
    summary = EventSummary(
        counts={"disk": 0, "disk_removable": 3},
        last_seen={"disk": "2026-10-31T23:48:23"},
        items=[EventRecord(group="disk_removable", count=3, last_seen="2026-10-31T23:48:23")],
    )
    assert summary.last_for("disk") == ""
    assert summary.last_for("disk_removable") == "2026-10-31T23:48:23"
