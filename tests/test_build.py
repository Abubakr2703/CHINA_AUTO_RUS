"""Тесты сборки APK с переводом."""

from __future__ import annotations

import io
import zipfile

import pytest

from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.core.build import BuildError, build_apk
from china_auto_rus.core.translation import TranslationRow, build_replacements
from tests.arsc_fixture import build_sample


def _apk(*, with_arsc: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        if with_arsc:
            archive.writestr("resources.arsc", build_sample())
    return buffer.getvalue()


def _row(original: str, translation: str) -> TranslationRow:
    return TranslationRow(
        source="zh-CN",
        key="string/settings_title",
        original=original,
        translation=translation,
    )


def test_build_apk_replaces_strings() -> None:
    result = build_apk(_apk(), [_row("设置", "Параметры")])

    with zipfile.ZipFile(io.BytesIO(result.apk)) as archive:
        table = parse_arsc(archive.read("resources.arsc"))

    texts = {entry.text for entry in table.entries}
    assert "Параметры" in texts
    assert result.replacements == 1
    assert result.changed_entries == 1
    assert result.entries == 3
    assert result.missing == ()


def test_build_apk_reports_missing_originals() -> None:
    result = build_apk(_apk(), [_row("строки нет в APK", "перевод")])

    assert result.missing == ("строки нет в APK",)
    assert result.changed_entries == 0


def test_build_apk_rejects_empty_template() -> None:
    with pytest.raises(BuildError):
        build_apk(_apk(), [_row("设置", "")])


def test_build_apk_rejects_apk_without_arsc() -> None:
    with pytest.raises(BuildError):
        build_apk(_apk(with_arsc=False), [_row("设置", "Параметры")])


def test_build_replacements_skips_identity_and_blank() -> None:
    rows = [
        _row("设置", "设置"),
        _row("开始导航", ""),
        _row("", "что-то"),
        _row("设置", "Параметры"),
    ]

    assert build_replacements(rows) == {"设置": "Параметры"}


def test_build_replacements_keeps_first_translation() -> None:
    rows = [_row("设置", "Параметры"), _row("设置", "Настройки")]

    assert build_replacements(rows) == {"设置": "Параметры"}
