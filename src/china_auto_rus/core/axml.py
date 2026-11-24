"""Разбор бинарного Android XML (AXML).

aapt2 компилирует ``AndroidManifest.xml`` и ``res/layout/*.xml`` в цепочку
чанков ResChunk: пул строк, пространства имён, элементы и их атрибуты.
Текст в layout часто лежит прямо в атрибуте (``android:text="确定"``) и в
``resources.arsc`` не попадает — именно поэтому нужен этот парсер.

Читаем только строковые атрибуты. Ссылки на ресурсы, enum и числа
пропускаются: их значения и так берутся из ``resources.arsc``.

Модуль ничего не пишет: на вход байты, на выходе документ.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from china_auto_rus.core.arsc import ArscError, parse_string_pool

RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_START_ELEMENT_TYPE = 0x0102

# Res_value: строка — это индекс в пуле строк.
_VALUE_TYPE_STRING = 0x03
_NO_INDEX = 0xFFFFFFFF

MAX_AXML_BYTES = 16 * 1024 * 1024

# Атрибуты с техническими значениями: имена классов, идентификаторы, MIME,
# права доступа. Их не переводят, поэтому в тексты они не попадают.
_NON_TEXT_ATTRIBUTES = frozenset(
    {
        "id",
        "name",
        "tag",
        "scheme",
        "host",
        "path",
        "package",
        "authorities",
        "process",
        "resource",
        "mimeType",
        "targetPackage",
        "targetActivity",
        "parentActivityName",
        "taskAffinity",
        "appComponentFactory",
        "class",
        "key",
        "src",
        "domain",
    }
)

# Семейства атрибутов, где текст — всегда техническая строка:
# pathPrefix/pathPattern, versionName, readPermission, propertyName,
# fontFamily, layout_*, valueFrom/valueTo, scaleWidth.
_NON_TEXT_PREFIXES = (
    "path",
    "version",
    "permission",
    "compileSdk",
    "property",
    "font",
    "layout",
    "value",
    "scale",
    "constraint",
    "mime",
)


class AxmlError(Exception):
    """Данные не являются бинарным XML или повреждены."""


@dataclass(frozen=True, slots=True)
class AxmlAttribute:
    """Строковый атрибут: ``android:text`` и его значение."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class AxmlElement:
    """Элемент разметки и его строковые атрибуты."""

    name: str
    line: int
    attributes: tuple[AxmlAttribute, ...]


@dataclass(frozen=True, slots=True)
class AxmlDocument:
    """Результат разбора. Ошибки не бросаются, а попадают в ``notes``."""

    elements: tuple[AxmlElement, ...] = ()
    strings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def is_axml(data: bytes) -> bool:
    """Первые два байта AXML — тип чанка ``RES_XML_TYPE``."""
    if len(data) < 8:
        return False
    chunk_type, header_size, size = struct.unpack_from("<HHI", data, 0)
    return chunk_type == RES_XML_TYPE and 8 <= header_size <= size


def _chunk(data: bytes, offset: int) -> tuple[int, int, int]:
    """Возвращает (тип, размер заголовка, полный размер) чанка."""
    if offset + 8 > len(data):
        raise AxmlError("чанк выходит за границы файла")
    chunk_type, header_size, size = struct.unpack_from("<HHI", data, offset)
    if header_size < 8 or size < header_size or offset + size > len(data):
        raise AxmlError(f"некорректный заголовок чанка по смещению {offset}")
    return chunk_type, header_size, size


def _string_at(strings: list[str], index: int) -> str:
    if 0 <= index < len(strings):
        return strings[index]
    return ""


def _attribute_name(
    strings: list[str],
    namespaces: dict[str, str],
    ns_index: int,
    name_index: int,
) -> str:
    """Имя атрибута с префиксом: ``android:text`` вместо просто ``text``."""
    local = _string_at(strings, name_index)
    if ns_index == _NO_INDEX:
        return local
    prefix = namespaces.get(_string_at(strings, ns_index), "")
    return f"{prefix}:{local}" if prefix and local else local


def _attribute_value(
    strings: list[str],
    raw_index: int,
    value_type: int,
    value_data: int,
) -> str | None:
    """Значение атрибута, если оно задано строкой, а не ссылкой."""
    if raw_index != _NO_INDEX:
        return _string_at(strings, raw_index)
    if value_type == _VALUE_TYPE_STRING:
        return _string_at(strings, value_data)
    return None


def _parse_element(
    data: bytes,
    offset: int,
    header_size: int,
    chunk_size: int,
    strings: list[str],
    namespaces: dict[str, str],
) -> AxmlElement | None:
    end = offset + chunk_size
    ext = offset + header_size
    if ext + 20 > end:
        return None

    line = struct.unpack_from("<I", data, offset + 8)[0]
    (
        _ns_index,
        name_index,
        attribute_start,
        attribute_size,
        attribute_count,
        *_indices,
    ) = struct.unpack_from("<IIHHHHHH", data, ext)

    attributes: list[AxmlAttribute] = []
    if attribute_size >= 20:
        for index in range(attribute_count):
            position = ext + attribute_start + index * attribute_size
            if position + 20 > end:
                break
            (
                ns_index,
                attribute_name_index,
                raw_index,
                _value_size,
                _res0,
                value_type,
                value_data,
            ) = struct.unpack_from("<IIIHBBI", data, position)

            name = _attribute_name(
                strings, namespaces, ns_index, attribute_name_index
            )
            local = name.rsplit(":", 1)[-1]
            if not name or local in _NON_TEXT_ATTRIBUTES:
                continue
            if local.startswith(_NON_TEXT_PREFIXES):
                continue
            value = _attribute_value(strings, raw_index, value_type, value_data)
            if value is None or not value.strip():
                continue
            attributes.append(AxmlAttribute(name, value))

    element_name = _string_at(strings, name_index)
    if not element_name:
        return None
    return AxmlElement(element_name, line, tuple(attributes))


def _parse_axml(data: bytes) -> AxmlDocument:
    """Разбор без ловушки исключений — их обрабатывает ``parse_axml``."""
    if len(data) > MAX_AXML_BYTES:
        return AxmlDocument(
            notes=(f"файл больше {MAX_AXML_BYTES} байт и пропущен",)
        )
    if len(data) < 8:
        return AxmlDocument(notes=("файл слишком мал для бинарного XML",))

    chunk_type, header_size, size = _chunk(data, 0)
    if chunk_type != RES_XML_TYPE:
        return AxmlDocument(
            notes=(f"это не бинарный XML: тип чанка 0x{chunk_type:04x}",)
        )

    strings: list[str] = []
    pool_type, _pool_header, _pool_size = _chunk(data, header_size)
    if pool_type != 0x0001:
        return AxmlDocument(
            notes=(f"ожидался пул строк, найден тип 0x{pool_type:04x}",)
        )
    strings = parse_string_pool(data, header_size)

    namespaces: dict[str, str] = {}
    elements: list[AxmlElement] = []
    position = header_size
    end = min(size, len(data))

    while position + 8 <= end:
        chunk_type, header_size, chunk_size = _chunk(data, position)
        if chunk_size == 0:
            break
        if chunk_type == RES_XML_START_NAMESPACE_TYPE:
            body = position + header_size
            if body + 8 <= position + chunk_size:
                prefix_index, uri_index = struct.unpack_from("<II", data, body)
                prefix = _string_at(strings, prefix_index)
                uri = _string_at(strings, uri_index)
                if uri:
                    namespaces[uri] = prefix
        elif chunk_type == RES_XML_START_ELEMENT_TYPE:
            element = _parse_element(
                data, position, header_size, chunk_size, strings, namespaces
            )
            if element is not None:
                elements.append(element)
        position += chunk_size

    return AxmlDocument(tuple(elements), tuple(strings))


def parse_axml(data: bytes) -> AxmlDocument:
    """Разбирает бинарный XML и никогда не падает на битых данных."""
    try:
        return _parse_axml(data)
    except (AxmlError, ArscError, struct.error, IndexError) as error:
        return AxmlDocument(notes=(f"бинарный XML не разобран: {error}",))
