"""Оркестрация анализа: сканирование → извлечение → отчёт."""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

from china_auto_rus.config import DEFAULT_PROFILE
from china_auto_rus.core.extractors import analyze_entry
from china_auto_rus.core.models import (
    AnalysisReport,
    FileInsight,
    ProgressEvent,
    ScanError,
    Stage,
)
from china_auto_rus.core.report import build_report
from china_auto_rus.core.scanner import scan_paths

logger = logging.getLogger(__name__)


def analyze_paths(
    paths: Sequence[Path | str],
    *,
    profile_id: str = DEFAULT_PROFILE.id,
    compute_hashes: bool = True,
    max_depth: int = 64,
    preview_chars: int = 2000,
    max_archive_entries: int = 2000,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> AnalysisReport:
    """Полный анализ файлов и папок. Исходные файлы не изменяются."""
    scan = scan_paths(
        paths,
        compute_hashes=compute_hashes,
        max_depth=max_depth,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )

    insights: list[FileInsight] = []
    errors = list(scan.errors)
    total = len(scan.files)

    for index, entry in enumerate(scan.files, start=1):
        if should_cancel is not None and should_cancel():
            scan.cancelled = True
            break
        try:
            insights.append(
                analyze_entry(
                    entry,
                    preview_chars=preview_chars,
                    max_archive_entries=max_archive_entries,
                )
            )
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            logger.warning("Не удалось разобрать %s: %s", entry.relative_path, exc)
            errors.append(ScanError(entry.relative_path, str(exc)))

        if on_progress is not None:
            on_progress(ProgressEvent(Stage.ANALYZE, index, total, entry.relative_path))

    scan.errors = errors
    report = build_report(scan, insights, profile_id=profile_id)
    logger.info(
        "Анализ завершён: файлов=%d, ошибок=%d", len(report.files), len(report.errors)
    )
    return report
