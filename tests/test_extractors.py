"""Тесты извлечения: кодировки, предпросмотр, архивы."""

from __future__ import annotations

import zipfile
from pathlib import Path

from china_auto_rus.core.extractors import detect_encoding, list_archive, read_text_preview


def test_detect_encoding_utf8() -> None:
    assert detect_encoding("привет".encode()) == "utf-8"


def test_detect_encoding_gbk() -> None:
    assert detect_encoding("你好世界".encode("gbk")) == "gbk"


def test_detect_encoding_utf16_by_bom() -> None:
    assert detect_encoding("你好".encode("utf-16")) == "utf-16"


def test_read_text_preview_truncates(tmp_path: Path) -> None:
    path = tmp_path / "long.txt"
    path.write_text("x" * 50, encoding="utf-8")

    preview = read_text_preview(path, limit=10)

    assert preview.text == "x" * 10
    assert preview.truncated
    assert preview.encoding == "utf-8"


def test_list_archive_reports_apk_resources(tmp_path: Path) -> None:
    path = tmp_path / "app.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("resources.arsc", b"\x00")
        archive.writestr("AndroidManifest.xml", b"\x03\x00")
        archive.writestr("res/values/strings.xml", b"<resources/>")

    listing = list_archive(path)

    assert listing.total == 3
    assert len(listing.entries) == 3
    assert any("resources.arsc" in note for note in listing.notes)
    assert any("AndroidManifest.xml" in note for note in listing.notes)


def test_list_archive_limits_entries(tmp_path: Path) -> None:
    path = tmp_path / "many.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(5):
            archive.writestr(f"file{index}.txt", "x")

    listing = list_archive(path, max_entries=2)

    assert listing.total == 5
    assert len(listing.entries) == 2
    assert listing.notes
