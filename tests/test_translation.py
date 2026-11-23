"""Тесты библиотеки перевода: шаблон, импорт, проверка плейсхолдеров."""

from __future__ import annotations

from pathlib import Path

import pytest

from china_auto_rus.core.resources import ResourceEntry
from china_auto_rus.core.translation import (
    TARGET_LANGUAGE,
    TRANSLATION_HEADER,
    TranslationRow,
    apply_translations,
    check_translations,
    display_width,
    export_translation_csv,
    is_translatable,
    read_translation_csv,
    unique_texts,
    validate_text,
)


def codes(text: str, translated: str) -> list[str]:
    return [issue.code for issue in validate_text(text, translated)]


def test_display_width_counts_cjk_as_two() -> None:
    assert display_width("中文") == 4
    assert display_width("ab") == 2
    assert display_width("") == 0


def test_clean_translation_has_no_issues() -> None:
    assert codes("设置", "Настройки") == []


def test_empty_translation_is_single_error() -> None:
    issues = validate_text("设置", "   ")
    assert [issue.code for issue in issues] == ["empty"]
    assert issues[0].severity == "error"


def test_untranslated_text_is_warning() -> None:
    issues = validate_text("Wi-Fi", "Wi-Fi")
    assert [issue.code for issue in issues] == ["untranslated"]
    assert issues[0].severity == "warning"


def test_leftover_chinese_is_error() -> None:
    assert "cjk_left" in codes("设置", "设置 Настройки")


def test_placeholder_must_survive() -> None:
    assert "placeholder_mismatch" in codes("已连接 %1$s", "Подключено")
    assert "placeholder_mismatch" in codes("已连接 %1$s", "Подключено %s")


def test_placeholder_type_must_not_change() -> None:
    assert "placeholder_mismatch" in codes("Файлов: %d", "Файлов: %s")


def test_placeholder_count_must_match() -> None:
    assert "placeholder_mismatch" in codes("Файлов: %d", "Файлов: %d из %d")


def test_indexed_placeholders_can_change_order() -> None:
    assert codes("%1$s из %2$d", "%2$d из %1$s") == []


def test_number_precision_is_not_checked() -> None:
    # %.2f и %.1f показывают разное число знаков, но это осознанный выбор.
    assert codes("Скорость %.2f", "Скорость %.1f") == []


def test_percent_sign_is_not_a_placeholder() -> None:
    assert codes("电量 100%", "Заряд 100%") == []
    assert codes("100% заряда", "100% заряда, ок") == []


def test_brace_placeholders_are_checked() -> None:
    assert codes("{0} 个文件", "{0} файлов") == []
    assert "brace_mismatch" in codes("{0} 个文件", "файлов")


def test_html_tags_are_checked() -> None:
    assert codes("<b>设置</b>", "<b>Настройки</b>") == []
    assert "tag_mismatch" in codes("<b>设置</b>", "Настройки")


def test_newline_count_mismatch_is_warning() -> None:
    issues = validate_text("第一行\n第二行", "Первая строка")
    assert "newline_mismatch" in [issue.code for issue in issues]
    assert all(
        issue.severity == "warning"
        for issue in issues
        if issue.code == "newline_mismatch"
    )


def test_long_translation_is_warning() -> None:
    issues = validate_text("设置", "Настройки и параметры")
    assert [issue.code for issue in issues] == ["too_long"]
    assert issues[0].severity == "warning"


def test_issue_keeps_key_and_source() -> None:
    issues = validate_text("Файлов: %d", "Файлов", key="files_count", source="a.apk")
    assert issues[0].key == "files_count"
    assert issues[0].source == "a.apk"


def test_export_and_read_roundtrip(tmp_path: Path) -> None:
    entries = (
        ResourceEntry("title", "设置", "zh-CN", "strings.xml"),
        ResourceEntry("start", "开始", "zh-CN", "strings.xml"),
    )
    path = tmp_path / "translations.csv"

    assert export_translation_csv(entries, path) == 2

    rows = read_translation_csv(path)
    assert [row.key for row in rows] == ["title", "start"]
    assert rows[0].original == "设置"
    assert rows[0].translation == ""


def test_export_skips_empty_and_duplicate_rows(tmp_path: Path) -> None:
    entries = (
        ResourceEntry("title", "设置", "zh-CN", "a.xml"),
        ResourceEntry("title", "设置", "zh-CN", "a.xml"),
        ResourceEntry("blank", "   ", "zh-CN", "a.xml"),
    )
    path = tmp_path / "translations.csv"

    assert export_translation_csv(entries, path) == 1


def test_export_prefers_chinese_original(tmp_path: Path) -> None:
    entries = (
        ResourceEntry("title", "Instellings", "af", "a.xml"),
        ResourceEntry("title", "设置", "zh-CN", "a.xml"),
        ResourceEntry("title", "Настройки", "ru", "a.xml"),
    )
    path = tmp_path / "translations.csv"

    export_translation_csv(entries, path)

    rows = read_translation_csv(path)
    assert [row.original for row in rows] == ["设置"]


def test_export_falls_back_to_non_russian_original(tmp_path: Path) -> None:
    entries = (
        ResourceEntry("title", "Settings", "en", "a.xml"),
        ResourceEntry("title", "Настройки", "ru", "a.xml"),
    )
    path = tmp_path / "translations.csv"

    export_translation_csv(entries, path)

    rows = read_translation_csv(path)
    assert [row.original for row in rows] == ["Settings"]


def test_technical_strings_are_not_translatable() -> None:
    assert not is_translatable("https://f-droid.org/repo")
    assert not is_translatable("com.android.settings")
    assert not is_translatable("user@example.com")
    assert not is_translatable("100%")
    assert not is_translatable("   ")
    assert is_translatable("设置")
    assert is_translatable("Wi-Fi")
    assert is_translatable("确定 %1$s")


def test_export_skips_technical_strings(tmp_path: Path) -> None:
    entries = (
        ResourceEntry("repo", "https://example.org/repo", "zh", "a.json"),
        ResourceEntry("title", "设置", "zh", "a.xml"),
    )
    path = tmp_path / "translations.csv"

    assert export_translation_csv(entries, path) == 1
    assert [row.key for row in read_translation_csv(path)] == ["title"]


def test_read_translation_csv_requires_header(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="колонок"):
        read_translation_csv(path)


def test_header_is_stable() -> None:
    assert TRANSLATION_HEADER == ("source", "key", "original", "translation")


def test_check_translations_counts_progress() -> None:
    rows = (
        TranslationRow("a.apk", "title", "设置", "Настройки"),
        TranslationRow("a.apk", "nav", "导航", "Навигация"),
        TranslationRow("a.apk", "toast", "已保存", ""),
    )

    report = check_translations(rows)

    assert report.total == 3
    assert report.translated == 2
    assert report.missing == ("a.apk:toast",)
    assert report.errors == ()
    assert report.coverage == pytest.approx(2 / 3)


def test_check_translations_reports_duplicates_as_warning() -> None:
    rows = (
        TranslationRow("a.apk", "title", "设置", "Настройки"),
        TranslationRow("a.apk", "title", "设置", "Настройки"),
    )

    report = check_translations(rows)

    assert [issue.code for issue in report.warnings] == ["duplicate"]
    assert report.errors == ()


def test_check_translations_collects_errors() -> None:
    rows = (
        TranslationRow("a.apk", "speed", "速度 %d", "Скорость"),
        TranslationRow("a.apk", "ok", "确定", "ОК"),
    )

    report = check_translations(rows)

    assert [issue.code for issue in report.errors] == ["placeholder_mismatch"]
    assert report.coverage == 1.0


def test_unique_texts_groups_repeated_originals() -> None:
    rows = (
        TranslationRow("a.apk", "one", "确定", ""),
        TranslationRow("b.apk", "two", "确定", ""),
        TranslationRow("b.apk", "three", "取消", ""),
    )

    unique = unique_texts(rows)

    assert [item.text for item in unique] == ["确定", "取消"]
    assert unique[0].count == 2
    assert unique[0].keys == ("a.apk:one", "b.apk:two")


def test_apply_translations_keeps_only_filled_rows() -> None:
    rows = (
        TranslationRow("a.apk", "title", "设置", "Настройки"),
        TranslationRow("a.apk", "toast", "已保存", ""),
    )

    entries = apply_translations(rows)

    assert len(entries) == 1
    assert entries[0] == ResourceEntry(
        "title", "Настройки", TARGET_LANGUAGE, "a.apk"
    )
