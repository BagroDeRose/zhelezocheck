# Сборка портативной версии ЖелезоЧек (PyInstaller, onedir).
# Запуск — через scripts\build.ps1 (он же докладывает сторонние программы и лицензии).
# -*- mode: python -*-
import os

from PyInstaller.utils.hooks import collect_data_files

APP_NAME = "ЖелезоЧек"
HERE = SPECPATH  # noqa: F821 — папка packaging/, переменную задаёт PyInstaller
ROOT = os.path.dirname(HERE)

# Свойства exe (вкладка «Подробно»): правообладатель — только псевдоним (SPEC 1.5, 34.7).
import re  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, HERE)
from exe_metadata import version_info  # noqa: E402

_init = open(os.path.join(ROOT, "hwcheck", "__init__.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'__version__ = "([^"]+)"', _init).group(1)

datas = collect_data_files("hwcheck")  # справочники, правила, сценарии, шаблон отчёта, иконка

a = Analysis(
    [os.path.join(HERE, "launcher.py")],
    pathex=[ROOT],  # корень проекта: пакеты hwcheck и licensing
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Встроенного браузера больше нет (SPEC 1.3, 25.4): QtWebEngine и всё, что он тянет,
    # в сборку не попадает. Программе нужны только QtCore, QtGui, QtWidgets и QtSvg.
    excludes=[
        "tkinter", "pytest", "pytestqt", "pyright", "ruff", "tests", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtNetwork",
        "PySide6.QtPdf", "PySide6.QtPositioning",
    ],  # fmt: skip
    noarchive=False,
)
# Убираем модули Qt, которые программе не нужны (QML-компоненты, 3D, графики, мультимедиа…)
# и переводы Qt на другие языки. Это уменьшает сборку на сотни мегабайт. Если после правки
# что-то сломается — самопроверка в scripts/build.ps1 это покажет.
UNUSED_QT = (
    "Qt63D", "Qt6Quick3D", "Qt6QuickControls2", "Qt6QuickDialogs2", "Qt6Charts",
    "Qt6DataVisualization", "Qt6Graphs", "Qt6Location", "Qt6Multimedia", "Qt6Sensors",
    "Qt6TextToSpeech", "Qt6VirtualKeyboard", "Qt6Labs", "Qt6RemoteObjects", "Qt6Scxml",
    "Qt6StateMachine", "Qt6SpatialAudio", "Qt6QuickTest", "Qt6Test", "Qt6WebView",
    "Qt6WebEngineQuick", "Qt6QuickTimeline", "Qt6QuickVectorImage", "Qt6QuickParticles",
    "Qt6SerialPort", "Qt6PdfQuick", "Qt6QuickEffects", "Qt6QuickShapes", "Qt6ShaderTools",
    # Движок браузера и его зависимости (25.4).
    "Qt6WebEngine", "QtWebEngine", "Qt6WebChannel", "Qt6Quick", "Qt6Qml", "Qt6Pdf",
    "Qt6Positioning", "Qt6Network", "Qt6OpenGL",
)
KEEP_LANGUAGES = ("_ru.qm", "_en.qm", "/ru.pak", "/en-US.pak")


# Ресурсы и переводы движка браузера (его в программе больше нет) и отладочные копии.
UNUSED_RESOURCES = ("qtwebengine",)
DEBUG_SUFFIXES = (".debug.pak", ".debug.bin")


def wanted(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    if "/qml/" in dest or dest.startswith("PySide6/qml"):
        return False
    if name.startswith(UNUSED_QT):
        return False
    if name.startswith(UNUSED_RESOURCES) or name.endswith(DEBUG_SUFFIXES):
        return False
    if "qtwebengine_locales" in dest:
        return False
    if "/translations/" in dest and not dest.endswith(KEEP_LANGUAGES):
        return False
    return True


a.binaries = [entry for entry in a.binaries if wanted(entry)]
a.datas = [entry for entry in a.datas if wanted(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=os.path.join(ROOT, "hwcheck", "data", "icon.ico"),
    console=False,
    uac_admin=False,  # права администратора программа просит сама кнопкой
    upx=False,
    version=version_info(APP_VERSION),
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
