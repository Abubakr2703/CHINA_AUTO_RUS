"""Фоновый worker анализа. Тяжёлая работа не блокирует GUI-поток."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.models import AnalysisReport, ProgressEvent

logger = logging.getLogger(__name__)


class AnalysisWorker(QObject):
    """Выполняет analyze_paths в отдельном QThread."""

    progress = Signal(object)  # ProgressEvent
    finished = Signal(object)  # AnalysisReport
    failed = Signal(str)

    def __init__(self, paths: list[Path], *, compute_hashes: bool = True) -> None:
        super().__init__()
        self._paths = paths
        self._compute_hashes = compute_hashes
        self._cancelled = False

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
            return
        self.finished.emit(report)

    def _emit_progress(self, event: ProgressEvent) -> None:
        self.progress.emit(event)
