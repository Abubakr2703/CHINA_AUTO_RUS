"""Тесты отчёта: сборка, JSON, Markdown."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

import china_auto_rus.core.report as report_module
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.models import AnalysisReport
from china_auto_rus.core.report import (
    SCHEMA_VERSION,
    human_size,
    render_markdown,
    report_to_dict,
    safe_report_stem,
    save_report,
)
from china_auto_rus.profiles import DEFAULT_PROFILE_ID, default_profile


def _make_report(tmp_path: Path) -> AnalysisReport:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    return analyze_paths([source])


def test_human_size() -> None:
    assert human_size(0) == "0 Б"
    assert human_size(1024) == "1.0 КБ"
    assert human_size(1024 * 1024) == "1.0 МБ"


def test_save_report_writes_json_and_markdown(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    report = analyze_paths([tmp_path])

    json_path, md_path = save_report(report, output_dir=tmp_path / "out", stem="test")

    assert json_path.exists()
    assert md_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["profile_id"] == DEFAULT_PROFILE_ID
    assert data["files"][0]["path"] == "a.txt"
    assert data["files"][0]["sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "# Отчёт анализа" in markdown
    assert "a.txt" in markdown
    assert "## Форматы" in markdown


def test_save_report_twice_creates_unique_files(tmp_path: Path) -> None:
    report = _make_report(tmp_path)
    output_dir = tmp_path / "out"

    first_json, first_md = save_report(report, output_dir=output_dir)
    second_json, second_md = save_report(report, output_dir=output_dir)

    assert first_json != second_json
    assert first_md != second_md
    assert first_json.exists() and first_md.exists()
    assert second_json.exists() and second_md.exists()


def test_save_report_same_timestamp_does_not_collide(tmp_path: Path) -> None:
    report = _make_report(tmp_path)
    report.generated_at = datetime(2026, 1, 2, 3, 4, 5)
    output_dir = tmp_path / "out"

    first_json, _ = save_report(report, output_dir=output_dir)
    second_json, _ = save_report(report, output_dir=output_dir)
    third_json, _ = save_report(report, output_dir=output_dir)

    assert first_json.name == "report-20260102-030405.json"
    assert second_json.name == "report-20260102-030405-1.json"
    assert third_json.name == "report-20260102-030405-2.json"


def test_save_report_does_not_overwrite_existing(tmp_path: Path) -> None:
    report = _make_report(tmp_path)
    output_dir = tmp_path / "out"

    first_json, first_md = save_report(report, output_dir=output_dir, stem="test")
    original_json = first_json.read_bytes()
    original_md = first_md.read_bytes()

    report.cancelled = True
    second_json, second_md = save_report(report, output_dir=output_dir, stem="test")

    assert second_json.name == "test-1.json"
    assert second_md.name == "test-1.md"
    assert first_json.read_bytes() == original_json
    assert first_md.read_bytes() == original_md
    assert second_json.read_bytes() != original_json


def test_save_report_write_error_leaves_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _make_report(tmp_path)
    output_dir = tmp_path / "out"
    real_replace = os.replace

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst).parent == output_dir:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(report_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        save_report(report, output_dir=output_dir, stem="test")

    assert not (output_dir / "test.json").exists()
    assert not (output_dir / "test.md").exists()
    assert list(output_dir.iterdir()) == [], "временные файлы должны быть удалены"


def test_report_marks_reached_limit(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    report = analyze_paths([tmp_path], max_files=1)

    data = report_to_dict(report)
    assert data["limit_reached"] == "max_files"

    markdown = render_markdown(report)
    assert "Сканирование остановлено" in markdown
    assert "лимит количества файлов" in markdown


def test_save_report_markdown_error_removes_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _make_report(tmp_path)
    output_dir = tmp_path / "out"
    real_replace = os.replace

    def failing_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst).parent == output_dir and Path(dst).suffix == ".md":
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(report_module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        save_report(report, output_dir=output_dir, stem="test")

    assert not (output_dir / "test.json").exists()
    assert not (output_dir / "test.md").exists()
    assert list(output_dir.iterdir()) == [], "временные файлы должны быть удалены"


def test_json_schema_and_profile(tmp_path: Path) -> None:
    data = report_to_dict(_make_report(tmp_path))

    assert data["schema_version"] == SCHEMA_VERSION
    profile = data["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == DEFAULT_PROFILE_ID
    assert profile["model"] == default_profile().model
    # Неподтверждённые характеристики остаются пустыми.
    assert profile["head_unit"] is None
    assert profile["hardware_platform"] is None
    assert data["file_count"] == 1
    assert data["successful_files"] == 1
    assert data["error_count"] == 0
    assert data["completion_state"] == "completed"
    assert data["limits_reached"] == []
    assert data["source_path"] == data["base_dir"]


def test_report_timestamps_are_timezone_aware(tmp_path: Path) -> None:
    data = report_to_dict(_make_report(tmp_path))

    moments = {
        key: datetime.fromisoformat(str(data[key]))
        for key in ("started_at", "finished_at", "generated_at")
    }
    assert all(moment.tzinfo is not None for moment in moments.values())
    assert moments["finished_at"] >= moments["started_at"]
    assert isinstance(data["duration_seconds"], float)
    assert data["duration_seconds"] >= 0


def test_cancelled_report_state(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    report = analyze_paths([tmp_path], should_cancel=lambda: True)

    data = report_to_dict(report)

    assert data["cancelled"] is True
    assert data["completion_state"] == "cancelled"


def test_limit_report_state(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    report = analyze_paths([tmp_path], max_files=1)

    data = report_to_dict(report)

    assert data["completion_state"] == "limit_reached"
    assert data["limits_reached"] == ["max_files"]
    assert data["limit_reached"] == "max_files"


@pytest.mark.parametrize(
    "name",
    ['C:\\Users\\bad?name', "CON", "  ", "x" * 200, "normal.name"],
)
def test_safe_report_stem(name: str) -> None:
    stem = safe_report_stem(name)

    assert stem
    assert not any(char in stem for char in '<>:"/\\|?*')
    assert stem.strip() == stem
    assert len(stem) <= 80


def test_save_report_sanitizes_stem(tmp_path: Path) -> None:
    json_path, md_path = save_report(
        _make_report(tmp_path),
        output_dir=tmp_path / "out",
        stem="bad:name?*",
    )

    assert ":" not in json_path.name
    assert "?" not in json_path.name
    assert ":" not in md_path.name


def test_old_report_without_new_fields_is_readable(tmp_path: Path) -> None:
    old = AnalysisReport(
        profile_id="old-profile",
        base_dir=tmp_path,
        generated_at=datetime(2025, 1, 1, 12, 0, 0),
        files=[],
        insights=[],
        errors=[],
        cancelled=False,
        total_size=0,
        kind_counts={},
    )

    data = report_to_dict(old)

    assert data["schema_version"] == SCHEMA_VERSION
    assert data["profile"] == {"id": "old-profile"}
    assert datetime.fromisoformat(str(data["generated_at"])).tzinfo is not None
    assert "# Отчёт анализа" in render_markdown(old)
