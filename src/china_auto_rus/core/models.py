"""Модели данных ядра. Не зависят от PySide6."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class FileKind(StrEnum):
    """Формат файла, определённый по сигнатурам, а не только по расширению."""

    APK = "apk"
    ZIP = "zip"
    XML = "xml"
    JSON = "json"
    TEXT = "text"
    ELF = "elf"
    DEX = "dex"
    SQLITE = "sqlite"
    IMAGE = "image"
    # Известная бинарная сигнатура без отдельного парсера.
    BINARY = "binary"
    # Расширение заявляет формат, но содержимое ему не соответствует.
    UNSUPPORTED = "unsupported"
    # Формат достоверно определить нельзя.
    UNKNOWN = "unknown"


class Stage(StrEnum):
    """Этап работы, к которому относится событие прогресса."""

    SCAN = "scan"
    ANALYZE = "analyze"


class EncodingConfidence(StrEnum):
    """Насколько можно доверять определённой кодировке."""

    HIGH = "high"
    LOW = "low"


class CompletionState(StrEnum):
    """Состояние, с которым анализ завершился."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: Path
    relative_path: str
    size: int
    kind: FileKind
    sha256: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    size: int
    compressed_size: int
    is_dir: bool


@dataclass(frozen=True, slots=True)
class FileInsight:
    """Результат разбора содержимого одного файла."""

    relative_path: str
    encoding: str | None = None
    preview: str | None = None
    archive_entries: tuple[ArchiveEntry, ...] = ()
    notes: tuple[str, ...] = ()
    # Для неоднозначных байтов кодировка не выбирается наугад.
    encoding_confidence: EncodingConfidence = EncodingConfidence.HIGH
    encoding_candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanError:
    path: str
    message: str


@dataclass(slots=True)
class ScanResult:
    base_dir: Path
    files: list[FileEntry] = field(default_factory=list)
    errors: list[ScanError] = field(default_factory=list)
    cancelled: bool = False
    # Имя сработавшего ограничения: "max_files", "max_total_bytes", "max_errors".
    # None означает, что скан завершился без достижения лимитов.
    limit_reached: str | None = None


@dataclass(slots=True)
class AnalysisReport:
    profile_id: str
    base_dir: Path
    generated_at: datetime
    files: list[FileEntry]
    insights: list[FileInsight]
    errors: list[ScanError]
    cancelled: bool
    total_size: int
    kind_counts: dict[str, int]
    # Перенесено из ScanResult, чтобы отчёт явно показывал неполный анализ.
    limit_reached: str | None = None
    # Временные метки и итоги анализа. Заполняются build_report(); значения
    # по умолчанию нужны для совместимости со старыми отчётами и тестами.
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    successful_files: int = 0
    completion_state: CompletionState = CompletionState.COMPLETED


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: Stage
    processed: int
    total: int | None
    current: str
