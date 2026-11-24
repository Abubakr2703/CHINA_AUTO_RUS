"""Тесты разбора бинарного Android XML (AXML).

Файл собирается прямо в тесте: проверка не зависит от aapt2 и от версии
Android SDK.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from china_auto_rus.core.axml import is_axml, parse_axml
from china_auto_rus.core.resources import (
    extract_from_zip,
    is_resource_candidate,
    parse_axml_strings,
    parse_resource_bytes,
)

ANDROID_NS = "http://schemas.android.com/apk/res/android"
PREFIX_INDEX = 0
URI_INDEX = 1


def _pad(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - len(data) % 4) % 4)


def _length8(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    return bytes([0x80 | (value >> 8), value & 0xFF])


def build_string_pool(strings: list[str]) -> bytes:
    offsets: list[int] = []
    data = bytearray()

    for text in strings:
        offsets.append(len(data))
        raw = text.encode("utf-8")
        data += _length8(len(text))
        data += _length8(len(raw))
        data += raw + b"\x00"

    data = bytearray(_pad(bytes(data)))
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    header = struct.pack(
        "<HHIIIIII",
        0x0001,
        header_size,
        strings_start + len(data),
        len(strings),
        0,
        0x100,
        strings_start,
        0,
    )
    offsets_bytes = b"".join(struct.pack("<I", value) for value in offsets)
    return header + offsets_bytes + bytes(data)


def _namespace(prefix_index: int, uri_index: int) -> bytes:
    header = struct.pack("<HHIII", 0x0100, 16, 24, 1, 0xFFFFFFFF)
    return header + struct.pack("<II", prefix_index, uri_index)


def _element(
    name_index: int, attributes: list[tuple[int, int, int | None]]
) -> bytes:
    """Атрибут — (ns, имя, значение); ``None`` вместо значения — ссылка."""
    body = b""
    for ns_index, attribute_name, value_index in attributes:
        if value_index is None:
            body += struct.pack(
                "<IIIHBBI", ns_index, attribute_name, 0xFFFFFFFF, 8, 0, 1, 0x7F010001
            )
        else:
            body += struct.pack(
                "<IIIHBBI", ns_index, attribute_name, value_index, 8, 0, 3, value_index
            )

    size = 16 + 20 + len(body)
    header = struct.pack("<HHIII", 0x0102, 16, size, 1, 0xFFFFFFFF)
    ext = struct.pack(
        "<IIHHHHHH",
        0xFFFFFFFF,
        name_index,
        20,
        20,
        len(attributes),
        0,
        0,
        0,
    )
    return header + ext + body


def build_axml(
    elements: list[tuple[str, list[tuple[str | None, str, str | None]]]],
) -> bytes:
    """Собирает минимальный AXML: элементы и их атрибуты."""
    strings: list[str] = ["android", ANDROID_NS]

    def index(value: str) -> int:
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    prepared: list[tuple[int, list[tuple[int, int, int | None]]]] = []
    for name, attributes in elements:
        packed: list[tuple[int, int, int | None]] = []
        for prefix, attribute_name, value in attributes:
            ns_index = URI_INDEX if prefix == "android" else 0xFFFFFFFF
            raw = None if value is None else index(value)
            packed.append((ns_index, index(attribute_name), raw))
        prepared.append((index(name), packed))

    chunks = [_namespace(PREFIX_INDEX, URI_INDEX)]
    chunks += [_element(name_index, attrs) for name_index, attrs in prepared]
    body = build_string_pool(strings) + b"".join(chunks)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def test_is_axml_detects_binary_xml() -> None:
    assert is_axml(build_axml([("TextView", [])])) is True
    assert is_axml(b"<resources></resources>") is False
    assert is_axml(b"PK\x03\x04\x00\x00\x00\x00") is False
    assert is_axml(b"\x03\x00") is False


def test_parse_layout_text_attribute() -> None:
    data = build_axml(
        [("TextView", [("android", "text", "设置"), ("android", "id", "@+id/t")])]
    )

    document = parse_axml(data)

    assert document.notes == ()
    assert len(document.elements) == 1
    element = document.elements[0]
    assert element.name == "TextView"
    # android:id — техническое значение, в тексты не попадает.
    assert [(item.name, item.value) for item in element.attributes] == [
        ("android:text", "设置")
    ]


def test_reference_value_is_skipped() -> None:
    data = build_axml([("TextView", [("android", "text", None)])])

    assert parse_axml(data).elements[0].attributes == ()


def test_attribute_without_namespace_keeps_plain_name() -> None:
    data = build_axml([("application", [(None, "label", "Deepal")])])

    assert [(item.name, item.value) for item in parse_axml(data).elements[0].attributes] == [
        ("label", "Deepal")
    ]


def test_blank_values_are_skipped() -> None:
    data = build_axml([("TextView", [("android", "text", "   ")])])

    assert parse_axml(data).elements[0].attributes == ()


def test_technical_manifest_attributes_are_skipped() -> None:
    data = build_axml(
        [
            (
                "manifest",
                [
                    ("android", "versionName", "2.0.3"),
                    ("android", "compileSdkVersionCodename", "17"),
                ],
            ),
            ("service", [("android", "permission", "android.permission.BIND_JOB_SERVICE")]),
            ("data", [("android", "pathPrefix", "/packages/")]),
            ("objectAnimator", [("android", "propertyName", "translationZ")]),
            ("TextView", [("android", "fontFamily", "sans-serif-medium")]),
            ("certificates", [("android", "src", "system")]),
            ("application", [("android", "label", "Deepal")]),
        ]
    )

    attributes = [
        (element.name, item.name, item.value)
        for element in parse_axml(data).elements
        for item in element.attributes
    ]

    assert attributes == [("application", "android:label", "Deepal")]


def test_malformed_data_returns_notes() -> None:
    document = parse_axml(b"\x03\x00\x08\x00\xff\xff\xff\xff")

    assert document.elements == ()
    assert document.notes


def test_plain_xml_is_not_axml() -> None:
    document = parse_axml(b"<resources><string>ok</string></resources>")

    assert document.elements == ()
    assert document.notes


def test_element_index_keeps_keys_unique() -> None:
    data = build_axml(
        [
            ("TextView", [("android", "text", "确定")]),
            ("Button", [("android", "text", "取消")]),
        ]
    )

    resource = parse_axml_strings(data, source="res/layout/main.xml")

    assert [entry.key for entry in resource.entries] == [
        "TextView[0]/android:text",
        "Button[1]/android:text",
    ]
    assert [entry.text for entry in resource.entries] == ["确定", "取消"]
    assert all(entry.language == "default" for entry in resource.entries)


def test_axml_strings_keep_language_and_notes() -> None:
    resource = parse_axml_strings(
        build_axml([("TextView", [("android", "text", "开始")])]),
        source="res/layout/main.xml",
        language="zh-CN",
    )
    assert resource.language == "zh-CN"
    assert resource.notes == ()


def test_parse_resource_bytes_detects_axml_by_content() -> None:
    data = build_axml([("TextView", [("android", "text", "导航")])])

    resource = parse_resource_bytes(data, source="res/layout/main.xml")

    assert [entry.text for entry in resource.entries] == ["导航"]


@pytest.mark.parametrize(
    "name",
    [
        "res/layout/activity_main.xml",
        "res/layout-v21/activity_main.xml",
        "res/xml/preferences.xml",
        "res/menu/main.xml",
        "res/0L.xml",
        "res/06.xml",
        "AndroidManifest.xml",
        "base/AndroidManifest.xml",
    ],
)
def test_compiled_xml_is_a_resource_candidate(name: str) -> None:
    assert is_resource_candidate(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "res/drawable/icon.png",
        "assets/config.xml",
        "lib/arm64-v8a/libapp.so",
    ],
)
def test_non_candidate_files_are_skipped(name: str) -> None:
    assert is_resource_candidate(name) is False


def test_extract_from_zip_reads_layouts(tmp_path: Path) -> None:
    layout = build_axml([("TextView", [("android", "text", "设置")])])
    apk = tmp_path / "app.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("res/layout/main.xml", layout)
        archive.writestr("res/drawable/icon.png", b"\x89PNG\r\n\x1a\n")

    files = extract_from_zip(apk)

    entries = [entry for item in files for entry in item.entries]
    assert [entry.text for entry in entries] == ["设置"]
    assert entries[0].source == "res/layout/main.xml"
