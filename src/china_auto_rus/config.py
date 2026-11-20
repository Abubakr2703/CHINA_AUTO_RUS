"""Конфигурация приложения: пути, профиль автомобиля, версия."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

APP_NAME = "CHINA AUTO RUS"
APP_VERSION = "0.1.0"

# Корень репозитория: src/china_auto_rus/config.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
REPORTS_DIR = WORKSPACE_DIR / "reports"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "app.log"


@dataclass(frozen=True, slots=True)
class CarProfile:
    """Описание исследуемого автомобиля.

    Неустановленные характеристики остаются None: мы не выдумываем данные
    о мультимедиа и аппаратной платформе.
    """

    id: str
    brand: str
    model: str
    year: int
    market: str
    trim: str
    head_unit: str | None = None
    hardware_platform: str | None = None
    notes: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.brand} {self.model} {self.year} ({self.market})"


DEFAULT_PROFILE = CarProfile(
    id="deepal-s07-2026-cn-restyling",
    brand="Changan",
    model="Deepal S07",
    year=2026,
    market="CN",
    trim="рестайлинг",
    notes="Версия мультимедиа и аппаратная платформа не подтверждены.",
)


def ensure_directories() -> None:
    """Создаёт рабочие каталоги приложения."""
    for path in (WORKSPACE_DIR, REPORTS_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)
