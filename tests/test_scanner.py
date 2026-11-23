"""Тесты сканера: форматы, хеши, отмена, ошибки путей."""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

import china_auto_rus.core.scanner as scanner_module
from china_auto_rus.core.models import FileEntry, FileKind
from china_auto_rus.core.scanner import _common_base, _relative, detect_kind, scan_paths


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


def test_scan_stops_at_max_files(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    result = scan_paths([tmp_path], max_files=2)

    assert len(result.files) == 2
    assert result.limit_reached == "max_files"
    assert not result.cancelled


def test_scan_stops_at_max_total_bytes(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("1234", encoding="utf-8")

    result = scan_paths([tmp_path], max_total_bytes=8)

    assert len(result.files) == 2
    assert result.limit_reached == "max_total_bytes"


def test_scan_total_bytes_boundary_is_inclusive(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("1234", encoding="utf-8")
    (tmp_path / "b.txt").write_text("5678", encoding="utf-8")

    result = scan_paths([tmp_path], max_total_bytes=4)

    assert [entry.relative_path for entry in result.files] == ["a.txt"]
    assert result.limit_reached == "max_total_bytes"

    exact = scan_paths([tmp_path / "a.txt"], max_total_bytes=4)

    assert len(exact.files) == 1
    assert exact.limit_reached is None


def test_scan_stops_at_max_errors(tmp_path: Path) -> None:
    missing = [tmp_path / f"missing-{index}" for index in range(3)]

    result = scan_paths(missing, max_errors=2)

    assert len(result.errors) == 2
    assert result.limit_reached == "max_errors"
    assert result.files == []


def test_scan_empty_directory_has_no_limit(tmp_path: Path) -> None:
    result = scan_paths([tmp_path])

    assert result.files == []
    assert result.errors == []
    assert result.limit_reached is None


def test_scan_small_directory_without_limits(tmp_path: Path) -> None:
    _write_tree(tmp_path)

    result = scan_paths(
        [tmp_path],
        max_files=100,
        max_total_bytes=1024 * 1024,
        max_errors=10,
    )

    assert len(result.files) == 6
    assert result.limit_reached is None


def test_scan_isolates_read_error_of_one_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "good.txt"
    bad = tmp_path / "bad.txt"
    good.write_text("ok", encoding="utf-8")
    bad.write_text("bad", encoding="utf-8")
    real_sha256 = scanner_module.sha256_file

    def fake_sha256(
        path: Path, chunk_size: int = scanner_module.CHUNK_SIZE
    ) -> str:
        if path == bad:
            raise PermissionError("access denied")
        return real_sha256(path, chunk_size)

    monkeypatch.setattr(scanner_module, "sha256_file", fake_sha256)

    result = scan_paths([tmp_path])

    entries = {entry.relative_path: entry for entry in result.files}
    assert entries["good.txt"].error is None
    assert entries["good.txt"].sha256 == hashlib.sha256(b"ok").hexdigest()
    assert entries["bad.txt"].error is not None
    assert len(result.errors) == 1
    assert result.errors[0].path == "bad.txt"
    assert result.limit_reached is None


def test_scan_isolates_unexpected_error_and_keeps_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "a_good.txt"
    bad = tmp_path / "b_bad.txt"
    good.write_text("ok", encoding="utf-8")
    bad.write_text("bad", encoding="utf-8")
    real_build = scanner_module._build_entry

    def fake_build(path: Path, base_dir: Path, compute_hash: bool) -> FileEntry:
        if path == bad:
            raise RuntimeError("неожиданный сбой")
        return real_build(path, base_dir, compute_hash)

    monkeypatch.setattr(scanner_module, "_build_entry", fake_build)

    result = scan_paths([tmp_path])

    entries = {entry.relative_path: entry for entry in result.files}
    assert len(entries) == 2
    assert entries["a_good.txt"].error is None
    assert entries["a_good.txt"].sha256 == hashlib.sha256(b"ok").hexdigest()
    assert entries["b_bad.txt"].error is not None
    assert "RuntimeError" in str(entries["b_bad.txt"].error)
    assert len(result.errors) == 1
    assert "RuntimeError: неожиданный сбой" in result.errors[0].message
    assert result.limit_reached is None


def test_scan_unexpected_error_respects_max_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    def fake_build(path: Path, base_dir: Path, compute_hash: bool) -> FileEntry:
        raise RuntimeError("boom")

    monkeypatch.setattr(scanner_module, "_build_entry", fake_build)

    result = scan_paths([tmp_path], max_errors=1)

    assert len(result.files) == 1
    assert len(result.errors) == 1
    assert result.limit_reached == "max_errors"


def test_scan_cancellation_is_not_recorded_as_file_error(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    result = scan_paths([tmp_path], should_cancel=lambda: True)

    assert result.cancelled
    assert result.errors == []
    assert result.limit_reached is None


def test_common_base_uses_largest_drive_group() -> None:
    base = _common_base(
        [
            Path("C:/data/one/a.txt"),
            Path("C:/data/two/b.txt"),
            Path("D:/other/c.txt"),
        ]
    )

    assert base == Path("C:/data")


def test_common_base_mixed_absolute_and_relative() -> None:
    base = _common_base([Path("C:/data/a.txt"), Path("rel/b.txt")])

    assert base == Path("C:/data")


def test_relative_falls_back_to_source_path_on_other_drive() -> None:
    path = Path("D:/other/file.txt")

    assert _relative(path, Path("C:/data")) == str(path)


def test_relative_handles_nested_unicode_paths(tmp_path: Path) -> None:
    root = tmp_path / "Китай_данные"
    nested = root / "уровень 2"
    nested.mkdir(parents=True)
    file_path = nested / "файл.txt"
    file_path.write_text("x", encoding="utf-8")

    assert _relative(file_path, root) == str(Path("уровень 2") / "файл.txt")


def test_scan_survives_commonpath_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    def broken_commonpath(paths: object) -> str:
        raise ValueError("different drives")

    monkeypatch.setattr(os.path, "commonpath", broken_commonpath)

    result = scan_paths([tmp_path])

    assert len(result.files) == 1
    assert result.files[0].path == tmp_path / "a.txt"
    assert result.files[0].relative_path == "a.txt"


def test_scan_mixed_absolute_and_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = scan_paths([tmp_path / "a.txt", Path("b.txt")])

    assert {entry.relative_path for entry in result.files} == {"a.txt", "b.txt"}
    assert result.errors == []


@pytest.mark.parametrize(
    ("name", "head"),
    [
        ("setup.exe", b"MZ" + b"\x00" * 16),
        ("document.pdf", b"%PDF-1.7\n" + b"\x00" * 8),
        ("archive.gz", b"\x1f\x8b" + b"\x00" * 8),
        ("video.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 8),
        ("font.otf", b"OTTO" + b"\x00" * 8),
        ("audio.ogg", b"OggS" + b"\x00" * 8),
    ],
)
def test_detect_kind_known_binary_by_magic(
    tmp_path: Path, name: str, head: bytes
) -> None:
    assert detect_kind(tmp_path / name, head) is FileKind.BINARY


def test_detect_kind_unknown_without_signature(tmp_path: Path) -> None:
    assert detect_kind(tmp_path / "data.dat", b"\x00\x01\x02\x03") is FileKind.UNKNOWN


def test_apk_is_detected_only_by_zip_signature(tmp_path: Path) -> None:
    assert detect_kind(tmp_path / "fake.apk", b"\x00\x01\x02\x03") is (
        FileKind.UNSUPPORTED
    )
    assert detect_kind(tmp_path / "real.apk", b"PK\x03\x04" + b"\x00" * 8) is (
        FileKind.APK
    )


def test_text_file_with_apk_extension_is_not_android_app(tmp_path: Path) -> None:
    assert detect_kind(tmp_path / "notes.apk", b"just plain text") is FileKind.TEXT


def test_scan_distinguishes_binary_and_unknown(tmp_path: Path) -> None:
    (tmp_path / "app.exe").write_bytes(b"MZ" + b"\x00" * 16)
    (tmp_path / "mystery.dat").write_bytes(b"\x00\x01\x02\x03")

    result = scan_paths([tmp_path])

    kinds = {entry.relative_path: entry.kind for entry in result.files}
    assert kinds["app.exe"] is FileKind.BINARY
    assert kinds["mystery.dat"] is FileKind.UNKNOWN
