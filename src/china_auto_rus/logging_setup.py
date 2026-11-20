"""Настройка логирования: консоль + ротация файла в logs/app.log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from china_auto_rus.config import LOG_FILE, ensure_directories

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Инициализирует корневой логгер. Повторный вызов безопасен."""
    root = logging.getLogger()
    if root.handlers:
        return

    ensure_directories()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
