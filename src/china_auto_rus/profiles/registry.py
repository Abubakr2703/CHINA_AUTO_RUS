"""Реестр профилей: встроенные модули и пользовательские JSON-файлы.

Новый встроенный автомобиль — новый модуль рядом с ``deepal_s07_2026_cn``
и одна строка в ``BUILTIN_PROFILES``. Новый личный автомобиль — JSON-файл
в пользовательском каталоге ``profiles``, без правки кода.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from china_auto_rus.profiles.car import (
    CarProfile,
    ProfileError,
    profile_from_mapping,
)
from china_auto_rus.profiles.deepal_s07_2026_cn import PROFILE as DEEPAL_S07_2026_CN

DEFAULT_PROFILE_ID = DEEPAL_S07_2026_CN.id

BUILTIN_PROFILES: tuple[CarProfile, ...] = (DEEPAL_S07_2026_CN,)


@dataclass(frozen=True, slots=True)
class ProfileLoadError:
    """Сломанный пользовательский профиль. Не мешает остальным."""

    path: Path
    message: str


def find_profile(profile_id: str) -> CarProfile | None:
    for profile in BUILTIN_PROFILES:
        if profile.id == profile_id:
            return profile
    return None


def get_profile(profile_id: str) -> CarProfile:
    profile = find_profile(profile_id)
    if profile is None:
        raise KeyError(f"профиль не найден: {profile_id}")
    return profile


def default_profile() -> CarProfile:
    return get_profile(DEFAULT_PROFILE_ID)


def resolve_profile(
    profile_id: str, directory: Path | None = None
) -> CarProfile | None:
    """Ищет профиль среди встроенных, затем среди пользовательских JSON-файлов."""
    profile = find_profile(profile_id)
    if profile is not None or directory is None:
        return profile
    user_profiles, _ = load_user_profiles(directory)
    return next(
        (item for item in user_profiles if item.id == profile_id), None
    )


def load_user_profiles(
    directory: Path,
) -> tuple[tuple[CarProfile, ...], tuple[ProfileLoadError, ...]]:
    """Читает JSON-профили из каталога.

    Ошибка в одном файле не мешает остальным: она возвращается отдельно.
    """
    profiles: list[CarProfile] = []
    errors: list[ProfileLoadError] = []
    if not directory.is_dir():
        return (), ()

    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(ProfileLoadError(path, f"не удалось прочитать JSON: {error}"))
            continue
        if not isinstance(payload, Mapping):
            errors.append(ProfileLoadError(path, "ожидался JSON-объект"))
            continue
        try:
            profiles.append(profile_from_mapping(payload, origin=path.name))
        except ProfileError as error:
            errors.append(ProfileLoadError(path, str(error)))

    return tuple(profiles), tuple(errors)


def available_profiles(directory: Path | None = None) -> tuple[CarProfile, ...]:
    """Встроенные профили плюс пользовательские.

    При совпадении ``id`` побеждает встроенный профиль: пользовательский файл
    не должен незаметно переопределять проверенные данные.
    """
    profiles = {profile.id: profile for profile in BUILTIN_PROFILES}
    if directory is not None:
        user_profiles, _ = load_user_profiles(directory)
        for profile in user_profiles:
            profiles.setdefault(profile.id, profile)
    return tuple(profiles.values())
