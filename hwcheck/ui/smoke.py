"""Самопроверка собранной программы (`--demo --smoke-test`).

Программа сама проходит демо-проверку «старт → быстрая проверка → вердикт», сохраняет
отчёт HTML и PDF и закрывается. Итог пишется в `data/logs/smoke_test.txt`, код выхода:
0 — всё работает, 1 — что-то сломалось или не уложилось во время. Нужна, чтобы после
сборки автоматически убедиться, что exe запускается и все части программы на месте.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop

from hwcheck.config import package_data_dir, temp_dir
from hwcheck.models import TestResult, TestStatus
from hwcheck.ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _wait(condition: Callable[[], bool], deadline: float) -> bool:
    while time.monotonic() < deadline:
        if condition():
            return True
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    return False


def _check_charts() -> bool:
    """Графики отчёта рисуются модулем QtSvg (PDF без движка браузера, 25.4)."""
    from hwcheck.report.builder import svg_line_chart
    from hwcheck.report.pdf import svg_to_image

    image = svg_to_image(svg_line_chart([(0.0, 40.0), (10.0, 70.0)], "Проверка", "°C"))
    return not image.isNull() and image.width() > 0


def _check_keyboard(window: MainWindow) -> tuple[bool | None, bool | None]:
    """Тест клавиатуры в настоящем окне (25.1): (Alt+F4 не закрыл окно и засчитан,
    «×» во время теста спросил подтверждение). None — нет настоящего окна Windows (другая ОС
    или платформа Qt offscreen в тестах), проверить нечем; в собранной программе окно есть."""
    from hwcheck.platform import window_messages

    page = window.laptop_page
    page.refresh()
    window.go_to("laptop")
    page.start_keyboard_test()
    hwnd = int(window.winId())
    _wait(lambda: False, time.monotonic() + 0.3)
    if not window_messages.send_alt_f4(hwnd):
        page.keyboard.stop()
        return None, None
    _wait(lambda: False, time.monotonic() + 1.5)
    window_messages.restore_alt(hwnd)
    alt_f4_ok = window.isVisible() and page.keyboard.is_lit("F4") and page.keyboard.running
    asked: list[str] = []
    original = window.confirm
    window.confirm = lambda _title, text: asked.append(text) is not None and False  # «Нет»
    try:
        window_messages.send_close(hwnd)
        _wait(lambda: bool(asked), time.monotonic() + 3)
        close_ok = bool(asked) and window.isVisible()
    finally:
        window.confirm = original
        page.keyboard.stop()
    return alt_f4_ok, close_ok


KEYBOARD_SHOT_SIZES = [(1280, 720), (1920, 1080)]


def _keyboard_layout_shots(window: MainWindow) -> list[str]:
    """Снимки страницы «Ноутбук» в окнах разного размера (25.2): строки для итога.

    Снимки — в папке журналов (`keyboard_<размер>.png`), сборка копирует их в docs/qa."""
    from hwcheck.ui.widgets.keyboard_view import overlapping_keys

    page = window.laptop_page
    lines = []
    for width, height in KEYBOARD_SHOT_SIZES:
        window.resize(width, height - 40)
        page.start_keyboard_test()
        _wait(lambda: False, time.monotonic() + 0.4)
        page.keyboard_done.click()  # длинный список «не нажимались» не должен сдвигать схему
        _wait(lambda: False, time.monotonic() + 0.4)
        name = f"keyboard_{width}x{height}.png"
        window.grab().save(str(window.ctx.paths.logs / name))
        overlaps = overlapping_keys(page.keyboard.key_rects())
        state = "клавиши не пересекаются" if not overlaps else f"ПЕРЕСЕКАЮТСЯ: {overlaps[:3]}"
        lines.append(f"Схема клавиатуры {width}×{height}: {state} ({name})")
    return lines


def _check_listing(window: MainWindow, deadline: float) -> tuple[bool, bool]:
    """Объявление (25.4): (сохранённая страница с кириллицей в пути разобрана,
    вставленный текст объявления разобран) — без встроенного браузера, как пользователь."""
    ctx = window.ctx
    page = window.listing_page
    page.refresh()
    window.go_to("listing")
    html = (package_data_dir() / "smoke" / "listing_sample.html").read_text(encoding="utf-8")

    def saved_gpu() -> str:
        claims = ctx.listings.load()
        return claims.gpu_model if claims is not None else ""

    with temp_dir() as folder:
        sample = folder / "Сохранённая страница Авито.html"
        sample.write_text(html, encoding="utf-8")
        page.open_saved_file(sample)
        from_file = _wait(lambda: page.pending_id is None, deadline) and bool(saved_gpu())
    ctx.listings.clear()
    page.text_edit.setPlainText(LISTING_SAMPLE_TEXT)
    page.analyze()
    from_text = _wait(lambda: page.pending_id is None, deadline) and bool(saved_gpu())
    ctx.listings.clear()
    page.text_edit.clear()
    return from_file, from_text


LISTING_SAMPLE_TEXT = "Видеокарта RTX 3070 8GB\n32 000 ₽\nПродаю, работала в играх.\n"


def exe_dir() -> Path | None:
    """Папка exe в собранной программе (None — запуск из исходников)."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def _check_exe_metadata(program_dir: Path | None) -> tuple[str, bool]:
    """Свойства собранного exe: правообладатель — только BagroDeRose (SPEC 1.5, 34.7)."""
    if program_dir is None:
        return "", True  # из исходников exe нет
    from hwcheck.platform.file_version import read_version_strings

    fields = read_version_strings(Path(sys.executable).resolve())
    company = fields.get("CompanyName", "")
    copyright_ = fields.get("LegalCopyright", "")
    ok = company == "BagroDeRose" and "BagroDeRose" in copyright_
    text = f"CompanyName «{company or '—'}», LegalCopyright «{copyright_ or '—'}»"
    return f"Свойства exe: {text}" + ("" if ok else " — НЕ ПСЕВДОНИМ"), ok


def run_smoke_test(
    window: MainWindow,
    timeout_s: float = 120.0,
    worker_check: Callable[[], TestResult] | None = None,
) -> int:
    """Проводит демо-проверку в окне. Возвращает код выхода (0 — успех).

    `worker_check` — короткая настоящая нагрузка (в собранной программе): проверяет, что
    дочерние процессы нагрузки запускаются из exe.
    """
    ctx = window.ctx
    deadline = time.monotonic() + timeout_s
    lines = [f"Самопроверка, сценарий: {ctx.demo_scenario or 'нет'}"]
    code = 1
    try:
        if not _wait(lambda: window.start_page.next_button.isEnabled(), deadline):
            raise TimeoutError("сведения о железе не собраны вовремя")
        window.start_page.next_button.click()
        window.mode_page.start_button.click()
        if not _wait(lambda: window.current_page_name() == "verdict", deadline):
            window.stop_check()
            raise TimeoutError("проверка не дошла до вердикта вовремя")
        session = window.last_session
        if session is None or session.verdict is None:
            raise RuntimeError("вердикт не получен")
        report = window.verdict_page.save_report()
        if report is None:
            raise RuntimeError("отчёт не сохранён")
        pdfs = list(report.parent.glob(report.stem + ".pdf"))
        charts = _check_charts()
        lines.append(f"Вердикт: {session.verdict.decision.value}")
        lines.append(f"Отчёт: {report.name}, PDF: {'есть' if pdfs else 'НЕТ'}")
        lines.append(f"Графики для PDF (QtSvg): {'рисуются' if charts else 'НЕ рисуются'}")
        from_file, from_text = _check_listing(window, deadline)
        lines.append(f"Объявление из файла: {'разобрано' if from_file else 'НЕ разобрано'}")
        lines.append(f"Объявление из текста: {'разобрано' if from_text else 'НЕ разобрано'}")
        metadata_line, metadata_ok = _check_exe_metadata(exe_dir())
        if metadata_line:
            lines.append(metadata_line)
        alt_f4, close_asked = _check_keyboard(window)
        if alt_f4 is None:
            alt_text = "не проверялся (нет настоящего окна Windows)"
        else:
            alt_text = "окно не закрылось, F4 засчитана" if alt_f4 else "ОКНО ЗАКРЫЛОСЬ / F4 НЕТ"
        lines.append(f"Alt+F4 в тесте клавиатуры: {alt_text}")
        if close_asked is None:
            close_text = "не проверялось"
        else:
            close_text = "спрошено подтверждение" if close_asked else "НЕ спрошено"
        lines.append(f"Закрытие окна во время теста: {close_text}")
        ctx.paths.logs.mkdir(parents=True, exist_ok=True)
        layout_lines = _keyboard_layout_shots(window)
        lines.extend(layout_lines)
        keyboard_ok = (
            alt_f4 is not False
            and close_asked is not False
            and all("ПЕРЕСЕКАЮТСЯ" not in line for line in layout_lines)
        )
        workers_ok = True
        if worker_check is not None:
            result = worker_check()
            workers_ok = result.status is TestStatus.PASSED
            state = "работают" if workers_ok else f"НЕ работают ({'; '.join(result.notes)})"
            lines.append(f"Процессы нагрузки: {state}")
        listing_ok = from_file and from_text
        all_ok = pdfs and charts and listing_ok and workers_ok and keyboard_ok and metadata_ok
        code = 0 if all_ok else 1
        lines.append("OK" if code == 0 else "FAIL: см. строки выше")
    except Exception as error:  # итог самопроверки пишем в файл в любом случае
        lines.append(f"FAIL: {error}")
        lines.append(traceback.format_exc())
    ctx.paths.logs.mkdir(parents=True, exist_ok=True)
    (ctx.paths.logs / "smoke_test.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Самопроверка завершена с кодом %s", code)
    return code
