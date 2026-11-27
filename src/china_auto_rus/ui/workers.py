"""Фоновые worker'ы. Тяжёлая работа не блокирует GUI-поток."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.models import AnalysisReport, ProgressEvent

logger = logging.getLogger(__name__)


class FunctionWorker(QObject):
    """Одноразовая задача в отдельном потоке: результат или текст ошибки.

    Прогресса и отмены нет: операции с APK короткие и неделимые.
    """

    finished = Signal(object)
    failed = Signal(str)
    # Испускается после finished/failed — для очистки worker.
    done = Signal()

    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self._function = function

    def run(self) -> None:
        try:
            result = self._function()
        except Exception as exc:  # граница потока: не даём упасть приложению
            logger.exception("Ошибка фоновой задачи")
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.finished.emit(result)
        finally:
            self.done.emit()


class AnalysisWorker(QObject):
    """Выполняет analyze_paths в отдельном QThread."""

    progress = Signal(object)  # ProgressEvent
    finished = Signal(object)  # AnalysisReport
    failed = Signal(str)
    # Гарантированно испускается после finished/failed — служит для очистки worker.
    done = Signal()

    def __init__(self, paths: list[Path], *, compute_hashes: bool = True) -> None:
        super().__init__()
        self._paths = paths
        self._compute_hashes = compute_hashes
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        """Признак запрошенной отмены (для тестов и состояния окна)."""
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            report: AnalysisReport = analyze_paths(
                self._paths,
                compute_hashes=self._compute_hashes,
                should_cancel=lambda: self._cancelled,
                on_progress=self._emit_progress,
            )
        except Exception as exc:  # граница потока: не даём упасть приложению
            logger.exception("Неожиданная ошибка анализа")
            self.failed.emit(str(exc))
        else:
            self.finished.emit(report)
        finally:
            self.done.emit()

    def _emit_progress(self, event: ProgressEvent) -> None:
        self.progress.emit(event)
