"""Тесты фонового worker без запуска QThread."""

from __future__ import annotations

from pathlib import Path

import pytest

import china_auto_rus.ui.workers as workers_module
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


def test_worker_emits_done_after_finished(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    worker = AnalysisWorker([tmp_path])
    order: list[str] = []
    worker.finished.connect(lambda _: order.append("finished"))
    worker.done.connect(lambda: order.append("done"))

    worker.run()

    assert order == ["finished", "done"]


def test_worker_emits_failed_and_done_on_error(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(paths: list[Path], **kwargs: object) -> object:
        raise RuntimeError("сбой ядра")

    monkeypatch.setattr(workers_module, "analyze_paths", failing)
    worker = AnalysisWorker([tmp_path])
    messages: list[str] = []
    order: list[str] = []
    worker.finished.connect(lambda _: order.append("finished"))

    def on_failed(message: str) -> None:
        messages.append(message)
        order.append("failed")

    worker.failed.connect(on_failed)
    worker.done.connect(lambda: order.append("done"))

    worker.run()

    assert len(messages) == 1
    assert "сбой ядра" in messages[0]
    assert order == ["failed", "done"]


def test_worker_exposes_cancel_flag(qapp: object, tmp_path: Path) -> None:
    worker = AnalysisWorker([tmp_path])

    assert worker.cancelled is False
    worker.cancel()
    assert worker.cancelled is True
