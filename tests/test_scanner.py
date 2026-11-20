"""Тесты сканера: форматы, хеши, отмена, ошибки путей."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from china_auto_rus.core.models import FileKind
from china_auto_rus.core.scanner import detect_kind, scan_paths


def _write_tree(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "strings.xml").write_text(
        "<?xml version='1.0'?><resources/>", encoding="utf-8"
    )
    (tmp_path / "config.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02\x03")
    (tmp_path / "fake.apk").write_bytes(b"PK\x03\x04" + b"\x00" * 16)
    with zipfile.ZipFile(tmp_path / "data.zip", "w") as archive:
        archive.writestr("a.txt", "hello")


def test_scan_detects_kinds_and_sha256(tmp_path: Path) -> None:
    _write_tree(tmp_path)

    result = scan_paths([tmp_path])

    kinds = {entry.relative_path: entry.kind for entry in result.files}
    assert kinds["note.txt"] is FileKind.TEXT
    assert kinds["strings.xml"] is FileKind.XML
    assert kinds["config.json"] is FileKind.JSON
    assert kinds["blob.bin"] is FileKind.UNKNOWN
    assert kinds["fake.apk"] is FileKind.APK
    assert kinds["data.zip"] is FileKind.ZIP

    note = next(entry for entry in result.files if entry.relative_path == "note.txt")
    assert note.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert not result.errors


def test_scan_detects_elf_by_magic(tmp_path: Path) -> None:
    library = tmp_path / "libtest.so"
    library.write_bytes(b"\x7fELF" + b"\x00" * 16)

    result = scan_paths([library])

    assert result.files[0].kind is FileKind.ELF
    assert result.files[0].relative_path == "libtest.so"


def test_detect_kind_uses_extension_for_zip(tmp_path: Path) -> None:
    head = b"PK\x03\x04" + b"\x00" * 16
    assert detect_kind(tmp_path / "a.apk", head) is FileKind.APK
    assert detect_kind(tmp_path / "a.zip", head) is FileKind.ZIP
    assert detect_kind(tmp_path / "a.bin", head) is FileKind.ZIP


def test_scan_is_cancellable(tmp_path: Path) -> None:
    _write_tree(tmp_path)

    result = scan_paths([tmp_path], should_cancel=lambda: True)

    assert result.cancelled
    assert result.files == []


def test_scan_reports_missing_path(tmp_path: Path) -> None:
    result = scan_paths([tmp_path / "missing"])

    assert result.files == []
    assert len(result.errors) == 1
    assert result.errors[0].path.endswith("missing")


def test_scan_deduplicates_overlapping_inputs(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    result = scan_paths([tmp_path, tmp_path / "a.txt"])

    assert len(result.files) == 1


def test_scan_without_hashes(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    result = scan_paths([tmp_path], compute_hashes=False)

    assert result.files[0].sha256 is None
