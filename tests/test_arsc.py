"""Тесты разбора resources.arsc.

Бинарная таблица собирается в ``tests/arsc_fixture.py``: так проверка
не зависит от внешних файлов и от версии aapt.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from china_auto_rus.core.arsc import (
    DEFAULT_LANGUAGE,
    ArscTable,
    parse_arsc,
    parse_string_pool,
)
from china_auto_rus.core.resources import extract_from_zip
from tests.arsc_fixture import (
    build_package,
    build_sample,
    build_string_pool,
    build_table,
    build_type_chunk,
)


def test_parse_string_pool_utf8() -> None:
    pool = build_string_pool(["设置", "开始导航"])

    assert parse_string_pool(pool, 0) == ["设置", "开始导航"]


def test_parse_string_pool_utf16() -> None:
    pool = build_string_pool(["设置", "Settings"], utf8=False)

    assert parse_string_pool(pool, 0) == ["设置", "Settings"]


def test_parse_string_pool_decodes_four_byte_utf8() -> None:
    pool = build_string_pool(["🎉 поздравляем"])

    assert parse_string_pool(pool, 0) == ["🎉 поздравляем"]


def test_parse_arsc_extracts_strings_with_language() -> None:
    table = parse_arsc(build_sample())

    assert isinstance(table, ArscTable)
    assert table.package == "com.deepal.settings"

    values = {(entry.resource, entry.language): entry.text for entry in table.entries}
    assert values[("string/settings_title", "zh-CN")] == "设置"
    assert values[("string/nav_start", "zh-CN")] == "开始导航"
    assert values[("string/settings_title", "ru")] == "Настройки"


def test_parse_arsc_utf16_pool() -> None:
    table = parse_arsc(build_sample(utf8=False))

    texts = {entry.text for entry in table.entries}
    assert "设置" in texts
    assert "Настройки" in texts


def test_parse_arsc_offset16_entries() -> None:
    table = parse_arsc(build_sample(offset16=True))

    texts = {entry.text for entry in table.entries}
    assert texts == {"设置", "开始导航", "Настройки"}


def test_parse_arsc_compact_entries() -> None:
    table = parse_arsc(build_sample(compact=True))

    values = {(entry.resource, entry.language): entry.text for entry in table.entries}
    assert values[("string/settings_title", "zh-CN")] == "设置"
    assert values[("string/nav_start", "zh-CN")] == "开始导航"


def test_parse_arsc_sparse_entries() -> None:
    table = parse_arsc(build_sample(sparse=True))

    texts = {entry.text for entry in table.entries}
    assert texts == {"设置", "开始导航", "Настройки"}


def test_parse_arsc_rejects_foreign_data() -> None:
    table = parse_arsc(b"not an arsc file at all")

    assert table.entries == ()
    assert "не resources.arsc" in table.notes[0]


def test_parse_arsc_handles_truncated_file() -> None:
    data = build_sample()[:60]

    table = parse_arsc(data)

    assert table.entries == ()


def test_extract_from_zip_reads_arsc(tmp_path: Path) -> None:
    target = tmp_path / "app.apk"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("resources.arsc", build_sample())

    files = extract_from_zip(target)

    assert files
    languages = {item.language for item in files if item.entries}
    assert languages == {"zh-CN", "ru"}
    texts = {entry.text for item in files for entry in item.entries}
    assert "设置" in texts


def test_default_language_is_used_for_empty_config() -> None:
    global_pool = build_string_pool(["Hello"])
    type_pool = build_string_pool(["string"])
    key_pool = build_string_pool(["hello"])
    package = build_package(
        "com.example",
        type_pool,
        key_pool,
        [build_type_chunk({0: 0})],
    )

    table = parse_arsc(build_table(global_pool, package))

    assert table.entries[0].language == DEFAULT_LANGUAGE
