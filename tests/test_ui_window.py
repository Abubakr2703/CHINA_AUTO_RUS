"""Smoke-тесты главного окна на offscreen-платформе."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer

from china_auto_rus.config import APP_NAME
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.ui.main_window import MainWindow


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
    thread.wait(2000)

    assert window.table_model.rowCount() == 1
    assert window.action_save.isEnabled()
    assert not window.action_cancel.isEnabled()

    window.close()
