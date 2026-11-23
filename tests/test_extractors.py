"""Тесты извлечения: кодировки, предпросмотр, архивы."""

from __future__ import annotations

import codecs
import zipfile
from pathlib import Path

from china_auto_rus.core.analyzer import analyze_entry
from china_auto_rus.core.extractors import (
    AMBIGUOUS_ENCODING,
    UNKNOWN_ENCODING,
    detect_encoding,
    detect_encoding_detailed,
    list_archive,
    read_text_preview,
)
from china_auto_rus.core.models import EncodingConfidence, FileEntry, FileKind


def test_detect_encoding_utf8() -> None:
    assert detect_encoding("привет".encode()) == "utf-8"


def test_detect_encoding_utf8_bom() -> None:
    raw = codecs.BOM_UTF8 + "привет".encode()

    decision = detect_encoding_detailed(raw)

    assert decision.encoding == "utf-8-sig"
    assert decision.confidence is EncodingConfidence.HIGH
    assert "привет" in decision.variants[0][1]


def test_detect_encoding_utf16_le_by_bom() -> None:
    raw = codecs.BOM_UTF16_LE + "你好".encode("utf-16-le")

    assert detect_encoding(raw) == "utf-16"


def test_detect_encoding_utf16_be_by_bom() -> None:
    raw = codecs.BOM_UTF16_BE + "你好".encode("utf-16-be")

    assert detect_encoding(raw) == "utf-16"


def test_detect_encoding_utf16_le_without_bom() -> None:
    raw = "Hello world".encode("utf-16-le")

    decision = detect_encoding_detailed(raw)

    assert decision.encoding == "utf-16-le"
    assert decision.confidence is EncodingConfidence.HIGH
    assert decision.variants[0][1] == "Hello world"


def test_detect_encoding_utf16_be_without_bom() -> None:
    raw = "Hello world".encode("utf-16-be")

    assert detect_encoding_detailed(raw).encoding == "utf-16-be"


def test_detect_encoding_gbk() -> None:
    assert detect_encoding("你好世界".encode("gbk")) == "gbk"


def test_detect_encoding_gb18030() -> None:
    # 4-байтовая последовательность GB18030, недоступная в GBK.
    raw = bytes.fromhex("95328236")

    decision = detect_encoding_detailed(raw)

    assert decision.encoding == "gb18030"
    assert decision.confidence is EncodingConfidence.HIGH
    assert decision.variants[0][1] == chr(0x20000)


def test_detect_encoding_cp1251() -> None:
    raw = "Привет мир, это тест".encode("cp1251")

    decision = detect_encoding_detailed(raw)

    assert "cp1251" in decision.candidates
    assert any(text == "Привет мир, это тест" for _, text in decision.variants)


def test_detect_encoding_ambiguous_cp1251_and_gbk() -> None:
    raw = "Привет".encode("cp1251")

    decision = detect_encoding_detailed(raw)

    assert decision.encoding == AMBIGUOUS_ENCODING
    assert decision.confidence is EncodingConfidence.LOW
    assert set(decision.candidates) == {"cp1251", "gbk"}
    assert any(text == "Привет" for _, text in decision.variants)


def test_detect_encoding_corrupted_sequence() -> None:
    decision = detect_encoding_detailed(bytes.fromhex("fffe00d8"))

    assert decision.encoding == UNKNOWN_ENCODING
    assert decision.confidence is EncodingConfidence.LOW
    assert decision.candidates == ()


def test_detect_encoding_empty_file() -> None:
    decision = detect_encoding_detailed(b"")

    assert decision.encoding == "utf-8"
    assert decision.variants == (("utf-8", ""),)


def test_read_text_preview_truncates(tmp_path: Path) -> None:
    path = tmp_path / "long.txt"
    path.write_text("x" * 50, encoding="utf-8")

    preview = read_text_preview(path, limit=10)

    assert preview.text == "x" * 10
    assert preview.truncated
    assert preview.encoding == "utf-8"
    assert preview.confidence is EncodingConfidence.HIGH


def test_read_text_preview_keeps_source_bytes(tmp_path: Path) -> None:
    raw = "你好世界".encode("gbk")
    path = tmp_path / "zh.txt"
    path.write_bytes(raw)

    preview = read_text_preview(path)

    assert path.read_bytes() == raw
    assert preview.encoding == "gbk"
    assert preview.text == "你好世界"


def test_read_text_preview_shows_ambiguous_variants(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.txt"
    path.write_bytes("Привет".encode("cp1251"))

    preview = read_text_preview(path)

    assert preview.confidence is EncodingConfidence.LOW
    assert set(preview.candidates) == {"cp1251", "gbk"}
    assert "hex" in preview.text
    assert "cp1251" in preview.text
    assert "gbk" in preview.text
    assert "Привет" in preview.text


def test_analyze_entry_propagates_encoding_confidence(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.txt"
    path.write_bytes("Привет".encode("cp1251"))
    entry = FileEntry(
        path=path,
        relative_path="ambiguous.txt",
        size=path.stat().st_size,
        kind=FileKind.TEXT,
    )

    insight = analyze_entry(entry)

    assert insight.encoding_confidence is EncodingConfidence.LOW
    assert set(insight.encoding_candidates) == {"cp1251", "gbk"}
    assert any("неоднозначна" in note for note in insight.notes)


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
