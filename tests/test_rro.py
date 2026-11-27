"""Тесты генератора RRO-оверлея."""

from __future__ import annotations

from pathlib import Path

import pytest

from china_auto_rus.core.rro import RroError, build_overlay, write_overlay
from china_auto_rus.core.translation import TranslationRow


def _row(key: str, translation: str, original: str = "中文") -> TranslationRow:
    return TranslationRow(
        source="zh-CN",
        key=key,
        original=original,
        translation=translation,
    )


def test_build_overlay_manifest_targets_package() -> None:
    overlay = build_overlay("com.example.app", [_row("string/title", "Заголовок")])

    assert overlay.package == "ru.chinaautorius.overlay.com_example_app"
    assert overlay.target_package == "com.example.app"
    assert 'android:targetPackage="com.example.app"' in overlay.manifest
    assert 'android:isStatic="false"' in overlay.manifest
    assert 'android:hasCode="false"' in overlay.manifest


def test_build_overlay_writes_strings_xml() -> None:
    overlay = build_overlay(
        "com.example.app",
        [
            _row("string/title", "Заголовок"),
            _row("string/subtitle", "Подзаголовок"),
        ],
    )

    assert overlay.strings == 2
    assert "<string name=\"title\">Заголовок</string>" in overlay.strings_xml
    assert "<string name=\"subtitle\">Подзаголовок</string>" in overlay.strings_xml
    assert '<?xml version="1.0" encoding="utf-8"?>' in overlay.strings_xml


def test_build_overlay_escapes_special_characters() -> None:
    overlay = build_overlay(
        "com.example.app",
        [
            _row("string/text", "a & b < c > d \"e\" 'f'"),
            _row("string/ref", "@g"),
        ],
    )

    assert "a &amp; b &lt; c &gt; d" in overlay.strings_xml
    assert "\\@g</string>" in overlay.strings_xml
    assert "\\'f\\'" in overlay.strings_xml


def test_build_overlay_marks_formatted_strings() -> None:
    overlay = build_overlay(
        "com.example.app",
        [_row("string/fmt", "Всего: %1$d"), _row("string/plain", "Просто текст")],
    )

    assert 'name="fmt" formatted="false"' in overlay.strings_xml
    assert 'name="plain" formatted=' not in overlay.strings_xml


def test_build_overlay_skips_empty_and_non_string() -> None:
    overlay = build_overlay(
        "com.example.app",
        [
            _row("string/title", "Заголовок"),
            _row("string/empty", ""),
            _row("color/accent", "красный"),
        ],
    )

    assert overlay.strings == 1
    assert any("color/accent" in item for item in overlay.skipped)


def test_build_overlay_skips_duplicate_with_other_translation() -> None:
    overlay = build_overlay(
        "com.example.app",
        [
            _row("string/title", "Первый"),
            _row("string/title", "Второй"),
        ],
    )

    assert "<string name=\"title\">Первый</string>" in overlay.strings_xml
    assert any("другим переводом" in item for item in overlay.skipped)


def test_build_overlay_rejects_bad_package() -> None:
    with pytest.raises(RroError):
        build_overlay("1bad-package", [_row("string/title", "Заголовок")])


def test_build_overlay_rejects_empty_template() -> None:
    with pytest.raises(RroError):
        build_overlay("com.example.app", [_row("string/title", "")])


def test_build_overlay_rejects_bad_locale() -> None:
    with pytest.raises(RroError):
        build_overlay("com.example.app", [_row("string/title", "Текст")], locale="russian")


def test_write_overlay_creates_sources(tmp_path: Path) -> None:
    overlay = build_overlay("com.example.app", [_row("string/title", "Заголовок")])

    manifest_path, strings_path = write_overlay(overlay, tmp_path)

    assert manifest_path == tmp_path / "AndroidManifest.xml"
    assert strings_path == tmp_path / "res" / "values-ru" / "strings.xml"
    assert manifest_path.read_text(encoding="utf-8") == overlay.manifest
    assert strings_path.read_text(encoding="utf-8") == overlay.strings_xml
