"""Профили автомобилей: данные отдельно от логики.

Публичный интерфейс пакета:

* :class:`CarProfile` — описание машины;
* :func:`default_profile` — профиль по умолчанию;
* :func:`find_profile` / :func:`get_profile` — поиск по ``id``;
* :func:`available_profiles` — все профили, включая пользовательские.
"""

from china_auto_rus.profiles.car import (
    CarProfile,
    ProfileError,
    profile_from_mapping,
    profile_to_mapping,
)
from china_auto_rus.profiles.registry import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
    ProfileLoadError,
    available_profiles,
    default_profile,
    find_profile,
    get_profile,
    load_user_profiles,
    resolve_profile,
)

__all__ = [
    "BUILTIN_PROFILES",
    "DEFAULT_PROFILE_ID",
    "CarProfile",
    "ProfileError",
    "ProfileLoadError",
    "available_profiles",
    "default_profile",
    "find_profile",
    "get_profile",
    "load_user_profiles",
    "profile_from_mapping",
    "profile_to_mapping",
    "resolve_profile",
]
