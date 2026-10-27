r"""Скриншоты интерфейса из демо-режима (инструмент разработчика, SPEC 1.3 — 24.5).

Снимает все основные страницы в обеих темах (версия 2.0: программа бесплатная, все функции
доступны всем — без разделения Free/Pro). Имена файлов — без номера версии (`verdict_light.png`):
при следующей съёмке файлы перезаписываются, а не копятся. Скрипт заодно пересоздаёт галерею
`docs/SCREENSHOTS.md`, а устаревшие снимки (которых нет в новом наборе) удаляет.

Окно рисуется без показа на экране (атрибут WA_DontShowOnScreen; платформа offscreen не
годится — в ней нет шрифтов). Демо-данные пишутся во временную папку внутри `.tmp/` проекта.

Запуск:  .venv\Scripts\python scripts\make_screenshots.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
GALLERY = ROOT / "docs" / "SCREENSHOTS.md"
WINDOW_SIZE = (1150, 860)
# Тема → демо-сценарий: светлая — компьютер с майнинговой видеокартой, тёмная — ноутбук.
SCENARIOS = {"light": "mining_gpu", "dark": "laptop_worn_battery"}
PAGES = ["start", "mode", "progress", "verdict", "history", "listing", "laptop", "settings"]
# Тест клавиатуры ноутбука (25.2): размер экрана и масштаб Windows. 150 % снимается в
# отдельном процессе с QT_SCALE_FACTOR=1.5 (окно того же физического размера).
KEYBOARD_SCREENS = [(1280, 720, 100), (1366, 768, 100), (1920, 1080, 100), (1920, 1080, 150)]
KEYBOARD_PRESSED = [1, 16, 17, 18, 30, 31, 32, 57, 28, 14, 0x148, 0x14B, 0x150, 0x14D, 59, 62]

SAMPLE_LISTING = (
    "Игровой ПК: RTX 3070 8GB, Ryzen 5 5600, 32 ГБ ОЗУ\n"
    "65 000 ₽\n"
    "Состояние: Б/у\n"
    "Видеокарта полгода работала в майнинге, потом только игры. Срочно, торг.\n"
)

TITLES = {
    "start": "Старт: сводка «Что найдено»",
    "mode": "Выбор режима проверки",
    "progress": "Идёт проверка",
    "verdict": "Вердикт",
    "history": "История и отчёты",
    "listing": "Проверка объявления",
    "laptop": "Ноутбук",
    "settings": "Настройки",
}


def screenshot_names() -> list[str]:
    """Имена всех снимков набора (без расширения) в порядке галереи."""
    names = [f"{page}_{theme}" for page in PAGES for theme in SCENARIOS]
    names += ["icon_sizes"]  # иконка программы во всех размерах (SPEC 1.5, 36.1)
    return names + [keyboard_name(w, h, scale) for w, h, scale in KEYBOARD_SCREENS]


def keyboard_name(width: int, height: int, scale: int) -> str:
    return f"keyboard_{width}x{height}" + ("" if scale == 100 else f"_{scale}")


def gallery_text() -> str:
    """Текст docs/SCREENSHOTS.md: таблица «светлая | тёмная» для каждой страницы."""
    lines = [
        "# Как выглядит программа",
        "",
        "Скриншоты сделаны в демо-режиме на учебных данных (данные не настоящие) скриптом",
        "`scripts/make_screenshots.py`. Набор пересоздаётся целиком при каждом изменении",
        "интерфейса; имена файлов без номера версии.",
        "",
        "| Страница | Светлая тема | Тёмная тема |",
        "|---|---|---|",
    ]
    for page in PAGES:
        cells = [f"![{TITLES[page]}](images/{page}_{theme}.png)" for theme in SCENARIOS]
        lines.append(f"| {TITLES[page]} | {' | '.join(cells)} |")
    lines += [
        "",
        "## Иконка программы",
        "",
        "Из фирменного аватара (`docs/brand/avatar.png`): 48–256 px — сам аватар, 16–32 px —",
        "упрощённый вариант без свечения и мелких деталей (внизу — увеличенно). Собирает",
        "`scripts/make_icon.py` (SPEC 1.5, 36.1).",
        "",
        "![Иконка во всех размерах](images/icon_sizes.png)",
        "",
        "## Тест клавиатуры ноутбука на разных экранах",
        "",
        "Схема клавиатуры сохраняет пропорции, клавиши не наезжают друг на друга; список",
        "ненажатых клавиш — в своей прокручиваемой области под схемой (задача 25.2). Геометрию",
        "проверяет `tests/ui/test_keyboard_layout.py`, снимки из собранной программы — в",
        "`docs/qa/smoke_<версия>_keyboard_*.png`.",
        "",
        "| Экран | Снимок |",
        "|---|---|",
    ]
    for width, height, scale in KEYBOARD_SCREENS:
        name = keyboard_name(width, height, scale)
        label = f"{width}×{height}, масштаб {scale} %"
        lines.append(f"| {label} | ![Тест клавиатуры, {label}](images/{name}.png) |")
    lines.append("")
    return "\n".join(lines)


def stale_images(keep: set[str]) -> list[Path]:
    """Снимки в docs/images, которых нет в новом наборе (кроме снимков других скриптов)."""
    return [path for path in sorted(OUT.glob("*.png")) if path.stem not in keep]


def shoot_keyboard(app: object, data_root: Path, screens: list[tuple[int, int, int]]) -> None:
    """Страница «Ноутбук» с тестом клавиатуры на экранах разного размера (Pro, светлая тема)."""
    from PySide6.QtCore import QCoreApplication, Qt

    from hwcheck.backends.fake import FakeBackend
    from hwcheck.config import get_paths
    from hwcheck.ui.context import AppContext
    from hwcheck.ui.main_window import MainWindow
    from hwcheck.ui.theme import apply_theme

    apply_theme(app, "light")  # type: ignore[arg-type]  # QApplication
    for width, height, scale in screens:
        ctx = AppContext.create(
            FakeBackend("laptop_worn_battery"), get_paths(data_root / f"kb_{width}_{scale}"),
            "laptop_worn_battery",
        )  # fmt: skip
        ctx.admin_check = lambda: False
        window = MainWindow(ctx)
        factor = scale / 100
        window.resize(int(width / factor), int((height - 40) / factor))  # минус заголовок
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.show()
        window.laptop_page.refresh()
        window.go_to("laptop")
        page = window.laptop_page
        page.start_keyboard_test()
        for scan in KEYBOARD_PRESSED:
            page.keyboard.press_native(scan, 0)
        page.keyboard_done.click()
        for _ in range(30):
            QCoreApplication.processEvents()
        name = keyboard_name(width, height, scale)
        window.grab().save(str(OUT / f"{name}.png"))
        print("снимок:", name)
        window.close()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    if "--keyboard" in sys.argv:  # дочерний процесс для масштаба 150 %
        from hwcheck.ui.app import ensure_application

        app = ensure_application([])
        scale = int(sys.argv[sys.argv.index("--keyboard") + 1])
        screens = [screen for screen in KEYBOARD_SCREENS if screen[2] == scale]
        (ROOT / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", ignore_cleanup_errors=True) as tmp:
            shoot_keyboard(app, Path(tmp), screens)
        return 0
    from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer

    from hwcheck.backends.fake import FakeBackend
    from hwcheck.config import get_paths
    from hwcheck.ui.app import ensure_application
    from hwcheck.ui.context import AppContext
    from hwcheck.ui.main_window import MainWindow
    from hwcheck.ui.theme import apply_theme

    app = ensure_application([])
    OUT.mkdir(parents=True, exist_ok=True)

    def wait_until(condition: Callable[[], bool], timeout_ms: int = 30000) -> None:
        loop_end = QTimer()
        loop_end.setSingleShot(True)
        loop_end.start(timeout_ms)
        while not condition() and loop_end.isActive():
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    def shoot(window: MainWindow, name: str) -> None:
        for _ in range(20):
            QCoreApplication.processEvents()
        window.grab().save(str(OUT / f"{name}.png"))
        print("снимок:", name)

    (ROOT / ".tmp").mkdir(exist_ok=True)
    # Временные данные — в .tmp проекта (SPEC 1.1); кэш браузера может быть ещё занят.
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", ignore_cleanup_errors=True) as tmp:
        for theme, scenario in SCENARIOS.items():
            apply_theme(app, theme)
            backend = FakeBackend(scenario, time_scale=0.004)
            data = get_paths(Path(tmp) / theme)
            ctx = AppContext.create(backend, data, scenario)
            ctx.open_path = lambda _path: None
            ctx.admin_check = lambda: False
            window = MainWindow(ctx)
            window.resize(*WINDOW_SIZE)
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            window.show()
            window.start_page.start_collect()
            wait_until(lambda w=window: w.start_page.next_button.isEnabled())
            suffix = f"_{theme}"
            shoot(window, f"start{suffix}")
            window.go_to("mode")
            shoot(window, f"mode{suffix}")
            window.start_check("quick")
            wait_until(lambda w=window: w.progress_page.bar.value() > 400)
            shoot(window, f"progress{suffix}")
            wait_until(lambda w=window: w.current_page_name() == "verdict")
            shoot(window, f"verdict{suffix}")
            window.verdict_page.save_report()
            for page in ("history", "listing", "laptop", "settings"):
                window.go_to(page)
                if page == "listing":
                    # Пример объявления (выдуманный), чтобы видеть карточки результата.
                    listing = window.listing_page
                    listing.text_edit.setPlainText(SAMPLE_LISTING)
                    listing.analyze()
                    wait_until(lambda lp=listing: lp.pending_id is None)
                    listing.scroll_area.verticalScrollBar().setValue(listing.results.y() - 120)
                shoot(window, f"{page}{suffix}")
            window.close()
        shoot_keyboard(app, Path(tmp), [s for s in KEYBOARD_SCREENS if s[2] == 100])
    from scripts import make_icon  # превью иконки — часть набора снимков (SPEC 1.5, 36.1)

    make_icon.build()
    print("снимок: icon_sizes")
    for scale in sorted({screen[2] for screen in KEYBOARD_SCREENS} - {100}):
        env = {**os.environ, "QT_SCALE_FACTOR": str(scale / 100)}
        subprocess.run(  # noqa: S603 — этот же скрипт, без оболочки
            [sys.executable, __file__, "--keyboard", str(scale)], env=env, check=True
        )
    keep = set(screenshot_names())
    for path in stale_images(keep):
        path.unlink()
        print("удалён устаревший снимок:", path.name)
    GALLERY.write_text(gallery_text(), encoding="utf-8")
    print("галерея:", GALLERY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
