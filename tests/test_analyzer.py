"""Интеграционные тесты анализатора: сквозной сценарий и read-only."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from china_auto_rus.core.analyzer import analyze_paths


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
