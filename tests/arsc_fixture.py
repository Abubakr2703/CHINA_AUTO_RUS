"""Сборщики синтетической ``resources.arsc`` для тестов.

Таблица собирается в памяти: проверки не зависят от внешних файлов
и от версии aapt.
"""

from __future__ import annotations

import struct

TABLE_STRING = 0x0001
TABLE_TABLE = 0x0002
TABLE_PACKAGE = 0x0200
TABLE_TYPE = 0x0201


def _pad(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - len(data) % 4) % 4)


def _length8(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    return bytes([0x80 | (value >> 8), value & 0xFF])


def build_string_pool(
    strings: list[str],
    *,
    utf8: bool = True,
    flags: int = 0,
    style_offsets: bytes = b"",
    style_data: bytes = b"",
) -> bytes:
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
            raw = text.encode("utf-16-le")
            data += struct.pack("<H", len(raw) // 2) + raw + b"\x00\x00"

    data = bytearray(_pad(bytes(data)))
    style_count = len(style_offsets) // 4
    header_size = 28
    strings_start = header_size + 4 * len(strings) + 4 * style_count
    styles_start = strings_start + len(data) if style_count else 0
    size = strings_start + len(data) + len(style_data)
    header = struct.pack(
        "<HHIIIIII",
        TABLE_STRING,
        header_size,
        size,
        len(strings),
        style_count,
        flags | (0x100 if utf8 else 0),
        strings_start,
        styles_start,
    )
    offsets_bytes = b"".join(struct.pack("<I", value) for value in offsets)
    return header + offsets_bytes + style_offsets + bytes(data) + style_data


def build_type_chunk(
    entries: dict[int, int],
    *,
    type_id: int = 1,
    language: str = "",
    country: str = "",
    offset16: bool = False,
    compact: bool = False,
    sparse: bool = False,
) -> bytes:
    payload = bytearray()
    sparse_offsets: list[tuple[int, int]] = []
    dense_offsets: list[int] = []
    entry_count = len(entries) if sparse else max(entries) + 1

    for index in range(entry_count):
        value = entries.get(index)
        if value is None:
            if not sparse:
                dense_offsets.append(0xFFFF if offset16 else 0xFFFFFFFF)
            continue

        if sparse:
            sparse_offsets.append((index, len(payload) // 4))
        else:
            dense_offsets.append(len(payload) // 4 if offset16 else len(payload))

        if compact:
            payload += struct.pack("<HHI", index, 0x0008 | (0x03 << 8), value)
        else:
            payload += struct.pack("<HHI", 8, 0, index)
            payload += struct.pack("<HBBI", 8, 0, 0x03, value)

    payload = bytearray(_pad(bytes(payload)))
    config_size = 64
    header_size = 20 + config_size
    if sparse:
        offsets_size = 4 * entry_count
        offsets_bytes = b"".join(
            struct.pack("<HH", index, offset) for index, offset in sparse_offsets
        )
    elif offset16:
        offsets_size = 2 * entry_count
        offsets_bytes = b"".join(struct.pack("<H", value) for value in dense_offsets)
    else:
        offsets_size = 4 * entry_count
        offsets_bytes = b"".join(struct.pack("<I", value) for value in dense_offsets)
    entries_start = header_size + offsets_size
    size = entries_start + len(payload)

    config = struct.pack("<I", config_size) + b"\x00" * 4
    config += language.encode("ascii").ljust(2, b"\x00")[:2]
    config += country.encode("ascii").ljust(2, b"\x00")[:2]
    config = config.ljust(config_size, b"\x00")

    flags = 0x01 if sparse else (0x02 if offset16 else 0)
    header = struct.pack(
        "<HHIBBHII",
        TABLE_TYPE,
        header_size,
        size,
        type_id,
        flags,
        0,
        entry_count,
        entries_start,
    )
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
    header = struct.pack("<HHII", TABLE_PACKAGE, header_size, size, 0x7F)
    header += name.encode("utf-16-le")[:256].ljust(256, b"\x00")
    header += struct.pack("<IIII", header_size, 1, header_size + len(type_pool), 1)
    header += struct.pack("<I", 0)
    return header + body


def build_table(global_pool: bytes, package: bytes) -> bytes:
    header_size = 12
    size = header_size + len(global_pool) + len(package)
    header = struct.pack("<HHII", TABLE_TABLE, header_size, size, 1)
    return header + global_pool + package


def build_sample(
    *,
    utf8: bool = True,
    offset16: bool = False,
    compact: bool = False,
    sparse: bool = False,
    pool_flags: int = 0,
) -> bytes:
    global_pool = build_string_pool(["设置", "开始导航", "Настройки"], utf8=utf8, flags=pool_flags)
    type_pool = build_string_pool(["string"], utf8=utf8)
    key_pool = build_string_pool(["settings_title", "nav_start"], utf8=utf8)
    default_type = build_type_chunk(
        {0: 0, 1: 1},
        language="zh",
        country="CN",
        offset16=offset16,
        compact=compact,
        sparse=sparse,
    )
    russian_type = build_type_chunk(
        {0: 2},
        language="ru",
        country="",
        offset16=offset16,
        compact=compact,
        sparse=sparse,
    )
    package = build_package(
        "com.deepal.settings", type_pool, key_pool, [default_type, russian_type]
    )
    return build_table(global_pool, package)
