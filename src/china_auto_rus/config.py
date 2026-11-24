"""Конфигурация приложения: пути, версия.

Профиль автомобиля здесь больше не живёт: модели — данные, они лежат
в пакете :mod:`china_auto_rus.profiles` и в пользовательском каталоге.

Пути делятся на две группы:

* ``PROJECT_ROOT`` — исходный код и ресурсы. Сюда ничего не пишем.
* ``USER_DATA_DIR`` — отчёты, логи и настройки пользователя. По умолчанию
  это ``%LOCALAPPDATA%\\CHINA_AUTO_RUS``, а при отсутствии переменной —
  портативный fallback рядом с домашним каталогом.
"""

from __future__ import annotations

import os
from pathlib import Path

from china_auto_rus import __version__

APP_NAME = "CHINA AUTO RUS"
APP_VERSION = __version__
APP_DIR_NAME = "CHINA_AUTO_RUS"

# Корень репозитория: src/china_auto_rus/config.py -> parents[2].
# Используется только для чтения исходников и ресурсов.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_user_data_dir() -> Path:
    """Каталог пользовательских данных без обращения к каталогу установки."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    # LOCALAPPDATA может отсутствовать в тестах и на не-Windows системах.
    return Path.home() / ".local" / "share" / APP_DIR_NAME


USER_DATA_DIR = _default_user_data_dir()
REPORTS_DIR = USER_DATA_DIR / "reports"
LOGS_DIR = USER_DATA_DIR / "logs"
SETTINGS_DIR = USER_DATA_DIR / "settings"
LOG_FILE = LOGS_DIR / "app.log"

# Пользовательские профили автомобилей: JSON-файлы, без правки кода.
PROFILES_DIR = USER_DATA_DIR / "profiles"

# Оставлено для совместимости: рабочие файлы тоже живут у пользователя.
WORKSPACE_DIR = USER_DATA_DIR / "workspace"


def get_user_data_dir() -> Path:
    return USER_DATA_DIR


def get_reports_dir() -> Path:
    """Актуальный каталог отчётов (учитывает подмену в тестах)."""
    return REPORTS_DIR


def get_logs_dir() -> Path:
    return LOGS_DIR


def get_settings_dir() -> Path:
    """Настройки всегда рядом с отчётами — в каталоге пользовательских данных."""
    return get_reports_dir().parent / "settings"


def get_log_file() -> Path:
    return LOG_FILE


def get_workspace_dir() -> Path:
    return WORKSPACE_DIR


def get_profiles_dir() -> Path:
    """Каталог пользовательских профилей автомобилей (JSON)."""
    return PROFILES_DIR


def ensure_directories() -> None:
    """Создаёт только пользовательские каталоги, без записи в каталог установки."""
    for path in (
        get_reports_dir(),
        get_logs_dir(),
        get_settings_dir(),
        get_workspace_dir(),
        get_profiles_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
