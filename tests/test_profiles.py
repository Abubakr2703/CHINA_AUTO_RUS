"""Тесты профилей автомобилей: валидация, реестр, пользовательские JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from china_auto_rus.profiles import (
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
    CarProfile,
    ProfileError,
    available_profiles,
    default_profile,
    find_profile,
    get_profile,
    load_user_profiles,
    profile_from_mapping,
    profile_to_mapping,
    resolve_profile,
)


def profile_json(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "my-car-2025-cn",
        "brand": "Changan",
        "model": "CS55 Plus",
        "year": 2025,
        "market": "CN",
    }
    payload.update(overrides)
    return payload


def get_profile_in(profiles: tuple[CarProfile, ...], profile_id: str) -> CarProfile:
    return next(profile for profile in profiles if profile.id == profile_id)


def test_default_profile_is_deepal_s07() -> None:
    profile = default_profile()

    assert profile.id == DEFAULT_PROFILE_ID
    assert profile.brand == "Changan"
    assert profile.model == "Deepal S07"
    assert profile.year == 2026
    assert profile.market == "CN"


def test_unknown_characteristics_stay_unknown() -> None:
    profile = default_profile()

    assert profile.head_unit is None
    assert profile.hardware_platform is None


def test_display_name() -> None:
    assert default_profile().display_name == "Changan Deepal S07 2026 (CN)"


def test_default_profile_is_in_builtin_registry() -> None:
    assert DEFAULT_PROFILE_ID in {profile.id for profile in BUILTIN_PROFILES}


def test_id_must_be_slug() -> None:
    with pytest.raises(ProfileError, match="id"):
        CarProfile("Bad Id", "Changan", "Deepal S07", 2026, "CN")


def test_year_range_is_checked() -> None:
    with pytest.raises(ProfileError, match="год"):
        CarProfile("x", "Changan", "Deepal S07", 1800, "CN")
    with pytest.raises(ProfileError, match="год"):
        CarProfile("x", "Changan", "Deepal S07", 3000, "CN")


def test_market_must_be_two_letters() -> None:
    with pytest.raises(ProfileError, match="market"):
        CarProfile("x", "Changan", "Deepal S07", 2026, "china")


def test_required_fields_are_not_empty() -> None:
    with pytest.raises(ProfileError, match="brand"):
        CarProfile("x", "  ", "Deepal S07", 2026, "CN")


def test_mapping_roundtrip() -> None:
    profile = default_profile()

    assert profile_from_mapping(profile_to_mapping(profile)) == profile


def test_mapping_requires_year() -> None:
    payload = profile_json()
    del payload["year"]

    with pytest.raises(ProfileError, match="year"):
        profile_from_mapping(payload)


def test_mapping_rejects_wrong_year_type() -> None:
    with pytest.raises(ProfileError, match="year"):
        profile_from_mapping(profile_json(year="2025"))


def test_mapping_error_mentions_origin() -> None:
    with pytest.raises(ProfileError, match="car.json"):
        profile_from_mapping(profile_json(year=0), origin="car.json")


def test_mapping_ignores_unknown_fields() -> None:
    profile = profile_from_mapping(profile_json(vin="LS6C3E2SXTF004308"))

    assert profile.id == "my-car-2025-cn"


def test_find_and_get_profile() -> None:
    assert find_profile(DEFAULT_PROFILE_ID) is default_profile()
    assert find_profile("nope") is None

    with pytest.raises(KeyError, match="nope"):
        get_profile("nope")


def test_load_user_profiles(tmp_path: Path) -> None:
    (tmp_path / "my_car.json").write_text(
        json.dumps(profile_json(), ensure_ascii=False), encoding="utf-8"
    )

    profiles, errors = load_user_profiles(tmp_path)

    assert errors == ()
    assert [profile.id for profile in profiles] == ["my-car-2025-cn"]


def test_broken_profile_does_not_break_others(tmp_path: Path) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    (tmp_path / "wrong_type.json").write_text(
        json.dumps(profile_json(id="other", year="2025")), encoding="utf-8"
    )
    (tmp_path / "good.json").write_text(
        json.dumps(profile_json()), encoding="utf-8"
    )

    profiles, errors = load_user_profiles(tmp_path)

    assert [profile.id for profile in profiles] == ["my-car-2025-cn"]
    assert {error.path.name for error in errors} == {"broken.json", "wrong_type.json"}
    assert all(error.message for error in errors)


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert load_user_profiles(tmp_path / "nope") == ((), ())


def test_user_profile_cannot_override_builtin(tmp_path: Path) -> None:
    (tmp_path / "fake.json").write_text(
        json.dumps(profile_json(id=DEFAULT_PROFILE_ID, brand="Fake")),
        encoding="utf-8",
    )

    profiles = available_profiles(tmp_path)

    assert get_profile_in(profiles, DEFAULT_PROFILE_ID).brand == "Changan"


def test_available_profiles_include_user_entries(tmp_path: Path) -> None:
    (tmp_path / "my_car.json").write_text(
        json.dumps(profile_json()), encoding="utf-8"
    )

    ids = [profile.id for profile in available_profiles(tmp_path)]

    assert ids == [DEFAULT_PROFILE_ID, "my-car-2025-cn"]


def test_resolve_profile_reads_user_directory(tmp_path: Path) -> None:
    (tmp_path / "my_car.json").write_text(
        json.dumps(profile_json()), encoding="utf-8"
    )

    assert resolve_profile(DEFAULT_PROFILE_ID, tmp_path) is default_profile()
    assert resolve_profile("my-car-2025-cn", tmp_path) is not None
    assert resolve_profile("my-car-2025-cn") is None
    assert resolve_profile("nope", tmp_path) is None
