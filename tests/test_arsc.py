"""Тесты разбора resources.arsc.

Бинарная таблица собирается прямо в тесте: так проверка не зависит
от внешних файлов и от версии aapt.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

from china_auto_rus.core.arsc import (
    DEFAULT_LANGUAGE,
    ArscTable,
    parse_arsc,
    parse_string_pool,
)
from china_auto_rus.core.resources import extract_from_zip

TABLETYPE_STRING = 0x0001
TABLETYPE_TABLE = 0x0002
TABLETYPE_PACKAGE = 0x0200
TABLETYPE_TYPE = 0x0201


def _pad(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - len(data) % 4) % 4)


def _length8(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    return bytes([0x80 | (value >> 8), value & 0xFF])


def build_string_pool(strings: list[str], *, utf8: bool = True) -> bytes:
    offsets: list[int] = []
    data = bytearray()

    for text in strings:
        offsets.append(len(data))
        if utf8:
            raw = text.encode("utf-8")
            data += _length8(len(text.encode("utf-16-le")) // 2)
            data += _length8(len(raw))
            data += raw + b"\x00"
        else:
            data += struct.pack("<H", len(text)) + text.encode("utf-16-le")

    data = bytearray(_pad(bytes(data)))
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    size = strings_start + len(data)
    header = struct.pack(
        "<HHIIIIII",
        TABLETYPE_STRING,
        header_size,
        size,
        len(strings),
        0,
        0x100 if utf8 else 0,
        strings_start,
        0,
    )
    offsets_bytes = b"".join(struct.pack("<I", value) for value in offsets)
    return header + offsets_bytes + bytes(data)


def build_type_chunk(
    entries: dict[int, int],
    *,
    type_id: int = 1,
    language: str = "",
    country: str = "",
    offset16: bool = False,
) -> bytes:
    entry_count = max(entries) + 1
    payload = bytearray()
    offsets: list[int] = []

    for index in range(entry_count):
        value = entries.get(index)
        if value is None:
            offsets.append(0xFFFF if offset16 else 0xFFFFFFFF)
            continue
        offsets.append(len(payload) // 4 if offset16 else len(payload))
        payload += struct.pack("<HHI", 8, 0, index)
        payload += struct.pack("<HBBI", 8, 0, 0x03, value)

    payload = bytearray(_pad(bytes(payload)))
    config_size = 64
    header_size = 20 + config_size
    entries_start = header_size + (2 if offset16 else 4) * entry_count
    size = entries_start + len(payload)

    config = struct.pack("<I", config_size) + b"\x00" * 4
    config += language.encode("ascii").ljust(2, b"\x00")[:2]
    config += country.encode("ascii").ljust(2, b"\x00")[:2]
    config = config.ljust(config_size, b"\x00")

    flags = 0x02 if offset16 else 0
    header = struct.pack(
        "<HHIBBHII",
        TABLETYPE_TYPE,
        header_size,
        size,
        type_id,
        flags,
        0,
        entry_count,
        entries_start,
    )
    if offset16:
        offsets_bytes = b"".join(struct.pack("<H", value) for value in offsets)
    else:
        offsets_bytes = b"".join(struct.pack("<I", value) for value in offsets)
    return header + config + offsets_bytes + bytes(payload)


def build_package(
    name: str,
    type_pool: bytes,
    key_pool: bytes,
    type_chunks: list[bytes],
) -> bytes:
    header_size = 288
    body = type_pool + key_pool + b"".join(type_chunks)
    size = header_size + len(body)
    header = struct.pack("<HHII", TABLETYPE_PACKAGE, header_size, size, 0x7F)
    header += name.encode("utf-16-le")[:256].ljust(256, b"\x00")
    header += struct.pack("<IIII", header_size, 1, header_size + len(type_pool), 1)
    header += struct.pack("<I", 0)
    return header + body


def build_table(global_pool: bytes, package: bytes) -> bytes:
    header_size = 12
    size = header_size + len(global_pool) + len(package)
    header = struct.pack("<HHII", TABLETYPE_TABLE, header_size, size, 1)
    return header + global_pool + package


def build_sample(
    *, utf8: bool = True, offset16: bool = False
) -> bytes:
    global_pool = build_string_pool(
        ["设置", "开始导航", "Настройки"], utf8=utf8
    )
    type_pool = build_string_pool(["string"], utf8=utf8)
    key_pool = build_string_pool(["settings_title", "nav_start"], utf8=utf8)
    default_type = build_type_chunk(
        {0: 0, 1: 1}, language="zh", country="CN", offset16=offset16
    )
    russian_type = build_type_chunk(
        {0: 2}, language="ru", country="", offset16=offset16
    )
    package = build_package("com.deepal.settings", type_pool, key_pool, [
        default_type,
        russian_type,
    ])
    return build_table(global_pool, package)


def test_parse_string_pool_utf8() -> None:
    pool = build_string_pool(["设置", "开始导航"])

    assert parse_string_pool(pool, 0) == ["设置", "开始导航"]


def test_parse_string_pool_utf16() -> None:
    pool = build_string_pool(["设置", "Settings"], utf8=False)

    assert parse_string_pool(pool, 0) == ["设置", "Settings"]


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
