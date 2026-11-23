"""Точка входа: python -m china_auto_rus [--check | --analyze PATH]."""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from collections.abc import Callable
from pathlib import Path

from china_auto_rus import __version__
from china_auto_rus.config import (
    APP_NAME,
    ensure_directories,
    get_log_file,
    get_profiles_dir,
    get_workspace_dir,
)
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.report import human_size, save_report
from china_auto_rus.core.resources import export_csv, extract_resources
from china_auto_rus.core.strings import contains_cjk, extract_strings_from_file
from china_auto_rus.core.translation import (
    TranslationIssue,
    check_translations,
    export_translation_csv,
    read_translation_csv,
    unique_texts,
)
from china_auto_rus.error_handling import install_exception_hooks
from china_auto_rus.logging_setup import setup_logging
from china_auto_rus.profiles import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
    available_profiles,
    default_profile,
    load_user_profiles,
)

logger = logging.getLogger("china_auto_rus")

# Код возврата, когда GUI-режим невозможен из-за отсутствующей зависимости.
EXIT_MISSING_GUI = 2

GUI_MISSING_HINT = """\
PySide6 не установлен в этом интерпретаторе:
    {executable}

GUI-режим недоступен, но анализ без интерфейса работает.

Запуск из виртуального окружения проекта:
    .venv\\Scripts\\python.exe -m china_auto_rus

Установка зависимостей:
    .venv\\Scripts\\python.exe -m pip install -e ".[dev]"

Диагностика окружения:
    .venv\\Scripts\\python.exe -m china_auto_rus --check
"""


def _configure_console() -> None:
    """Принудительно UTF-8 в консоли Windows (по умолчанию бывает cp1251/cp866)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _pyside6_version() -> str:
    try:
        import PySide6
    except ImportError:
        return "не установлен"
    return PySide6.__version__


def _run_check() -> int:
    """Печатает состояние окружения. Полезно для диагностики на Windows."""
    ensure_directories()
    profile = default_profile()
    print(f"{APP_NAME} {__version__}")
    print(f"Python:   {platform.python_version()} ({sys.executable})")
    print(f"PySide6:  {_pyside6_version()}")
    print(f"Профиль:  {profile.display_name} [{profile.id}]")
    print(f"Встроенных профилей: {len(BUILTIN_PROFILES)}")
    print(f"Профили:  {get_profiles_dir()}")
    print(f"Workspace: {get_workspace_dir()}")
    print(f"Лог:       {get_log_file()}")
    return 0


def _run_profiles() -> int:
    """Показывает встроенные и пользовательские профили автомобилей."""
    directory = get_profiles_dir()
    profiles = available_profiles(directory)
    user_profiles, errors = load_user_profiles(directory)

    print(f"Встроенных профилей: {len(BUILTIN_PROFILES)}")
    print(f"Пользовательских:    {len(user_profiles)} ({directory})")
    print("")
    for profile in profiles:
        marker = "*" if profile.id == DEFAULT_PROFILE_ID else " "
        notes = f" — {profile.notes}" if profile.notes else ""
        print(f"{marker} {profile.id}")
        print(f"    {profile.display_name}{notes}")
    for error in errors:
        print(f"  ! {error.path.name}: {error.message}")
    if errors:
        print(f"\nСломанных профилей: {len(errors)}")
        return 1
    return 0


def _run_analysis(path: Path, *, compute_hashes: bool, profile_id: str) -> int:
    """Анализирует путь и сохраняет отчёты. Нужен для проверки ядра без GUI."""
    report = analyze_paths(
        [path], compute_hashes=compute_hashes, profile_id=profile_id
    )
    json_path, md_path = save_report(report)

    print(f"Профиль: {profile_id}")
    print(
        f"Файлов: {len(report.files)}, объём: {human_size(report.total_size)}, "
        f"ошибок: {len(report.errors)}"
    )
    for error in report.errors[:10]:
        print(f"  ! {error.path}: {error.message}")
    if len(report.errors) > 10:
        print(f"  … ещё ошибок: {len(report.errors) - 10}")

    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    return 0 if report.files else 1


def _run_strings(path: Path, *, limit: int = 200) -> int:
    """Ищет текстовые строки в файле — в том числе в незнакомом контейнере."""
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    scan = extract_strings_from_file(path)
    note = " (прочитано только начало файла)" if scan.truncated else ""
    print(f"Файл: {path}")
    print(f"Просканировано: {human_size(scan.scanned_bytes)}{note}")
    print(f"Найдено строк: {len(scan.hits)}")

    cjk_hits = [hit for hit in scan.hits if contains_cjk(hit.text)]
    other_hits = [hit for hit in scan.hits if not contains_cjk(hit.text)]
    print(f"С китайскими иероглифами: {len(cjk_hits)}")

    ordered = cjk_hits + other_hits
    for hit in ordered[:limit]:
        print(f"{hit.offset:08X}  {hit.encoding:<9} {hit.text}")
    if len(ordered) > limit:
        print(f"… показаны первые {limit} из {len(ordered)}")
    return 0


def _run_resources(
    path: Path,
    *,
    csv_path: Path | None = None,
    translation_path: Path | None = None,
) -> int:
    """Извлекает ресурсы «ключ → текст → язык» из папки, APK или файла."""
    if not path.exists():
        print(f"Путь не найден: {path}", file=sys.stderr)
        return 1

    files = extract_resources(path)
    total = sum(len(item.entries) for item in files)
    languages = sorted({item.language for item in files if item.entries})

    print(f"Источник: {path}")
    print(f"Файлов ресурсов: {sum(1 for item in files if item.entries)}")
    print(f"Строк: {total}")
    print(f"Языки: {', '.join(languages) or '—'}")

    for item in files:
        if item.entries:
            print(f"  {item.language:<8} {len(item.entries):>6}  {item.source}")
    for item in files:
        for note in item.notes:
            print(f"  ! {item.source}: {note}")

    if csv_path is not None and total:
        written = export_csv(files, csv_path)
        print(f"CSV: {csv_path} (строк: {written})")

    if translation_path is not None and total:
        written = export_translation_csv(
            (entry for item in files for entry in item.entries),
            translation_path,
        )
        print(f"Шаблон перевода: {translation_path} (строк: {written})")
    return 0 if total else 1


def _issue_label(issue: TranslationIssue) -> str:
    return f"{issue.source}:{issue.key}" if issue.source else issue.key


def _run_check_translations(path: Path) -> int:
    """Проверяет заполненный шаблон и печатает прогресс перевода."""
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    rows = read_translation_csv(path)
    report = check_translations(rows)
    unique = unique_texts(rows)

    print(f"Файл: {path}")
    print(
        f"Строк: {report.total}, переведено: {report.translated} "
        f"({report.coverage:.1%})"
    )
    print(
        f"Уникальных текстов: {len(unique)} "
        f"(дублей: {report.total - len(unique)})"
    )

    errors = report.errors
    warnings = report.warnings
    for issue in errors[:20]:
        print(f"  ! {_issue_label(issue)}: {issue.message}")
    if len(errors) > 20:
        print(f"  … ещё ошибок: {len(errors) - 20}")
    for issue in warnings[:10]:
        print(f"  ~ {_issue_label(issue)}: {issue.message}")
    if len(warnings) > 10:
        print(f"  … ещё предупреждений: {len(warnings) - 10}")
    if report.missing:
        print(f"  Без перевода: {len(report.missing)}, например:")
        for label in report.missing[:5]:
            print(f"    - {label}")

    print(f"Ошибок: {len(errors)}, предупреждений: {len(warnings)}")
    return 1 if errors else 0


def _load_gui() -> Callable[[list[str]], int]:
    """Импортирует GUI-слой отдельно, чтобы ошибку зависимости было видно."""
    from china_auto_rus.app import run

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="china-auto-rus", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--check",
        action="store_true",
        help="проверить окружение и выйти",
    )
    parser.add_argument(
        "--analyze",
        type=Path,
        metavar="PATH",
        help="проанализировать файл или папку и сохранить отчёт",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="не считать SHA-256 (быстрее на больших образах)",
    )
    parser.add_argument(
        "--profile",
        metavar="ID",
        help="профиль автомобиля для --analyze (см. --profiles)",
    )
    parser.add_argument(
        "--profiles",
        action="store_true",
        help="показать профили автомобилей и выйти",
    )
    parser.add_argument(
        "--strings",
        type=Path,
        metavar="PATH",
        help="найти текстовые строки в бинарном файле (UTF-8/UTF-16/GBK)",
    )
    parser.add_argument(
        "--resources",
        type=Path,
        metavar="PATH",
        help="извлечь ресурсы «ключ → текст → язык» из папки, APK или файла",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        metavar="PATH",
        help="сохранить извлечённые ресурсы в CSV (используется с --resources)",
    )
    parser.add_argument(
        "--translation-csv",
        type=Path,
        metavar="PATH",
        help="сохранить шаблон перевода для переводчика (с --resources)",
    )
    parser.add_argument(
        "--check-translations",
        type=Path,
        metavar="PATH",
        help="проверить заполненный шаблон перевода и показать прогресс",
    )
    args = parser.parse_args(argv)

    _configure_console()
    setup_logging()
    install_exception_hooks()
    logger.info("%s %s запущен", APP_NAME, __version__)

    if args.check:
        return _run_check()

    if args.profiles:
        return _run_profiles()

    if args.analyze is not None:
        profile_id = args.profile or DEFAULT_PROFILE_ID
        known = {profile.id for profile in available_profiles(get_profiles_dir())}
        if profile_id not in known:
            print(f"Профиль не найден: {profile_id}", file=sys.stderr)
            print(f"Доступны: {', '.join(sorted(known))}", file=sys.stderr)
            return 1
        return _run_analysis(
            args.analyze,
            compute_hashes=not args.no_hash,
            profile_id=profile_id,
        )

    if args.strings is not None:
        return _run_strings(args.strings)

    if args.resources is not None:
        return _run_resources(
            args.resources,
            csv_path=args.csv,
            translation_path=args.translation_csv,
        )

    if args.check_translations is not None:
        return _run_check_translations(args.check_translations)

    try:
        run_gui = _load_gui()
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "PySide6":
            print(
                GUI_MISSING_HINT.format(executable=sys.executable),
                file=sys.stderr,
            )
            logger.error(
                "GUI-режим недоступен: PySide6 не установлен (%s)", sys.executable
            )
            return EXIT_MISSING_GUI
        raise

    return run_gui([])


if __name__ == "__main__":
    raise SystemExit(main())
