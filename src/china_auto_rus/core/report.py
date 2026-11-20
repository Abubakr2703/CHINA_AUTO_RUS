"""Формирование и сохранение отчёта: JSON + Markdown."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from china_auto_rus.config import REPORTS_DIR
from china_auto_rus.core.models import AnalysisReport, FileInsight, ScanResult


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} Б"


def build_report(
    scan: ScanResult,
    insights: Sequence[FileInsight],
    *,
    profile_id: str,
    generated_at: datetime | None = None,
) -> AnalysisReport:
    counts = Counter(entry.kind.value for entry in scan.files)
    return AnalysisReport(
        profile_id=profile_id,
        base_dir=scan.base_dir,
        generated_at=generated_at or datetime.now(),
        files=list(scan.files),
        insights=list(insights),
        errors=list(scan.errors),
        cancelled=scan.cancelled,
        total_size=sum(entry.size for entry in scan.files),
        kind_counts=dict(sorted(counts.items())),
    )


def report_to_dict(report: AnalysisReport) -> dict[str, object]:
    return {
        "profile_id": report.profile_id,
        "base_dir": str(report.base_dir),
        "generated_at": report.generated_at.isoformat(timespec="seconds"),
        "cancelled": report.cancelled,
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
        f"- **Файлов:** {len(report.files)}",
        f"- **Объём:** {human_size(report.total_size)}",
        f"- **Ошибок:** {len(report.errors)}",
        f"- **Прервано:** {'да' if report.cancelled else 'нет'}",
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
            for note in insight.notes:
                lines.append(f"- {note}")
            if insight.archive_entries:
                lines.append(f"- Записей в архиве: {len(insight.archive_entries)}")
            if insight.preview:
                lines += ["", "```text", insight.preview[:500], "```"]
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_report(
    report: AnalysisReport,
    *,
    output_dir: Path = REPORTS_DIR,
    stem: str | None = None,
) -> tuple[Path, Path]:
    """Сохраняет отчёт в JSON и Markdown. Возвращает (json_path, md_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    name = stem or f"report-{report.generated_at:%Y%m%d-%H%M%S}"

    json_path = output_dir / f"{name}.json"
    md_path = output_dir / f"{name}.md"

    payload = json.dumps(report_to_dict(report), ensure_ascii=False, indent=2)
    json_path.write_text(payload, encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
