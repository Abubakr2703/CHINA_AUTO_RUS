"""Оркестрация анализа: сканирование → извлечение → отчёт."""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from china_auto_rus.core.extractors import analyze_entry
from china_auto_rus.core.models import (
    AnalysisReport,
    FileInsight,
    ProgressEvent,
    ScanError,
    Stage,
)
from china_auto_rus.core.report import build_report
from china_auto_rus.core.scanner import (
    DEFAULT_MAX_ERRORS,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
    describe_exception,
    scan_paths,
)
from china_auto_rus.profiles import DEFAULT_PROFILE_ID

logger = logging.getLogger(__name__)


def analyze_paths(
    paths: Sequence[Path | str],
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    compute_hashes: bool = True,
    max_depth: int = 64,
    max_files: int | None = DEFAULT_MAX_FILES,
    max_total_bytes: int | None = DEFAULT_MAX_TOTAL_BYTES,
    max_errors: int | None = DEFAULT_MAX_ERRORS,
    preview_chars: int = 2000,
    max_archive_entries: int = 2000,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> AnalysisReport:
    """Полный анализ файлов и папок. Исходные файлы не изменяются."""
    started_at = datetime.now().astimezone()
    scan = scan_paths(
        paths,
        compute_hashes=compute_hashes,
        max_depth=max_depth,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        max_errors=max_errors,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )

    insights: list[FileInsight] = []
    errors = list(scan.errors)
    total = len(scan.files)

    def add_error(error: ScanError) -> bool:
        """Сохраняет ошибку; True означает, что достигнут max_errors."""
        if max_errors is not None and len(errors) >= max_errors:
            scan.limit_reached = scan.limit_reached or "max_errors"
            return True
        errors.append(error)
        if max_errors is not None and len(errors) >= max_errors:
            scan.limit_reached = scan.limit_reached or "max_errors"
            return True
        return False

    for index, entry in enumerate(scan.files, start=1):
        if scan.limit_reached == "max_errors":
            break
        if should_cancel is not None and should_cancel():
            scan.cancelled = True
            break
        try:
            insight = analyze_entry(
                entry,
                preview_chars=preview_chars,
                max_archive_entries=max_archive_entries,
            )
        except Exception as exc:
            # Ошибка одного файла не обрывает анализ остальных.
            if isinstance(exc, (OSError, zipfile.BadZipFile, ValueError)):
                logger.warning("Не удалось разобрать %s: %s", entry.relative_path, exc)
            else:
                logger.exception(
                    "Неожиданная ошибка при разборе %s", entry.relative_path
                )
            if add_error(ScanError(entry.relative_path, describe_exception(exc))):
                break
        else:
            insights.append(insight)

        if on_progress is not None:
            on_progress(ProgressEvent(Stage.ANALYZE, index, total, entry.relative_path))

    scan.errors = errors
    report = build_report(
        scan,
        insights,
        profile_id=profile_id,
        started_at=started_at,
    )
    logger.info(
        "Анализ завершён: файлов=%d, ошибок=%d", len(report.files), len(report.errors)
    )
    return report
