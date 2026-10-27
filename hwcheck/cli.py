"""Консольные команды программы (для разработки и проверки без интерфейса).

Примеры:
    python -m hwcheck.cli collect                      — собрать сведения о железе (только чтение)
    python -m hwcheck.cli collect --demo mining_gpu    — то же на демо-сценарии
    python -m hwcheck.cli collect --out snapshot.json  — сохранить результат в файл
    python -m hwcheck.cli run --short                  — короткие (по 30 с) нагрузочные тесты
    python -m hwcheck.cli run --demo mining_gpu        — проверка на демо-сценарии
    python -m hwcheck.cli verdict --demo mining_gpu    — вердикт по демо-сценарию
    python -m hwcheck.cli verdict --from run.json      — вердикт по сохранённому прогону
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from hwcheck.backends import create_backend
from hwcheck.backends.fake import list_scenarios
from hwcheck.models import CheckSession, Severity, TestResult, Verdict
from hwcheck.session import run_check
from hwcheck.ui import strings
from hwcheck.verdict.engine import decide


def _use_utf8_output() -> None:
    """Включает UTF-8 в консоли, чтобы русский текст не превращался в «кракозябры»."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _check_demo(demo: str | None) -> bool:
    """Проверяет имя демо-сценария; при ошибке печатает список доступных."""
    if demo and demo not in list_scenarios():
        print(f"Неизвестный сценарий «{demo}». Доступны:", file=sys.stderr)
        for name in list_scenarios():
            print(f"  {name}", file=sys.stderr)
        return False
    return True


def _write_or_print(text: str, out: str | None) -> None:
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"Сохранено: {path}")
    else:
        print(text)


def cmd_collect(args: argparse.Namespace) -> int:
    """Команда collect: собрать сведения о железе и вывести JSON."""
    if not _check_demo(args.demo):
        return 2
    backend = create_backend(args.demo)
    snapshot = backend.collect()
    _write_or_print(snapshot.to_json(), args.out)
    return 0


def _mode(args: argparse.Namespace) -> str:
    if args.short:
        return "short"
    if args.full:
        return "full"
    return "quick"


def cmd_run(args: argparse.Namespace) -> int:
    """Команда run: сведения о железе + нагрузочные тесты, итог в JSON."""
    if not _check_demo(args.demo):
        return 2
    backend = create_backend(args.demo)
    mode = _mode(args)
    shown = {"percent": -10}

    def progress(value: float, step: str) -> None:
        percent = int(value * 100)
        if percent - shown["percent"] >= 10 or percent == 100:
            shown["percent"] = percent
            print(f"  {percent:3d}%  {step}", flush=True)

    def step_done(result: TestResult) -> None:
        print(f"  — {result.name}: {result.status.value}", flush=True)

    print(f"Проверка, режим {mode}. Остановить — Ctrl+C.", flush=True)
    cancel = threading.Event()
    try:
        session = run_check(
            backend,
            mode,
            cancel,
            on_progress=progress,
            on_step_done=step_done,
            only=args.only.split(",") if args.only else None,
            demo_scenario=args.demo or "",
        )
    except KeyboardInterrupt:
        cancel.set()
        print("Остановлено.")
        return 130
    _write_or_print(session.to_json(), args.out)
    return 0


def format_verdict(verdict: Verdict) -> str:
    """Вердикт в виде текста для консоли."""
    lines = [
        f"Вердикт: {strings.DECISION_TITLES[verdict.decision.value].upper()}",
        verdict.summary,
        "",
        "Причины:",
    ]
    for finding in verdict.findings:
        if finding.severity is Severity.OK:
            continue
        lines.append(f"  [{strings.SEVERITY_NAMES[finding.severity.value]}] {finding.title}")
        lines.append(f"      {finding.explanation}")
        if finding.advice:
            lines.append(f"      Что делать: {finding.advice}")
    good = [f.title for f in verdict.findings if f.severity is Severity.OK]
    if good:
        lines += ["", "В порядке:"] + [f"  + {title}" for title in good]
    if verdict.bargaining_points:
        lines += ["", "Аргументы для торга:"] + [f"  • {p}" for p in verdict.bargaining_points]
    lines += ["", "Что не удалось проверить:"]
    lines += [f"  • {item}" for item in verdict.not_checked] or ["  • всё проверено"]
    return "\n".join(lines)


def cmd_verdict(args: argparse.Namespace) -> int:
    """Команда verdict: вердикт по демо-сценарию или по сохранённому прогону."""
    if args.source:
        session = CheckSession.from_json(Path(args.source).read_text(encoding="utf-8"))
        verdict = decide(session.snapshot, session.results)
    elif args.demo:
        if not _check_demo(args.demo):
            return 2
        session = run_check(create_backend(args.demo), "quick", threading.Event())
        assert session.verdict is not None
        verdict = session.verdict
    else:
        print("Укажите --demo СЦЕНАРИЙ или --from ФАЙЛ (результат команды run).", file=sys.stderr)
        return 2
    print(format_verdict(verdict))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hwcheck", description="ЖелезоЧек — консольные команды")
    commands = parser.add_subparsers(dest="command")

    collect = commands.add_parser("collect", help="собрать сведения о железе (только чтение)")
    collect.add_argument("--demo", metavar="SCENARIO", help="взять данные из демо-сценария")
    collect.add_argument("--out", metavar="FILE", help="сохранить JSON в файл")
    collect.set_defaults(func=cmd_collect)

    run = commands.add_parser("run", help="нагрузочные тесты (для разработки)")
    run.add_argument("--demo", metavar="SCENARIO", help="демо-сценарий вместо реального железа")
    run.add_argument("--out", metavar="FILE", help="сохранить результат (JSON) в файл")
    run.add_argument("--only", metavar="TESTS", help="только эти тесты, через запятую")
    length = run.add_mutually_exclusive_group()
    length.add_argument("--short", action="store_true", help="по 30 секунд на тест")
    length.add_argument("--quick", action="store_true", help="быстрая проверка (~10 мин)")
    length.add_argument("--full", action="store_true", help="полная проверка (~35 мин)")
    run.set_defaults(func=cmd_run)

    verdict = commands.add_parser("verdict", help="вердикт по демо-сценарию или прогону")
    verdict.add_argument("--demo", metavar="SCENARIO", help="демо-сценарий")
    verdict.add_argument("--from", dest="source", metavar="FILE", help="JSON из команды run")
    verdict.set_defaults(func=cmd_verdict)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа консольных команд. Возвращает код завершения."""
    _use_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
