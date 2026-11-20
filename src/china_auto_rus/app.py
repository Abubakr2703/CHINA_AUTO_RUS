"""Запуск GUI-приложения."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from china_auto_rus import __version__
from china_auto_rus.config import APP_NAME, ensure_directories
from china_auto_rus.logging_setup import setup_logging
from china_auto_rus.ui.main_window import MainWindow


def run(argv: list[str] | None = None) -> int:
    setup_logging()
    ensure_directories()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)

    window = MainWindow()
    window.show()
    return app.exec()
