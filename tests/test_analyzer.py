"""Интеграционные тесты анализатора: сквозной сценарий и read-only."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

import china_auto_rus.core.analyzer as analyzer_module
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.models import FileEntry, FileInsight


def test_analyze_paths_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "data.zip", "w") as archive:
        archive.writestr("strings.xml", "<resources/>")
    (tmp_path / "broken.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 16)

    before = hashlib.sha256(source.read_bytes()).hexdigest()
    report = analyze_paths([tmp_path])
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after, "анализатор не должен изменять исходные файлы"
    assert report.total_size > 0
    assert report.kind_counts["text"] == 1
    assert report.kind_counts["zip"] == 2
    assert any(error.path == "broken.zip" for error in report.errors)

    insights = {insight.relative_path: insight for insight in report.insights}
    assert insights["note.txt"].preview == "hello"
    assert insights["data.zip"].archive_entries[0].name == "strings.xml"


def test_analyze_paths_can_be_cancelled(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    report = analyze_paths([tmp_path], should_cancel=lambda: True)

    assert report.cancelled
    assert report.insights == []


def test_analyze_paths_reports_missing_path(tmp_path: Path) -> None:
    report = analyze_paths([tmp_path / "missing"])

    assert report.files == []
    assert report.errors


def test_analyze_paths_reflects_max_files(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    report = analyze_paths([tmp_path], max_files=1)

    assert len(report.files) == 1
    assert report.limit_reached == "max_files"


def test_analyze_paths_stops_at_max_errors(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "broken.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 16)

    report = analyze_paths([tmp_path], max_errors=1)

    assert len(report.errors) == 1
    assert report.limit_reached == "max_errors"


def test_analyze_isolates_unexpected_extractor_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("fail", encoding="utf-8")
    (tmp_path / "z.txt").write_text("ok", encoding="utf-8")
    real_analyze = analyzer_module.analyze_entry

    def fake_analyze(
        entry: FileEntry,
        *,
        preview_chars: int = 2000,
        max_archive_entries: int = 2000,
    ) -> FileInsight:
        if entry.relative_path == "a.txt":
            raise RuntimeError("сбой экстрактора")
        return real_analyze(
            entry,
            preview_chars=preview_chars,
            max_archive_entries=max_archive_entries,
        )

    monkeypatch.setattr(analyzer_module, "analyze_entry", fake_analyze)

    report = analyze_paths([tmp_path])

    assert len(report.files) == 2
    assert any(error.path == "a.txt" for error in report.errors)
    assert any("RuntimeError: сбой экстрактора" in error.message for error in report.errors)
    insights = {insight.relative_path: insight for insight in report.insights}
    assert set(insights) == {"z.txt"}
    assert insights["z.txt"].preview == "ok"
    assert report.limit_reached is None


def test_analyze_continues_after_archive_error(tmp_path: Path) -> None:
    (tmp_path / "a_broken.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 16)
    (tmp_path / "z_note.txt").write_text("hello", encoding="utf-8")

    report = analyze_paths([tmp_path])

    assert any(error.path == "a_broken.zip" for error in report.errors)
    insights = {insight.relative_path: insight for insight in report.insights}
    assert "z_note.txt" in insights
    assert insights["z_note.txt"].preview == "hello"
    assert len(report.files) == 2


def test_analyze_unexpected_error_respects_max_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    def fake_analyze(
        entry: FileEntry,
        *,
        preview_chars: int = 2000,
        max_archive_entries: int = 2000,
    ) -> FileInsight:
        raise RuntimeError("boom")

    monkeypatch.setattr(analyzer_module, "analyze_entry", fake_analyze)

    report = analyze_paths([tmp_path], max_errors=2)

    assert len(report.errors) == 2
    assert report.limit_reached == "max_errors"
    assert report.insights == []
    assert len(report.files) == 3, "уже полученные результаты не должны теряться"


def test_analyze_cancellation_is_not_recorded_as_error(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    report = analyze_paths([tmp_path], should_cancel=lambda: True)

    assert report.cancelled
    assert report.errors == []
    assert report.insights == []
    assert report.limit_reached is None
