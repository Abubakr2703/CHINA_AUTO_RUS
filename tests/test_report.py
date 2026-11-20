"""Тесты отчёта: сборка, JSON, Markdown."""

from __future__ import annotations

import json
from pathlib import Path

from china_auto_rus.config import DEFAULT_PROFILE
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.report import human_size, save_report


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
    assert data["profile_id"] == DEFAULT_PROFILE.id
    assert data["files"][0]["path"] == "a.txt"
    assert data["files"][0]["sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "# Отчёт анализа" in markdown
    assert "a.txt" in markdown
    assert "## Форматы" in markdown
