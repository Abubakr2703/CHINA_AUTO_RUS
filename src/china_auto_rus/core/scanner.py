"""Сканирование файлов: обход, SHA-256, определение формата.

Модуль работает только на чтение и не изменяет исходные файлы.
"""

from __future__ import annotations

import codecs
import hashlib
import logging
import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from china_auto_rus.core.models import (
    FileEntry,
    FileKind,
    ProgressEvent,
    ScanError,
    ScanResult,
    Stage,
)

logger = logging.getLogger(__name__)

HEAD_SIZE = 4096
CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_DEPTH = 64

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Считает SHA-256 потоково, не загружая файл в память целиком."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _is_text_like(head: bytes) -> bool:
    if not head or b"\x00" in head:
        return False
    control = sum(1 for byte in head if byte < 9 or 13 < byte < 32)
    return control / len(head) < 0.05


def detect_kind(path: Path, head: bytes) -> FileKind:
    """Определяет формат по сигнатурам; расширение — только уточнение."""
    suffix = path.suffix.lower()

    if head.startswith(_ZIP_MAGIC):
        return FileKind.APK if suffix == ".apk" else FileKind.ZIP
    if head.startswith(b"\x7fELF"):
        return FileKind.ELF
    if head.startswith(b"dex\n"):
        return FileKind.DEX
    if head.startswith(b"SQLite format 3\x00"):
        return FileKind.SQLITE
    if head.startswith(_IMAGE_MAGIC):
        return FileKind.IMAGE
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return FileKind.XML if suffix == ".xml" else FileKind.TEXT
    if _is_text_like(head):
        stripped = head.lstrip()
        if suffix == ".xml" or stripped.startswith(b"<?xml"):
            return FileKind.XML
        if suffix == ".json":
            return FileKind.JSON
        return FileKind.TEXT
    return FileKind.UNKNOWN


def _read_head(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(HEAD_SIZE)


def _describe(exc: OSError) -> str:
    return exc.strerror or str(exc)


def _is_reparse_point(path: Path) -> bool:
    """Защита от циклов через symlink/junction на Windows."""
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def _iter_files(
    root: Path,
    *,
    max_depth: int,
    should_cancel: Callable[[], bool] | None,
    on_error: Callable[[ScanError], None],
) -> Iterator[Path]:
    if root.is_file():
        yield root
        return

    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.lower())
        except OSError as exc:
            on_error(ScanError(str(directory), _describe(exc)))
            continue

        for entry in entries:
            if should_cancel is not None and should_cancel():
                return
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_reparse_point(path):
                        continue
                    if depth >= max_depth:
                        on_error(ScanError(str(path), f"превышена глубина {max_depth}"))
                        continue
                    stack.append((path, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    yield path
            except OSError as exc:
                on_error(ScanError(str(path), _describe(exc)))


def _common_base(paths: Sequence[Path]) -> Path:
    anchors = [path if path.is_dir() else path.parent for path in paths]
    try:
        return Path(os.path.commonpath([str(anchor) for anchor in anchors]))
    except ValueError:
        return anchors[0]


def _relative(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _build_entry(path: Path, base_dir: Path, compute_hash: bool) -> FileEntry:
    error: str | None = None
    size = 0
    try:
        size = path.stat().st_size
    except OSError as exc:
        error = _describe(exc)

    try:
        head = _read_head(path)
    except OSError as exc:
        head = b""
        error = error or _describe(exc)

    digest: str | None = None
    if compute_hash:
        try:
            digest = sha256_file(path)
        except OSError as exc:
            error = error or _describe(exc)

    return FileEntry(
        path=path,
        relative_path=_relative(path, base_dir),
        size=size,
        kind=detect_kind(path, head),
        sha256=digest,
        error=error,
    )


def scan_paths(
    paths: Sequence[Path | str],
    *,
    compute_hashes: bool = True,
    max_depth: int = DEFAULT_MAX_DEPTH,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> ScanResult:
    """Сканирует файлы и папки. Возвращает результат, не меняя исходники."""
    requested = [Path(path) for path in paths]
    errors: list[ScanError] = []
    existing: list[Path] = []

    for path in requested:
        if path.exists():
            existing.append(path)
        else:
            errors.append(ScanError(str(path), "путь не найден"))

    if not existing:
        return ScanResult(base_dir=Path("."), errors=errors)

    base_dir = _common_base(existing)
    result = ScanResult(base_dir=base_dir, errors=errors)
    seen: set[str] = set()
    cancelled = False

    def on_error(error: ScanError) -> None:
        logger.warning("Ошибка доступа: %s — %s", error.path, error.message)
        errors.append(error)

    processed = 0
    for root in existing:
        for file_path in _iter_files(
            root,
            max_depth=max_depth,
            should_cancel=should_cancel,
            on_error=on_error,
        ):
            key = os.path.normcase(str(file_path))
            if key in seen:
                continue
            seen.add(key)

            entry = _build_entry(file_path, base_dir, compute_hashes)
            if entry.error:
                on_error(ScanError(entry.relative_path, entry.error))
            result.files.append(entry)
            processed += 1

            if on_progress is not None:
                on_progress(ProgressEvent(Stage.SCAN, processed, None, entry.relative_path))

            if should_cancel is not None and should_cancel():
                cancelled = True
                break
        if cancelled:
            break

    if should_cancel is not None and should_cancel():
        cancelled = True
    result.cancelled = cancelled
    logger.info("Просканировано файлов: %d, ошибок: %d", len(result.files), len(errors))
    return result
