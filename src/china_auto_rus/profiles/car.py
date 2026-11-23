"""Профиль автомобиля как данные.

Логика анализа не знает ни одной конкретной машины: модель, год и рынок
приходят из профиля. Поэтому добавить новый автомобиль — значит добавить
файл с данными, а не править анализатор.

Встроенные профили лежат рядом, в отдельных модулях (``deepal_s07_2026_cn``).
Пользовательские — JSON-файлы в каталоге ``%LOCALAPPDATA%\\CHINA_AUTO_RUS\\profiles``:
их можно добавить без правки кода и без пересборки.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

MIN_YEAR = 1900
MAX_YEAR = 2100

# id попадает в имя отчёта и в командную строку, поэтому только латиница,
# цифры и разделители.
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Поля, которые обязаны быть непустыми строками.
_REQUIRED_TEXT = ("id", "brand", "model")
_OPTIONAL_TEXT = ("head_unit", "hardware_platform", "notes")


class ProfileError(ValueError):
    """Профиль не соответствует ожидаемой схеме."""


@dataclass(frozen=True, slots=True)
class CarProfile:
    """Описание исследуемого автомобиля.

    Неустановленные характеристики остаются ``None``: мы не выдумываем данные
    о мультимедиа и аппаратной платформе.
    """

    id: str
    brand: str
    model: str
    year: int
    market: str
    trim: str = ""
    head_unit: str | None = None
    hardware_platform: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in _REQUIRED_TEXT:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ProfileError(f"поле {name} не может быть пустым")
        if not _ID_PATTERN.match(self.id):
            raise ProfileError(
                "id должен состоять из латиницы в нижнем регистре, цифр "
                "и символов . _ -"
            )
        if isinstance(self.year, bool) or not isinstance(self.year, int):
            raise ProfileError("поле year должно быть целым числом")
        if not MIN_YEAR <= self.year <= MAX_YEAR:
            raise ProfileError(f"год должен быть в диапазоне {MIN_YEAR}..{MAX_YEAR}")
        if not re.fullmatch(r"[A-Z]{2}", self.market):
            raise ProfileError("market — двухбуквенный код страны, например CN")

    @property
    def display_name(self) -> str:
        return f"{self.brand} {self.model} {self.year} ({self.market})"


def profile_from_mapping(
    data: Mapping[str, Any], *, origin: str = ""
) -> CarProfile:
    """Собирает профиль из JSON-объекта. Неизвестные поля игнорируются.

    ``origin`` (имя файла) попадает в текст ошибки, чтобы было понятно,
    какой именно профиль сломан.
    """
    prefix = f"{origin}: " if origin else ""

    def text(name: str, *, required: bool) -> str:
        value = data.get(name)
        if value is None:
            if required:
                raise ProfileError(f"{prefix}нет обязательного поля {name}")
            return ""
        if not isinstance(value, str):
            raise ProfileError(f"{prefix}поле {name} должно быть строкой")
        return value

    year = data.get("year")
    if isinstance(year, bool) or not isinstance(year, int):
        raise ProfileError(f"{prefix}поле year должно быть целым числом")

    market = text("market", required=True)
    trim = text("trim", required=False)
    head_unit = text("head_unit", required=False) or None
    hardware_platform = text("hardware_platform", required=False) or None

    try:
        return CarProfile(
            id=text("id", required=True),
            brand=text("brand", required=True),
            model=text("model", required=True),
            year=year,
            market=market,
            trim=trim,
            head_unit=head_unit,
            hardware_platform=hardware_platform,
            notes=text("notes", required=False),
        )
    except ProfileError as error:
        raise ProfileError(f"{prefix}{error}") from None


def profile_to_mapping(profile: CarProfile) -> dict[str, object]:
    """Обратное преобразование: пригодится для экспорта профиля в JSON."""
    return dict(asdict(profile))
