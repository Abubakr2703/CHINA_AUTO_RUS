"""Smoke-тесты главного окна на offscreen-платформе."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

import china_auto_rus.ui.workers as workers_module
from china_auto_rus.config import APP_NAME
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.analyzer import analyze_paths as real_analyze_paths
from china_auto_rus.ui.main_window import AnalysisState, MainWindow


def _pump_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Прокачивает GUI-очередь, пока worker и слоты окна не завершатся."""
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            pytest.fail("условие не выполнено за отведённое время")
        time.sleep(0.005)


def _blocking_analyze(
    started: threading.Event, release: threading.Event
) -> Callable[..., object]:
    def analyze(paths: list[Path], **kwargs: object) -> object:
        started.set()
        assert release.wait(5), "тест не освободил worker"
        return real_analyze_paths(paths, **kwargs)  # type: ignore[arg-type]

    return analyze


def test_main_window_starts(qapp: object) -> None:
    window = MainWindow()

    assert APP_NAME in window.windowTitle()
    assert not window.action_save.isEnabled()
    assert not window.action_cancel.isEnabled()

    window.close()


def test_display_report_fills_models(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    report = analyze_paths([tmp_path])
    window = MainWindow()

    window._display_report(report)
    window.table.selectRow(0)

    assert window.table_model.rowCount() == 1
    assert window.action_save.isEnabled()
    assert window.tabs.tabText(window.tabs.indexOf(window.errors_list)) == "Ошибки (0)"
    assert "a.txt" in window.preview.toPlainText()
    assert "hello" in window.preview.toPlainText()

    window.close()


def test_analysis_runs_in_thread(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    window = MainWindow()

    window._start_analysis([tmp_path])
    thread = window._thread
    assert thread is not None

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()

    # Ссылка обнуляется в _on_thread_finished, когда поток реально остановился.
    # Не вызываем wait(): QThread уже помечен на deleteLater.
    _pump_until(lambda: window._thread is None)

    assert window.table_model.rowCount() == 1
    assert window.action_save.isEnabled()
    assert not window.action_cancel.isEnabled()

    window.close()


def test_start_then_finish_moves_through_states(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(workers_module, "analyze_paths", _blocking_analyze(started, release))

    window = MainWindow()
    assert window.state is AnalysisState.IDLE

    window._start_analysis([tmp_path])
    assert window.state is AnalysisState.RUNNING
    assert window._thread is not None
    assert window._worker is not None
    assert started.wait(5)
    assert not window.action_open_file.isEnabled()
    assert not window.action_open_folder.isEnabled()
    assert not window.hash_checkbox.isEnabled()
    assert not window.action_save.isEnabled()
    assert window.action_cancel.isEnabled()

    release.set()
    _pump_until(lambda: window.state is AnalysisState.FINISHED)

    assert window._thread is None
    assert window._worker is None
    assert window.table_model.rowCount() == 1
    assert window.action_save.isEnabled()
    assert window.action_open_file.isEnabled()
    assert not window.action_cancel.isEnabled()
    window.close()


def test_repeated_start_while_running_is_ignored(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    (first / "a.txt").write_text("a", encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()
    (second / "b.txt").write_text("b", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(workers_module, "analyze_paths", _blocking_analyze(started, release))

    window = MainWindow()
    window._start_analysis([first])
    assert started.wait(5)
    first_thread = window._thread
    first_worker = window._worker

    window._start_analysis([second])

    assert window._thread is first_thread
    assert window._worker is first_worker
    assert window.state is AnalysisState.RUNNING

    release.set()
    _pump_until(lambda: window.state is AnalysisState.FINISHED)
    # В таблице только файл из первого каталога: второй анализ не запускался.
    assert window.table_model.rowCount() == 1
    window.close()


def test_cancel_moves_to_cancelling_and_back(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    cancel_seen = threading.Event()
    real = workers_module.analyze_paths

    def waits_for_cancel(paths: list[Path], **kwargs: object) -> object:
        should_cancel = kwargs["should_cancel"]
        assert callable(should_cancel)
        while not should_cancel():
            time.sleep(0.005)
        cancel_seen.set()
        kwargs["should_cancel"] = lambda: True
        return real(paths, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(workers_module, "analyze_paths", waits_for_cancel)

    window = MainWindow()
    window._start_analysis([tmp_path])
    assert window.state is AnalysisState.RUNNING

    window._cancel_analysis()

    assert window.state is AnalysisState.CANCELLING
    assert not window.action_cancel.isEnabled()
    assert cancel_seen.wait(5)

    _pump_until(lambda: window.state is AnalysisState.FINISHED)
    assert window.table_model.rowCount() == 0
    assert "отменён" in window.status_label.text()
    assert not window.action_cancel.isEnabled()
    assert window.action_open_file.isEnabled()
    window.close()


def test_worker_error_clears_busy_state(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    shown: list[str] = []

    def failing(paths: list[Path], **kwargs: object) -> object:
        raise RuntimeError("сбой ядра")

    def fake_critical(*args: object, **kwargs: object) -> object:
        shown.append(str(args[-1]))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(workers_module, "analyze_paths", failing)
    monkeypatch.setattr(QMessageBox, "critical", fake_critical)

    window = MainWindow()
    window._start_analysis([tmp_path])

    _pump_until(lambda: window.state is AnalysisState.FINISHED)

    assert len(shown) == 1
    assert "сбой ядра" in shown[0]
    assert window.table_model.rowCount() == 0
    assert not window.action_save.isEnabled()
    assert not window.action_cancel.isEnabled()
    assert window.action_open_file.isEnabled()
    assert window._thread is None
    assert window._worker is None
    window.close()


def test_close_during_analysis_defers_until_thread_stops(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(workers_module, "analyze_paths", _blocking_analyze(started, release))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )

    window = MainWindow()
    window.show()
    window._start_analysis([tmp_path])
    assert started.wait(5)

    window.close()

    assert window._close_requested is True
    assert window.state is AnalysisState.CANCELLING
    assert window.isVisible(), "первое закрытие должно быть отложено"

    release.set()
    _pump_until(lambda: not window.isVisible())

    assert window._close_requested is False
    assert window.state is AnalysisState.FINISHED


def test_close_when_analysis_ends_during_confirmation(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(workers_module, "analyze_paths", _blocking_analyze(started, release))

    window = MainWindow()
    window.show()
    window._start_analysis([tmp_path])
    assert started.wait(5)

    def question(*args: object) -> object:
        # Диалог крутит вложенный event loop, за который анализ успевает закончиться.
        release.set()
        _pump_until(lambda: window.state is AnalysisState.FINISHED)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", question)

    window.close()

    assert not window.isVisible()
    assert window._thread is None
    assert window._close_requested is False


def test_restart_after_full_finish(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    (first / "a.txt").write_text("a", encoding="utf-8")
    second = tmp_path / "second"
    second.mkdir()
    (second / "b.txt").write_text("b", encoding="utf-8")
    calls: list[list[Path]] = []

    def counting(paths: list[Path], **kwargs: object) -> object:
        calls.append(paths)
        return real_analyze_paths(paths, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(workers_module, "analyze_paths", counting)

    window = MainWindow()
    window._start_analysis([first])
    _pump_until(lambda: window.state is AnalysisState.FINISHED)
    assert window.table_model.rowCount() == 1

    window._start_analysis([second])
    assert window.state is AnalysisState.RUNNING
    _pump_until(lambda: window.state is AnalysisState.FINISHED)

    assert len(calls) == 2
    assert calls[0] == [first]
    assert calls[1] == [second]
    assert window.table_model.rowCount() == 1
    window.close()
