"""Разбор бинарной таблицы ресурсов Android (``resources.arsc``).

Формат: цепочка чанков ResChunk_header. Нам нужны три вида:

* ``RES_STRING_POOL_TYPE`` — пулы строк (глобальный, имён типов, ключей);
* ``RES_TABLE_PACKAGE_TYPE`` — пакет с ресурсами;
* ``RES_TABLE_TYPE_TYPE`` — записи конкретного типа и конфигурации,
  где конфигурация задаёт язык и регион.

Читаем только простые строковые значения. Составные (массивы, стили,
ссылки на другие ресурсы) пропускаются: подставить туда перевод нельзя,
не разобрав структуру.

Модуль ничего не пишет и не меняет: на вход байты, на выходе список строк.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from china_auto_rus.core.locale import DEFAULT_LANGUAGE, normalize_language

RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201
RES_TABLE_TYPE_SPEC_TYPE = 0x0202
RES_TABLE_LIBRARY_TYPE = 0x0203

# Флаги пула строк.
_UTF8_FLAG = 0x100

# Флаги записи типа: разреженная таблица и 16-битные смещения (aapt2).
_TYPE_FLAG_SPARSE = 0x01
_TYPE_FLAG_OFFSET16 = 0x02

# Флаг «запись составная»: дальше идёт ResTable_map_entry, а не Res_value.
_ENTRY_FLAG_COMPLEX = 0x0001
# Компактная запись (Android 12+): ключ, тип и значение упакованы в 8 байт.
_ENTRY_FLAG_COMPACT = 0x0008

# Тип значения «строка» в Res_value: индекс в глобальном пуле строк.
_VALUE_TYPE_STRING = 0x03
_NO_ENTRY = 0xFFFFFFFF
_NO_ENTRY16 = 0xFFFF

MAX_ARSC_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ArscEntry:
    """Одна строка ресурса: ``тип/ключ``, текст и язык конфигурации."""

    resource: str
    text: str
    language: str


@dataclass(frozen=True, slots=True)
class ArscTable:
    """Результат разбора: строки, имя пакета и замечания."""

    entries: tuple[ArscEntry, ...]
    package: str = ""
    notes: tuple[str, ...] = ()


class ArscError(Exception):
    """Таблица повреждена или не является resources.arsc."""


def _chunk(data: bytes, offset: int) -> tuple[int, int, int]:
    """Возвращает (тип, размер заголовка, полный размер) чанка."""
    if offset + 8 > len(data):
        raise ArscError("чанк выходит за границы файла")
    chunk_type, header_size, size = struct.unpack_from("<HHI", data, offset)
    if header_size < 8 or size < header_size or offset + size > len(data):
        raise ArscError(f"некорректный заголовок чанка по смещению {offset}")
    return chunk_type, header_size, size


def _read_length8(data: bytes, position: int) -> tuple[int, int]:
    """Длина строки в UTF-8-пуле: один или два байта."""
    first = data[position]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[position + 1], position + 2
    return first, position + 1


def _read_length16(data: bytes, position: int) -> tuple[int, int]:
    """Длина строки в UTF-16-пуле: одно или два слова."""
    first = struct.unpack_from("<H", data, position)[0]
    if first & 0x8000:
        second = struct.unpack_from("<H", data, position + 2)[0]
        return ((first & 0x7FFF) << 16) | second, position + 4
    return first, position + 2


def _decode_utf8_pool(raw: bytes) -> str:
    """Декодирует строку UTF-8-пула, включая CESU-8.

    aapt пишет символы вне BMP как две трёхбайтовые последовательности
    (CESU-8). Python такой поток считает недопустимым, поэтому surrogatepass
    плюс склейка пар вручную.
    """
    try:
        text = raw.decode("utf-8", "surrogatepass")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")

    chars: list[str] = []
    index = 0
    while index < len(text):
        high = text[index]
        if (
            "\ud800" <= high <= "\udbff"
            and index + 1 < len(text)
            and "\udc00" <= text[index + 1] <= "\udfff"
        ):
            low = text[index + 1]
            chars.append(
                chr(0x10000 + ((ord(high) - 0xD800) << 10) + (ord(low) - 0xDC00))
            )
            index += 2
        else:
            chars.append(high)
            index += 1
    return "".join(chars)


def parse_string_pool(data: bytes, offset: int) -> list[str]:
    """Читает пул строк — как UTF-8, так и UTF-16."""
    chunk_type, header_size, _ = _chunk(data, offset)
    if chunk_type != RES_STRING_POOL_TYPE:
        raise ArscError(f"ожидался пул строк, найден тип 0x{chunk_type:04x}")

    count, _style_count, flags, strings_start, _styles_start = struct.unpack_from(
        "<IIIII", data, offset + 8
    )
    if count == 0:
        return []

    offsets = struct.unpack_from(f"<{count}I", data, offset + header_size)
    utf8 = bool(flags & _UTF8_FLAG)
    base = offset + strings_start
    strings: list[str] = []

    for relative in offsets:
        position = base + relative
        if position >= len(data):
            strings.append("")
            continue
        if utf8:
            _utf16_length, position = _read_length8(data, position)
            byte_length, position = _read_length8(data, position)
            raw = data[position : position + byte_length]
            strings.append(_decode_utf8_pool(raw))
        else:
            char_length, position = _read_length16(data, position)
            raw = data[position : position + char_length * 2]
            strings.append(raw.decode("utf-16-le", "replace"))
    return strings


def _config_language(data: bytes, offset: int) -> str:
    """Язык из ResTable_config: ``ru``, ``zh-CN`` или ``default``."""
    size = struct.unpack_from("<I", data, offset)[0]
    if size < 12:
        return DEFAULT_LANGUAGE

    language = data[offset + 8 : offset + 10]
    country = data[offset + 10 : offset + 12]
    if language == b"\x00\x00":
        return DEFAULT_LANGUAGE
    # Трёхбуквенные языки упакованы в старший бит — их не разбираем.
    if language[0] & 0x80:
        return DEFAULT_LANGUAGE

    code = language.decode("ascii", "replace")
    if not code.isalpha():
        return DEFAULT_LANGUAGE

    region = country.decode("ascii", "replace").rstrip("\x00").lstrip("r")
    if region and region.isalpha():
        return normalize_language(f"{code}-{region.upper()}")
    return normalize_language(code)


def _entry_name(
    key_strings: list[str], type_names: list[str], type_id: int, key_index: int
) -> str:
    key = (
        key_strings[key_index]
        if key_index < len(key_strings)
        else f"0x{key_index:08x}"
    )
    type_name = (
        type_names[type_id - 1]
        if 0 < type_id <= len(type_names)
        else f"type{type_id}"
    )
    return f"{type_name}/{key}"


def _parse_entry_value(
    data: bytes, position: int, global_strings: list[str]
) -> tuple[str | None, int]:
    """Строковое значение записи и индекс её ключа.

    Компактная запись (``FLAG_COMPACT``) хранит ключ в поле размера, тип
    значения — в старшем байте флагов, а само значение — сразу за ними.
    """
    size, entry_flags, key_index = struct.unpack_from("<HHI", data, position)
    if entry_flags & _ENTRY_FLAG_COMPLEX:
        return None, key_index

    if entry_flags & _ENTRY_FLAG_COMPACT:
        value_type = (entry_flags >> 8) & 0xFF
        value_data = struct.unpack_from("<I", data, position + 4)[0]
        if value_type != _VALUE_TYPE_STRING or value_data >= len(global_strings):
            return None, size
        return global_strings[value_data], size

    value_position = position + size
    if value_position + 8 > len(data):
        return None, key_index
    _value_size, _res0, value_type, value_data = struct.unpack_from(
        "<HBBI", data, value_position
    )
    if value_type != _VALUE_TYPE_STRING or value_data >= len(global_strings):
        return None, key_index
    return global_strings[value_data], key_index


def _parse_type_chunk(
    data: bytes,
    offset: int,
    global_strings: list[str],
    key_strings: list[str],
    type_names: list[str],
) -> tuple[ArscEntry, ...]:
    """Читает записи одного типа для одной конфигурации."""
    _chunk_type, header_size, _size = _chunk(data, offset)
    type_id = data[offset + 8]
    flags = data[offset + 9]
    entry_count, entries_start = struct.unpack_from("<II", data, offset + 12)
    language = _config_language(data, offset + 20)
    entries_base = offset + entries_start
    offsets_position = offset + header_size
    collected: list[ArscEntry] = []

    def add(entry_offset: int) -> None:
        position = entries_base + entry_offset
        if position + 8 > len(data):
            return
        text, key_index = _parse_entry_value(data, position, global_strings)
        if text is None or text == "":
            return
        collected.append(
            ArscEntry(
                _entry_name(key_strings, type_names, type_id, key_index),
                text,
                language,
            )
        )

    if flags & _TYPE_FLAG_SPARSE:
        for index in range(entry_count):
            _entry_id, entry_offset = struct.unpack_from(
                "<HH", data, offsets_position + index * 4
            )
            add(entry_offset * 4)
    elif flags & _TYPE_FLAG_OFFSET16:
        for index in range(entry_count):
            entry_offset = struct.unpack_from(
                "<H", data, offsets_position + index * 2
            )[0]
            if entry_offset != _NO_ENTRY16:
                add(entry_offset * 4)
    else:
        for index in range(entry_count):
            entry_offset = struct.unpack_from(
                "<I", data, offsets_position + index * 4
            )[0]
            if entry_offset != _NO_ENTRY:
                add(entry_offset)

    return tuple(collected)


def _parse_package(
    data: bytes, offset: int, global_strings: list[str]
) -> tuple[str, list[ArscEntry], tuple[str, ...]]:
    """Разбирает один пакет таблицы ресурсов."""
    _chunk_type, header_size, size = _chunk(data, offset)

    name_end = offset + 8 + 4 + 256
    package_name = (
        data[offset + 12 : name_end]
        .decode("utf-16-le", "replace")
        .split("\x00", 1)[0]
        or "package"
    )
    type_strings_offset, _last_type, key_strings_offset, _last_key = (
        struct.unpack_from("<IIII", data, offset + 8 + 4 + 256)
    )

    type_names = parse_string_pool(data, offset + type_strings_offset)
    key_strings = parse_string_pool(data, offset + key_strings_offset)

    notes: list[str] = []
    entries: list[ArscEntry] = []
    position = offset + header_size
    end = offset + size

    while position + 8 <= end:
        chunk_type, chunk_header, chunk_size = _chunk(data, position)
        if chunk_type == RES_TABLE_TYPE_TYPE:
            entries.extend(
                _parse_type_chunk(
                    data, position, global_strings, key_strings, type_names
                )
            )
        elif chunk_type not in {
            RES_TABLE_TYPE_SPEC_TYPE,
            RES_TABLE_LIBRARY_TYPE,
            RES_STRING_POOL_TYPE,
        }:
            notes.append(f"пропущен чанк типа 0x{chunk_type:04x}")
        position += chunk_size
        if chunk_size < chunk_header:
            break

    return package_name, entries, tuple(notes)


def _parse_arsc(data: bytes) -> ArscTable:
    """Разбор без ловушки исключений — их обрабатывает ``parse_arsc``."""
    if len(data) > MAX_ARSC_BYTES:
        return ArscTable(
            entries=(),
            notes=(f"файл больше {MAX_ARSC_BYTES} байт и пропущен",),
        )
    if len(data) < 12:
        return ArscTable(entries=(), notes=("файл слишком мал для resources.arsc",))

    chunk_type, header_size, size = struct.unpack_from("<HHI", data, 0)
    if chunk_type != RES_TABLE_TYPE:
        return ArscTable(
            entries=(),
            notes=(f"это не resources.arsc: тип чанка 0x{chunk_type:04x}",),
        )

    # Глобальный пул строк идёт сразу за заголовком таблицы.
    global_strings: list[str] = []
    if header_size >= 12 and header_size + 8 <= len(data):
        pool_type, _pool_header, _pool_size = struct.unpack_from(
            "<HHI", data, header_size
        )
        if pool_type == RES_STRING_POOL_TYPE:
            global_strings = parse_string_pool(data, header_size)

    entries: list[ArscEntry] = []
    notes: list[str] = []
    package_name = ""
    position = header_size
    # Обрезанный файл разбираем до конца данных, а не до заявленного размера.
    end = min(size, len(data))

    while position + 8 <= end:
        chunk_type, _chunk_header, chunk_size = _chunk(data, position)
        if chunk_type == RES_TABLE_PACKAGE_TYPE:
            package_name, package_entries, package_notes = _parse_package(
                data, position, global_strings
            )
            entries.extend(package_entries)
            notes.extend(package_notes)
        position += chunk_size

    return ArscTable(tuple(entries), package_name, tuple(notes))


def parse_arsc(data: bytes) -> ArscTable:
    """Разбирает ``resources.arsc`` и никогда не падает на битых данных.

    Неизвестный файл — это не ошибка программы: возвращаем пустую таблицу
    и замечание, чтобы отчёт честно сказал «здесь разобрать не удалось».
    """
    try:
        return _parse_arsc(data)
    except (ArscError, struct.error, IndexError) as error:
        return ArscTable(
            entries=(),
            notes=(f"resources.arsc повреждён: {error}",),
        )
