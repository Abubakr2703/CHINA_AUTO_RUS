"""Тесты извлечения языковых ресурсов (ключ → текст → язык)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from china_auto_rus.core.resources import (
    DEFAULT_LANGUAGE,
    ResourceEntry,
    ResourceFile,
    export_csv,
    extract_from_directory,
    extract_from_zip,
    extract_resource_file,
    extract_resources,
    is_resource_candidate,
    language_from_path,
    language_from_qualifiers,
    parse_json_strings,
    parse_xml_strings,
    read_csv,
)

STRINGS_XML = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="settings_title">设置</string>
    <string name="nav_start">开始导航</string>
    <string name="greeting">你好，<b>%1$s</b></string>
    <string-array name="volume_levels">
        <item>低</item>
        <item>中</item>
        <item>高</item>
    </string-array>
    <plurals name="minutes">
        <item quantity="one">%d 分钟</item>
        <item quantity="other">%d 分钟</item>
    </plurals>
</resources>
"""


def test_language_from_qualifiers() -> None:
    assert language_from_qualifiers("") == DEFAULT_LANGUAGE
    assert language_from_qualifiers("ru") == "ru"
    assert language_from_qualifiers("zh-rCN") == "zh-CN"
    assert language_from_qualifiers("zh-rCN-night") == "zh-CN"
    assert language_from_qualifiers("b+sr+Latn") == "sr-Latn"


def test_language_from_path() -> None:
    assert language_from_path("res/values/strings.xml") == DEFAULT_LANGUAGE
    assert language_from_path("res/values-zh-rCN/strings.xml") == "zh-CN"
    assert language_from_path("res/values-ru/strings.xml") == "ru"
    assert language_from_path("assets/lang/ru.json") == "ru"
    assert language_from_path("assets/strings_zh-CN.json") == "zh-CN"
    assert language_from_path("assets/config.json") == DEFAULT_LANGUAGE


def test_short_file_names_are_not_mistaken_for_languages() -> None:
    # "ui" и "car" состоят из 2-3 букв, но языками не являются.
    assert language_from_path("assets/ui.json") == DEFAULT_LANGUAGE
    assert language_from_path("assets/my_car.json") == DEFAULT_LANGUAGE
    assert language_from_qualifiers("night") == DEFAULT_LANGUAGE


def test_legacy_android_language_codes_are_normalized() -> None:
    # Android долго использовал in/he/ji вместо id/he/yi.
    assert language_from_qualifiers("in") == "id"
    assert language_from_qualifiers("iw") == "he"
    assert language_from_path("res/values-ji/strings.xml") == "yi"


def test_resource_candidate_filter() -> None:
    assert is_resource_candidate("res/values/strings.xml")
    assert is_resource_candidate("values-ru/strings.xml")
    assert is_resource_candidate("assets/lang/ru.json")
    # Бинарный XML теперь тоже источник строк (AndroidManifest, layout).
    assert is_resource_candidate("AndroidManifest.xml")
    assert is_resource_candidate("res/layout/main.xml")
    assert not is_resource_candidate("res/drawable/icon.png")


def test_parse_xml_strings_extracts_keys() -> None:
    result = parse_xml_strings(STRINGS_XML.encode(), source="strings.xml")

    keys = {entry.key: entry.text for entry in result.entries}
    assert keys["settings_title"] == "设置"
    assert keys["nav_start"] == "开始导航"
    # Вложенный <b> не должен теряться.
    assert keys["greeting"] == "你好，%1$s"
    assert result.notes == ()


def test_parse_xml_strings_arrays_and_plurals() -> None:
    result = parse_xml_strings(STRINGS_XML.encode(), source="strings.xml")

    keys = {entry.key: entry.text for entry in result.entries}
    assert keys["volume_levels[0]"] == "低"
    assert keys["volume_levels[2]"] == "高"
    assert keys["minutes[one]"] == "%d 分钟"


def test_parse_xml_reports_binary_axml() -> None:
    result = parse_xml_strings(b"\x03\x00\x08\x00binary", source="AndroidManifest.xml")

    assert result.entries == ()
    assert "бинарный AXML" in result.notes[0]


def test_parse_json_strings_flattens_nested_keys() -> None:
    payload = b'{"menu": {"settings": "\\u8bbe\\u7f6e", "items": ["a", "b"]}, "n": 5}'

    result = parse_json_strings(payload, source="ru.json", language="ru")

    keys = {entry.key: entry.text for entry in result.entries}
    assert keys["menu.settings"] == "设置"
    assert keys["menu.items[0]"] == "a"
    # Числа не переводятся и не должны попадать в таблицу.
    assert "n" not in keys
    assert result.language == "ru"


def test_parse_json_reports_broken_file() -> None:
    result = parse_json_strings(b"{not json", source="broken.json")

    assert result.entries == ()
    assert "не удалось разобрать JSON" in result.notes[0]


def test_extract_from_directory_collects_locales(tmp_path: Path) -> None:
    base = tmp_path / "res"
    (base / "values").mkdir(parents=True)
    (base / "values-ru").mkdir()
    (base / "values").joinpath("strings.xml").write_text(STRINGS_XML, encoding="utf-8")
    (base / "values-ru").joinpath("strings.xml").write_text(
        '<resources><string name="settings_title">Настройки</string></resources>',
        encoding="utf-8",
    )
    (base / "values").joinpath("ignored.png").write_bytes(b"\x89PNG")

    files = extract_from_directory(base)

    assert len(files) == 2
    languages = {item.language for item in files}
    assert languages == {DEFAULT_LANGUAGE, "ru"}
    russian = next(item for item in files if item.language == "ru")
    assert russian.entries[0].text == "Настройки"


def test_extract_from_zip_reads_apk_like_archive(tmp_path: Path) -> None:
    target = tmp_path / "app.apk"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("res/values/strings.xml", STRINGS_XML)
        archive.writestr("res/values-zh-rCN/strings.xml", STRINGS_XML)
        archive.writestr("resources.arsc", b"\x02\x00\x0c\x00")
        archive.writestr("res/drawable/icon.png", b"\x89PNG")

    files = extract_from_zip(target)

    sources = {item.source for item in files}
    assert "res/values/strings.xml" in sources
    assert "res/values-zh-rCN/strings.xml" in sources
    assert "res/drawable/icon.png" not in sources

    notes = " ".join(note for item in files for note in item.notes)
    assert "resources.arsc" in notes


def test_extract_resources_handles_single_file(tmp_path: Path) -> None:
    path = tmp_path / "ru.json"
    path.write_text('{"settings": "Настройки"}', encoding="utf-8")

    files = extract_resources(path)

    assert len(files) == 1
    assert files[0].entries[0].text == "Настройки"
    assert files[0].language == "ru"


def test_extract_resource_file_skips_oversized(tmp_path: Path) -> None:
    path = tmp_path / "big.json"
    path.write_bytes(b"{}")

    result = extract_resource_file(path, max_bytes=1)

    assert result.entries == ()
    assert "пропущен" in result.notes[0]


def test_csv_round_trip(tmp_path: Path) -> None:
    source = "res/values-zh-rCN/strings.xml"
    entry = ResourceEntry("settings_title", "设置", "zh-CN", source)
    files = (ResourceFile(source, "zh-CN", (entry,)),)
    target = tmp_path / "strings.csv"

    count = export_csv(files, target)
    assert count == 1

    assert read_csv(target) == (entry,)
    # Excel-совместимая кодировка: BOM в начале файла.
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_read_csv_rejects_wrong_columns(tmp_path: Path) -> None:
    target = tmp_path / "bad.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_csv(target)
