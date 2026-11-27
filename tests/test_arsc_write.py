"""Тесты записи resources.arsc: пул строк и замена значений."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from china_auto_rus.core.arsc import parse_arsc, parse_string_pool
from china_auto_rus.core.arsc_write import (
    ArscWriteError,
    rebuild_arsc,
    replace_strings,
    write_string_pool,
)
from tests.arsc_fixture import build_sample

POOL_STRINGS = ["", "短", "a" * 200, "😀 emoji", "中文" * 100]


def _pool_header(data: bytes, offset: int = 12) -> tuple[int, int, int, int]:
    # Заголовок таблицы — 12 байт, пул строк идёт сразу за ним.
    count, style_count, flags, strings_start = struct.unpack_from("<IIII", data, offset + 8)
    return count, style_count, flags, strings_start


def _tail(data: bytes) -> bytes:
    pool_size = struct.unpack_from("<I", data, 16)[0]
    return data[12 + pool_size :]


def test_write_string_pool_utf8_round_trip() -> None:
    pool = write_string_pool(POOL_STRINGS)

    assert parse_string_pool(pool, 0) == POOL_STRINGS
    assert len(pool) % 4 == 0


def test_write_string_pool_utf16_round_trip() -> None:
    pool = write_string_pool(POOL_STRINGS, utf8=False)

    assert parse_string_pool(pool, 0) == POOL_STRINGS
    assert _pool_header(pool, 0)[2] & 0x100 == 0


def test_write_string_pool_uses_cesu8_for_astral() -> None:
    pool = write_string_pool(["🎉"])

    assert parse_string_pool(pool, 0) == ["🎉"]
    # Вне BMP aapt пишет суррогатную пару двумя трёхбайтовыми блоками.
    assert b"\xed\xa0\xbc\xed\xbe\x89" in pool


def test_write_string_pool_keeps_styles() -> None:
    style_offsets = struct.pack("<I", 0)
    style_data = struct.pack("<IIII", 2, 0, 1, 0xFFFFFFFF)

    pool = write_string_pool(
        ["设置"], style_offsets=style_offsets, style_data=style_data
    )

    count, style_count, _flags, strings_start = _pool_header(pool, 0)
    styles_start = struct.unpack_from("<I", pool, 24)[0]
    assert (count, style_count) == (1, 1)
    assert parse_string_pool(pool, 0) == ["设置"]
    assert style_count == 1
    assert strings_start < styles_start
    assert pool[styles_start:] == style_data


def test_write_string_pool_rejects_oversized_string() -> None:
    with pytest.raises(ArscWriteError):
        write_string_pool(["x" * 40000])


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"utf8": False},
        {"offset16": True},
        {"compact": True},
        {"sparse": True},
        {"offset16": True, "compact": True},
    ],
)
def test_rebuild_arsc_matches_parsed_model(options: dict[str, Any]) -> None:
    original = build_sample(**options)

    rebuilt = rebuild_arsc(original)

    assert parse_arsc(rebuilt) == parse_arsc(original)
    assert len(rebuilt) == struct.unpack_from("<I", rebuilt, 4)[0]


def test_rebuild_arsc_keeps_package_bytes() -> None:
    original = build_sample()

    rebuilt = rebuild_arsc(original)

    assert _tail(rebuilt) == _tail(original)


def test_rebuild_arsc_is_byte_identical() -> None:
    original = build_sample()

    assert rebuild_arsc(original) == original


def test_replace_strings_translates_matching_values() -> None:
    original = build_sample()

    result = replace_strings(original, {"设置": "Параметры"})

    values = {(entry.resource, entry.language): entry.text for entry in parse_arsc(result).entries}
    assert values[("string/settings_title", "zh-CN")] == "Параметры"
    assert values[("string/nav_start", "zh-CN")] == "开始导航"
    assert values[("string/settings_title", "ru")] == "Настройки"


def test_replace_strings_reuses_existing_value() -> None:
    original = build_sample()
    count_before = _pool_header(original)[0]

    result = replace_strings(original, {"设置": "Настройки"})

    assert _pool_header(result)[0] == count_before
    assert "Настройки" in {entry.text for entry in parse_arsc(result).entries}


def test_replace_strings_appends_new_value() -> None:
    original = build_sample()
    count_before = _pool_header(original)[0]

    result = replace_strings(original, {"设置": "Параметры"})

    assert _pool_header(result)[0] == count_before + 1


def test_replace_strings_without_matches_returns_input() -> None:
    original = build_sample()

    assert replace_strings(original, {"нет такой строки": "x"}) == original


def test_replace_strings_clears_sorted_flag() -> None:
    original = build_sample(pool_flags=0x1)

    result = replace_strings(original, {"设置": "Параметры"})

    assert _pool_header(result)[2] & 0x1 == 0


@pytest.mark.parametrize(
    "options",
    [
        {"offset16": True},
        {"compact": True},
        {"sparse": True},
        {"offset16": True, "compact": True},
        {"utf8": False},
    ],
)
def test_replace_strings_supports_entry_layouts(options: dict[str, Any]) -> None:
    original = build_sample(**options)

    result = replace_strings(original, {"设置": "Параметры"})

    values = {(entry.resource, entry.language): entry.text for entry in parse_arsc(result).entries}
    assert values[("string/settings_title", "zh-CN")] == "Параметры"
    assert values[("string/settings_title", "ru")] == "Настройки"


def test_replace_strings_survives_repeated_pass() -> None:
    original = build_sample()

    once = replace_strings(original, {"设置": "Параметры"})
    twice = replace_strings(once, {"Параметры": "Настройки"})

    values = {(entry.resource, entry.language): entry.text for entry in parse_arsc(twice).entries}
    assert values[("string/settings_title", "zh-CN")] == "Настройки"


def test_rebuild_rejects_foreign_data() -> None:
    with pytest.raises(ArscWriteError):
        rebuild_arsc(b"not an arsc file")


def test_rebuild_rejects_truncated_table() -> None:
    with pytest.raises(ArscWriteError):
        rebuild_arsc(build_sample()[:60])
