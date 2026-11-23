"""Запуск GUI-приложения."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from china_auto_rus import __version__
from china_auto_rus.config import APP_NAME, ensure_directories
from china_auto_rus.error_handling import handle_exception, install_exception_hooks
from china_auto_rus.logging_setup import setup_logging
from china_auto_rus.ui.main_window import MainWindow


class SafeApplication(QApplication):
    """QApplication, который не даёт исключению в слоте уронить приложение."""

    def notify(self, receiver: QObject, event: QEvent) -> bool:
        try:
            return super().notify(receiver, event)
        except Exception:
            handle_exception(*sys.exc_info())
            return False


def _show_error(message: str) -> None:
    QMessageBox.critical(None, "Ошибка", message)


def run(argv: list[str] | None = None) -> int:
    setup_logging()
    ensure_directories()

    app = SafeApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    install_exception_hooks(_show_error)

    window = MainWindow()
    window.show()
    return app.exec()
