"""Точка входа: python -m china_auto_rus [--check]."""

from __future__ import annotations

import argparse
import logging
import platform
import sys

from china_auto_rus import __version__
from china_auto_rus.config import (
    APP_NAME,
    DEFAULT_PROFILE,
    LOG_FILE,
    WORKSPACE_DIR,
    ensure_directories,
)
from china_auto_rus.logging_setup import setup_logging

logger = logging.getLogger("china_auto_rus")


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
    print(f"{APP_NAME} {__version__}")
    print(f"Python:   {platform.python_version()} ({sys.executable})")
    print(f"PySide6:  {_pyside6_version()}")
    print(f"Профиль:  {DEFAULT_PROFILE.display_name} [{DEFAULT_PROFILE.id}]")
    print(f"Workspace: {WORKSPACE_DIR}")
    print(f"Лог:       {LOG_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="china-auto-rus", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument(
        "--check",
        action="store_true",
        help="проверить окружение и выйти",
    )
    args = parser.parse_args(argv)

    _configure_console()
    setup_logging()
    logger.info("%s %s запущен", APP_NAME, __version__)

    if args.check:
        return _run_check()

    print(f"{APP_NAME} {__version__} — каркас проекта.")
    print("Интерфейс будет добавлен на Этапе 2. Для диагностики: --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
