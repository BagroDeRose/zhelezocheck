"""Скрытие идентификаторов при экспорте отчёта (SPEC_V2_1, этап 48; MVP-спека, 8.4 и 10).

Отчёт часто отдают другим людям, а серийные номера и имя компьютера — данные продавца.
Поэтому при сохранении HTML, PDF и JSON (по умолчанию) они заменяются на «скрыто»:
- имя компьютера;
- серийные номера планок памяти и накопителей;
- имя продавца из объявления.

Скрытие делается над копией: история проверок хранит настоящие данные, а отчёт и его
SHA-256 считаются по тому, что в нём реально показано. Пустое поле и серийный номер-заглушка
(«00000000») остаются как есть — там нечего было скрывать.
"""

from __future__ import annotations

from hwcheck.models import CheckSession
from hwcheck.ui.summary_cards import is_placeholder_serial

HIDDEN = "скрыто"


def _hide(value: str) -> str:
    return HIDDEN if value.strip() else value


def _hide_serial(value: str) -> str:
    """Серийный номер-заглушка («00000000») ничего не выдаёт — его не скрываем, чтобы отчёт
    честно показал «Не указано производителем» (ручная проверка 2.1.0-rc2, пункт 18)."""
    return value if is_placeholder_serial(value) else _hide(value)


def mask_identifiers(session: CheckSession) -> CheckSession:
    """Копия проверки без имени компьютера, серийных номеров и имени продавца."""
    masked = CheckSession.from_dict(session.to_dict())
    snapshot = masked.snapshot
    if snapshot.system is not None:
        snapshot.system.computer_name = _hide(snapshot.system.computer_name)
    if snapshot.memory is not None:
        for module in snapshot.memory.modules:
            module.serial_number = _hide_serial(module.serial_number)
    for disk in snapshot.disks:
        disk.serial_number = _hide_serial(disk.serial_number)
    if masked.listing is not None:
        masked.listing.seller_name = _hide(masked.listing.seller_name)
    return masked
