"""Формирование и сохранение отчёта: JSON + Markdown."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from china_auto_rus.config import get_profiles_dir, get_reports_dir
from china_auto_rus.core.models import (
    AnalysisReport,
    CompletionState,
    FileInsight,
    ScanResult,
)
from china_auto_rus.profiles import profile_to_mapping, resolve_profile

# Сериализует выбор имени и запись пары файлов внутри процесса: два
# одновременных сохранения не должны получить одно и то же имя.
_SAVE_LOCK = threading.Lock()

SCHEMA_VERSION = 1

_UNSAFE_STEM_CHARS = '<>:"/\\|?*'
_RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_report_stem(name: str) -> str:
    """Делает из имени каталога безопасное имя файла для Windows."""
    cleaned = "".join(
        "_" if char in _UNSAFE_STEM_CHARS or ord(char) < 32 else char
        for char in name
    )
    cleaned = cleaned.strip(" .")[:80]
    head, dot, tail = cleaned.partition(".")
    if head.upper() in _RESERVED_STEMS:
        cleaned = f"_{head}{dot}{tail}"
    return cleaned or "report"


def _aware(moment: datetime) -> datetime:
    """Наивное время из старых отчётов трактуем как локальное."""
    return moment if moment.tzinfo is not None else moment.astimezone()


def _iso_utc(moment: datetime) -> str:
    """Однозначная метка времени с часовым поясом."""
    return (
        _aware(moment)
        .astimezone(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _profile_payload(profile_id: str) -> dict[str, object]:
    """Сохраняем профиль, только если он действительно известен."""
    profile = resolve_profile(profile_id, get_profiles_dir())
    if profile is None:
        return {"id": profile_id}
    return profile_to_mapping(profile)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} Б"


_LIMIT_DESCRIPTIONS = {
    "max_files": "достигнут лимит количества файлов",
    "max_total_bytes": "достигнут лимит суммарного размера файлов",
    "max_errors": "достигнут лимит количества ошибок",
}


def describe_limit(limit: str) -> str:
    """Человекочитаемое описание сработавшего ограничения."""
    return _LIMIT_DESCRIPTIONS.get(limit, limit)


def _completion_state(scan: ScanResult) -> CompletionState:
    if scan.cancelled:
        return CompletionState.CANCELLED
    if scan.limit_reached is not None:
        return CompletionState.LIMIT_REACHED
    return CompletionState.COMPLETED


def build_report(
    scan: ScanResult,
    insights: Sequence[FileInsight],
    *,
    profile_id: str,
    generated_at: datetime | None = None,
    started_at: datetime | None = None,
) -> AnalysisReport:
    counts = Counter(entry.kind.value for entry in scan.files)
    finished_at = generated_at or datetime.now().astimezone()
    start = started_at or finished_at
    duration = max(0.0, (_aware(finished_at) - _aware(start)).total_seconds())
    return AnalysisReport(
        profile_id=profile_id,
        base_dir=scan.base_dir,
        generated_at=finished_at,
        files=list(scan.files),
        insights=list(insights),
        errors=list(scan.errors),
        cancelled=scan.cancelled,
        total_size=sum(entry.size for entry in scan.files),
        kind_counts=dict(sorted(counts.items())),
        limit_reached=scan.limit_reached,
        started_at=start,
        finished_at=finished_at,
        duration_seconds=round(duration, 3),
        successful_files=sum(1 for entry in scan.files if entry.error is None),
        completion_state=_completion_state(scan),
    )


def report_to_dict(report: AnalysisReport) -> dict[str, object]:
    start = report.started_at or report.generated_at
    finish = report.finished_at or report.generated_at
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": report.profile_id,
        "profile": _profile_payload(report.profile_id),
        "base_dir": str(report.base_dir),
        "source_path": str(report.base_dir),
        "started_at": _iso_utc(start),
        "finished_at": _iso_utc(finish),
        "generated_at": _iso_utc(report.generated_at),
        "duration_seconds": report.duration_seconds or 0.0,
        "completion_state": report.completion_state.value,
        "file_count": len(report.files),
        "successful_files": report.successful_files,
        "error_count": len(report.errors),
        "cancelled": report.cancelled,
        "limit_reached": report.limit_reached,
        "limits_reached": [report.limit_reached] if report.limit_reached else [],
        "total_size": report.total_size,
        "kind_counts": report.kind_counts,
        "files": [
            {
                "path": entry.relative_path,
                "size": entry.size,
                "kind": entry.kind.value,
                "sha256": entry.sha256,
                "error": entry.error,
            }
            for entry in report.files
        ],
        "insights": [
            {
                "path": insight.relative_path,
                "encoding": insight.encoding,
                "encoding_confidence": insight.encoding_confidence.value,
                "encoding_candidates": list(insight.encoding_candidates),
                "preview": insight.preview,
                "archive_entries": [
                    {
                        "name": item.name,
                        "size": item.size,
                        "compressed_size": item.compressed_size,
                        "is_dir": item.is_dir,
                    }
                    for item in insight.archive_entries
                ],
                "notes": list(insight.notes),
            }
            for insight in report.insights
        ],
        "errors": [
            {"path": error.path, "message": error.message} for error in report.errors
        ],
    }


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: AnalysisReport) -> str:
    lines: list[str] = [
        "# Отчёт анализа",
        "",
        f"- **Профиль:** `{report.profile_id}`",
        f"- **Каталог:** `{report.base_dir}`",
        f"- **Дата:** {report.generated_at:%Y-%m-%d %H:%M:%S}",
        f"- **Состояние:** {report.completion_state.value}",
        f"- **Начало:** {_iso_utc(report.started_at or report.generated_at)}",
        f"- **Завершение:** {_iso_utc(report.finished_at or report.generated_at)}",
        f"- **Длительность:** {report.duration_seconds or 0.0:.3f} с",
        f"- **Файлов:** {len(report.files)}",
        f"- **Успешно обработано:** {report.successful_files}",
        f"- **Объём:** {human_size(report.total_size)}",
        f"- **Ошибок:** {len(report.errors)}",
        f"- **Прервано:** {'да' if report.cancelled else 'нет'}",
    ]

    if report.limit_reached is not None:
        lines.append(
            f"- **Сканирование остановлено:** {describe_limit(report.limit_reached)}"
        )

    lines += [
        "",
        "## Форматы",
        "",
        "| Формат | Файлов |",
        "|---|---:|",
    ]

    for kind, count in sorted(report.kind_counts.items()):
        lines.append(f"| {kind} | {count} |")

    lines += [
        "",
        "## Файлы",
        "",
        "| Путь | Размер | Формат | SHA-256 |",
        "|---|---:|---|---|",
    ]
    for entry in report.files:
        digest = f"`{entry.sha256[:16]}…`" if entry.sha256 else "—"
        lines.append(
            f"| {_escape_cell(entry.relative_path)} | {human_size(entry.size)} "
            f"| {entry.kind.value} | {digest} |"
        )

    if report.errors:
        lines += ["", "## Ошибки", ""]
        for error in report.errors:
            lines.append(f"- `{_escape_cell(error.path)}` — {error.message}")

    if report.insights:
        lines += ["", "## Содержимое", ""]
        for insight in report.insights:
            lines.append(f"### {_escape_cell(insight.relative_path)}")
            lines.append("")
            if insight.encoding:
                lines.append(f"- Кодировка: `{insight.encoding}`")
            if insight.encoding_confidence.value == "low":
                candidates = ", ".join(insight.encoding_candidates) or "нет вариантов"
                lines.append(f"- Уверенность: низкая ({candidates})")
            for note in insight.notes:
                lines.append(f"- {note}")
            if insight.archive_entries:
                lines.append(f"- Записей в архиве: {len(insight.archive_entries)}")
            if insight.preview:
                lines += ["", "```text", insight.preview[:500], "```"]
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _next_available_stem(output_dir: Path, base_stem: str) -> str:
    """Подбирает свободное имя: base, base-1, base-2, ....

    Существующим считается отчёт, у которого есть JSON или Markdown,
    поэтому недописанная пара тоже не будет перезаписана.
    """
    candidate = base_stem
    suffix = 1
    while (output_dir / f"{candidate}.json").exists() or (
        output_dir / f"{candidate}.md"
    ).exists():
        candidate = f"{base_stem}-{suffix}"
        suffix += 1
    return candidate


def _atomic_write_text(path: Path, text: str) -> None:
    """Пишет текст через временный файл в том же каталоге и os.replace.

    При любой ошибке временный файл удаляется, целевой файл не остаётся
    частично записанным.
    """
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def save_report(
    report: AnalysisReport,
    *,
    output_dir: Path | None = None,
    stem: str | None = None,
) -> tuple[Path, Path]:
    """Сохраняет отчёт в JSON и Markdown. Возвращает (json_path, md_path).

    Имя уникально: если отчёт с таким именем уже есть, добавляется суффикс
    ``-1``, ``-2`` и т. д. Существующие отчёты не перезаписываются.
    Оба файла пишутся атомарно; при ошибке второго файла первый удаляется.
    """
    target_dir = get_reports_dir() if output_dir is None else output_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    base_stem = (
        safe_report_stem(stem)
        if stem is not None
        else f"report-{report.generated_at:%Y%m%d-%H%M%S}"
    )

    # Сериализуем целиком, чтобы ошибка сериализации не создавала файлов.
    payload = json.dumps(report_to_dict(report), ensure_ascii=False, indent=2)
    markdown = render_markdown(report)

    with _SAVE_LOCK:
        name = _next_available_stem(target_dir, base_stem)
        json_path = target_dir / f"{name}.json"
        md_path = target_dir / f"{name}.md"

        _atomic_write_text(json_path, payload)
        try:
            _atomic_write_text(md_path, markdown)
        except BaseException:
            # Не оставляем «половину» отчёта, если Markdown записать не удалось.
            with contextlib.suppress(OSError):
                json_path.unlink(missing_ok=True)
            raise

    return json_path, md_path
