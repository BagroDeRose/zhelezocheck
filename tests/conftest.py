"""Общая настройка тестов.

- Окна Qt в тестах не показываются (платформа offscreen).
- Временные папки тестов — в .tmp/ внутри проекта (не в профиле пользователя).
"""

import os
import tempfile
from pathlib import Path

# Временные файлы тестов — только внутри проекта (.tmp/, см. SPEC 1.1, правило рабочих папок).
_TMP = Path(__file__).resolve().parent.parent / ".tmp"
(_TMP / "temp").mkdir(parents=True, exist_ok=True)
# tempfile в программе и тестах тоже пишет внутрь проекта.
os.environ["TEMP"] = os.environ["TMP"] = str(_TMP / "temp")
tempfile.tempdir = None

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_DISABLE_DISK_CACHE", "1")  # как в программе: без кэша на диске
os.environ.setdefault("QT_DISABLE_SHADER_DISK_CACHE", "1")
