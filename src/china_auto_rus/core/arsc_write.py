"""Запись ``resources.arsc``: замена строк без пересборки структуры.

Модуль меняет только глобальный пул строк и индексы строковых значений.
Заголовки, пакеты, спецификации типов, составные записи и стили остаются
байт-в-байт: это условие, при котором пересобранный APK не разваливается.

Функции чистые: на вход байты, на выходе новые байты. Оригинал не меняется.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from china_auto_rus.core.arsc import (
    MAX_ARSC_BYTES,
    RES_STRING_POOL_TYPE,
    RES_TABLE_PACKAGE_TYPE,
    RES_TABLE_TYPE,
    RES_TABLE_TYPE_TYPE,
    ArscError,
    parse_string_pool,
)

_POOL_HEADER_SIZE = 28
_TABLE_HEADER_SIZE = 12
_UTF8_FLAG = 0x100
_SORTED_FLAG = 0x0001
_TYPE_FLAG_SPARSE = 0x01
_TYPE_FLAG_OFFSET16 = 0x02
_ENTRY_FLAG_COMPLEX = 0x0001
_ENTRY_FLAG_COMPACT = 0x0008
_VALUE_TYPE_STRING = 0x03
_NO_ENTRY = 0xFFFFFFFF
_NO_ENTRY16 = 0xFFFF
_MAX_POOL_LENGTH = 0x7FFF


class ArscWriteError(Exception):
    """Таблицу нельзя безопасно пересобрать."""


@dataclass(frozen=True, slots=True)
class _Pool:
    """Глобальный пул строк вместе с блоками стилей."""

    strings: tuple[str, ...]
    utf8: bool
    flags: int
    style_offsets: bytes
    style_data: bytes

    @property
    def style_count(self) -> int:
        return len(self.style_offsets) // 4


@dataclass(frozen=True, slots=True)
class _Layout:
    """Разметка таблицы: заголовок, пул строк и всё, что после пула."""

    header_size: int
    table_size: int
    pool: _Pool
    pool_end: int
    tail: bytes


def _require(data: bytes | bytearray, offset: int, size: int, what: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ArscWriteError(f"{what} выходит за границы файла")


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - len(data) % 4) % 4)


def _encode_utf8_pool(text: str) -> bytes:
    """Кодирует строку так же, как aapt: BMP — UTF-8, вне BMP — CESU-8."""
    units = text.encode("utf-16-le")
    encoded = bytearray()
    for index in range(0, len(units), 2):
        unit = units[index] | (units[index + 1] << 8)
        if unit < 0x80:
            encoded.append(unit)
        elif unit < 0x800:
            encoded.append(0xC0 | (unit >> 6))
            encoded.append(0x80 | (unit & 0x3F))
        else:
            encoded.append(0xE0 | (unit >> 12))
            encoded.append(0x80 | ((unit >> 6) & 0x3F))
            encoded.append(0x80 | (unit & 0x3F))
    return bytes(encoded)


def _encode_length8(value: int) -> bytes:
    if value < 0:
        raise ArscWriteError("отрицательная длина строки")
    if value > _MAX_POOL_LENGTH:
        raise ArscWriteError("строка длиннее 32767 единиц — так не умеет и aapt")
    if value < 0x80:
        return bytes([value])
    return bytes([0x80 | (value >> 8), value & 0xFF])


def _encode_length16(value: int) -> bytes:
    if value < 0:
        raise ArscWriteError("отрицательная длина строки")
    if value < 0x8000:
        return struct.pack("<H", value)
    return struct.pack("<HH", 0x8000 | (value >> 16), value & 0xFFFF)


def write_string_pool(
    strings: Sequence[str],
    *,
    utf8: bool = True,
    flags: int = 0,
    style_offsets: bytes = b"",
    style_data: bytes = b"",
) -> bytes:
    """Собирает ``RES_STRING_POOL_TYPE`` из списка строк.

    ``style_offsets`` — массив смещений стилей, ``style_data`` — сами спаны.
    Оба блока берутся из оригинала как есть: их смещения относительны,
    поэтому пересборка строк их не ломает.
    """
    if len(style_offsets) % 4 != 0:
        raise ArscWriteError("блок смещений стилей не кратен 4 байтам")

    style_count = len(style_offsets) // 4
    body = bytearray()
    offsets: list[int] = []

    for text in strings:
        offsets.append(len(body))
        if utf8:
            raw = _encode_utf8_pool(text)
            body += _encode_length8(len(text.encode("utf-16-le")) // 2)
            body += _encode_length8(len(raw))
            body += raw + b"\x00"
        else:
            raw = text.encode("utf-16-le")
            body += _encode_length16(len(raw) // 2)
            body += raw + b"\x00\x00"

    body = bytearray(_pad4(bytes(body)))
    strings_start = _POOL_HEADER_SIZE + 4 * len(strings) + 4 * style_count
    styles_start = strings_start + len(body) if style_count else 0
    size = strings_start + len(body) + len(style_data)

    pool_flags = (flags & ~_UTF8_FLAG) | (_UTF8_FLAG if utf8 else 0)
    header = struct.pack(
        "<HHIIIIII",
        RES_STRING_POOL_TYPE,
        _POOL_HEADER_SIZE,
        size,
        len(strings),
        style_count,
        pool_flags,
        strings_start,
        styles_start,
    )
    offsets_bytes = struct.pack(f"<{len(offsets)}I", *offsets) if offsets else b""
    return header + offsets_bytes + style_offsets + bytes(body) + style_data


def _read_pool(data: bytes, offset: int) -> tuple[_Pool, int]:
    _require(data, offset, _POOL_HEADER_SIZE, "пул строк")
    chunk_type, header_size, size = struct.unpack_from("<HHI", data, offset)
    if chunk_type != RES_STRING_POOL_TYPE:
        raise ArscWriteError(f"ожидался пул строк, найден тип 0x{chunk_type:04x}")
    if header_size < _POOL_HEADER_SIZE or size < header_size or offset + size > len(data):
        raise ArscWriteError("некорректный заголовок пула строк")

    count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<IIIII", data, offset + 8
    )
    if style_count > count:
        raise ArscWriteError("блоков стилей больше, чем строк")
    if header_size + 4 * count + 4 * style_count > size:
        raise ArscWriteError("таблица смещений строк не помещается в пул")
    if count and not (header_size + 4 * count + 4 * style_count <= strings_start <= size):
        raise ArscWriteError("некорректное начало данных строк")
    if style_count and not (strings_start < styles_start <= size):
        raise ArscWriteError("некорректное начало блока стилей")

    try:
        strings = tuple(parse_string_pool(data, offset))
    except ArscError as error:
        raise ArscWriteError(f"пул строк повреждён: {error}") from error
    if any("\ufffd" in text for text in strings):
        # Пересборка заменила бы битые байты на U+FFFD, то есть испортила бы
        # пул. Лучше отказаться, чем молча испортить APK.
        raise ArscWriteError("в пуле есть строки, которые не декодируются")

    styles_area = header_size + 4 * count
    style_offsets = data[offset + styles_area : offset + styles_area + 4 * style_count]
    style_data = data[offset + styles_start : offset + size] if style_count else b""
    pool = _Pool(strings, bool(flags & _UTF8_FLAG), flags, style_offsets, style_data)
    return pool, offset + size


def _layout(data: bytes) -> _Layout:
    if len(data) > MAX_ARSC_BYTES:
        raise ArscWriteError(f"файл больше {MAX_ARSC_BYTES} байт")
    _require(data, 0, _TABLE_HEADER_SIZE, "заголовок таблицы")
    chunk_type, header_size, size = struct.unpack_from("<HHI", data, 0)
    if chunk_type != RES_TABLE_TYPE:
        raise ArscWriteError("это не resources.arsc")
    if header_size < _TABLE_HEADER_SIZE or size < header_size or size > len(data):
        raise ArscWriteError("некорректный размер таблицы")

    pool, pool_end = _read_pool(data, header_size)
    return _Layout(header_size, size, pool, pool_end, data[pool_end:size])


def _assemble(header_source: bytes, header_size: int, pool_bytes: bytes, tail: bytes) -> bytes:
    header = bytearray(header_source[:header_size])
    struct.pack_into("<I", header, 4, header_size + len(pool_bytes) + len(tail))
    return bytes(header) + pool_bytes + tail


def rebuild_arsc(data: bytes) -> bytes:
    """Пересобирает глобальный пул строк, сохраняя порядок и стили.

    Нужен для проверки writer'а: разбор результата обязан совпасть с разбором
    оригинала. Это же операция, которую делает замена строк.
    """
    layout = _layout(data)
    pool_bytes = write_string_pool(
        layout.pool.strings,
        utf8=layout.pool.utf8,
        flags=layout.pool.flags,
        style_offsets=layout.pool.style_offsets,
        style_data=layout.pool.style_data,
    )
    return _assemble(data, layout.header_size, pool_bytes, layout.tail)


def _iter_chunks(
    data: bytes | bytearray, start: int, end: int
) -> Iterator[tuple[int, int, int, int]]:
    position = start
    while position + 8 <= end:
        chunk_type, header_size, size = struct.unpack_from("<HHI", data, position)
        if header_size < 8 or size < header_size or position + size > end:
            raise ArscWriteError(f"некорректный чанк по смещению {position}")
        yield position, chunk_type, header_size, size
        position += size


def _patch_entry(buffer: bytearray, position: int, remap: Mapping[int, int]) -> None:
    _require(buffer, position, 8, "запись ресурса")
    entry_size, entry_flags = struct.unpack_from("<HH", buffer, position)
    if entry_flags & _ENTRY_FLAG_COMPLEX:
        return

    if entry_flags & _ENTRY_FLAG_COMPACT:
        value_type = (entry_flags >> 8) & 0xFF
        if value_type != _VALUE_TYPE_STRING:
            return
        current = struct.unpack_from("<I", buffer, position + 4)[0]
        if current in remap:
            struct.pack_into("<I", buffer, position + 4, remap[current])
        return

    if entry_size < 8:
        return
    value_position = position + entry_size
    _require(buffer, value_position, 8, "значение ресурса")
    _value_size, _res0, value_type, current = struct.unpack_from(
        "<HBBI", buffer, value_position
    )
    if value_type != _VALUE_TYPE_STRING:
        return
    if current in remap:
        struct.pack_into("<I", buffer, value_position + 4, remap[current])


def _patch_type_chunk(
    buffer: bytearray,
    offset: int,
    header_size: int,
    size: int,
    remap: Mapping[int, int],
) -> None:
    flags = buffer[offset + 9]
    entry_count, entries_start = struct.unpack_from("<II", buffer, offset + 12)
    entries_base = offset + entries_start
    offsets_position = offset + header_size

    if flags & _TYPE_FLAG_SPARSE:
        _require(buffer, offsets_position, 4 * entry_count, "разреженные смещения")
        for index in range(entry_count):
            _entry_index, entry_offset = struct.unpack_from(
                "<HH", buffer, offsets_position + index * 4
            )
            _patch_entry(buffer, entries_base + entry_offset * 4, remap)
        return

    if flags & _TYPE_FLAG_OFFSET16:
        _require(buffer, offsets_position, 2 * entry_count, "16-битные смещения")
        for index in range(entry_count):
            entry_offset = struct.unpack_from("<H", buffer, offsets_position + index * 2)[0]
            if entry_offset == _NO_ENTRY16:
                continue
            _patch_entry(buffer, entries_base + entry_offset * 4, remap)
        return

    _require(buffer, offsets_position, 4 * entry_count, "смещения записей")
    for index in range(entry_count):
        entry_offset = struct.unpack_from("<I", buffer, offsets_position + index * 4)[0]
        if entry_offset == _NO_ENTRY:
            continue
        _patch_entry(buffer, entries_base + entry_offset, remap)


def _patch_packages(buffer: bytearray, layout: _Layout, remap: Mapping[int, int]) -> None:
    for offset, chunk_type, header_size, size in _iter_chunks(
        buffer, layout.pool_end, layout.table_size
    ):
        if chunk_type != RES_TABLE_PACKAGE_TYPE:
            continue
        for inner_offset, inner_type, inner_header, inner_size in _iter_chunks(
            buffer, offset + header_size, offset + size
        ):
            if inner_type == RES_TABLE_TYPE_TYPE:
                _patch_type_chunk(buffer, inner_offset, inner_header, inner_size, remap)


def replace_strings(data: bytes, replacements: Mapping[str, str]) -> bytes:
    """Заменяет строки по тексту, дописывая новые значения в пул.

    Совпавшие строки получают новый индекс, остальные байты таблицы остаются
    на месте. Пустая карта возвращает исходные байты без изменений.
    """
    if not replacements:
        return data

    layout = _layout(data)
    pool = layout.pool

    positions: dict[str, int] = {}
    for index, text in enumerate(pool.strings):
        positions.setdefault(text, index)

    new_strings = list(pool.strings)
    remap: dict[int, int] = {}
    for index, text in enumerate(pool.strings):
        target = replacements.get(text)
        if target is None or target == text:
            continue
        new_index = positions.get(target)
        if new_index is None:
            new_index = len(new_strings)
            new_strings.append(target)
            positions[target] = new_index
        remap[index] = new_index

    if not remap:
        return data

    patched = bytearray(data)
    _patch_packages(patched, layout, remap)

    # Порядок строк изменён, флаг «отсортировано» больше не соответствует
    # содержимому пула. Если его оставить, поиск может вернуть чужую строку.
    pool_bytes = write_string_pool(
        new_strings,
        utf8=pool.utf8,
        flags=pool.flags & ~_SORTED_FLAG,
        style_offsets=pool.style_offsets,
        style_data=pool.style_data,
    )
    return _assemble(
        bytes(patched), layout.header_size, pool_bytes, bytes(patched[layout.pool_end :])
    )
