"""Тесты фонового worker без запуска QThread."""

from __future__ import annotations

from pathlib import Path

from china_auto_rus.core.models import AnalysisReport, ProgressEvent, Stage
from china_auto_rus.ui.workers import AnalysisWorker


def test_worker_emits_finished_report(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    worker = AnalysisWorker([tmp_path])

    received: list[object] = []
    worker.finished.connect(received.append)
    worker.run()

    assert len(received) == 1
    report = received[0]
    assert isinstance(report, AnalysisReport)
    assert report.files[0].relative_path == "a.txt"


def test_worker_emits_progress(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    worker = AnalysisWorker([tmp_path])

    events: list[ProgressEvent] = []
    worker.progress.connect(events.append)
    worker.run()

    assert any(event.stage is Stage.ANALYZE for event in events)
