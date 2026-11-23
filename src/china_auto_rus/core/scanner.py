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

# Лимиты защищают от неограниченного роста памяти и размера отчёта.
# 100 000 файлов — с запасом для крупного дампа ГУ, но без риска съесть
# гигабайты на список FileEntry.
DEFAULT_MAX_FILES = 100_000
# 16 ГиБ: типичный дамп прошивки ГУ укладывается в этот объём,
# а хеширование 16 ГиБ занимает десятки секунд, а не минуты.
DEFAULT_MAX_TOTAL_BYTES = 16 * 1024**3
# 1 000 ошибок достаточно для диагностики, но не превращает отчёт в свалку.
DEFAULT_MAX_ERRORS = 1_000

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")

# Известные бинарные сигнатуры, для которых у нас нет отдельного парсера.
# Формат считается BINARY только при совпадении сигнатуры, а не расширения.
_BINARY_MAGIC = (
    b"MZ",  # PE/Windows executable
    b"\x7fELF",  # на случай, если проверка ELF выше изменится
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"%PDF-",
    b"\x1f\x8b",  # gzip
    b"BZh",  # bzip2
    b"\xfd7zXZ\x00",  # xz
    b"7z\xbc\xaf\x27\x1c",  # 7z
    b"Rar!\x1a\x07",  # RAR
    b"\x00asm",  # WebAssembly
    b"OTTO",  # OpenType
    b"ttcf",  # TrueType collection
    b"wOFF",
    b"wOF2",
    b"OggS",
    b"fLaC",
    b"RIFF",  # WAV/AVI
    b"\x1aE\xdf\xa3",  # Matroska
)

# Расширения, которые заявляют конкретный формат. Если магия не совпала,
# это не повод объявлять файл этим форматом (тем более Android-приложением).
_DECLARED_FORMATS = {
    ".apk": FileKind.APK,
    ".zip": FileKind.ZIP,
}


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
    """Определяет формат по сигнатурам; расширение — только уточнение.

    BINARY — известная бинарная сигнатура, UNKNOWN — формат определить
    нельзя, UNSUPPORTED — расширение обещает формат, но содержимое другое.
    """
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
    if head.startswith(_BINARY_MAGIC) or head[4:8] == b"ftyp":
        return FileKind.BINARY
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return FileKind.XML if suffix == ".xml" else FileKind.TEXT
    if _is_text_like(head):
        stripped = head.lstrip()
        if suffix == ".xml" or stripped.startswith(b"<?xml"):
            return FileKind.XML
        if suffix == ".json":
            return FileKind.JSON
        return FileKind.TEXT
    if suffix in _DECLARED_FORMATS:
        return FileKind.UNSUPPORTED
    return FileKind.UNKNOWN


def _read_head(path: Path) -> bytes:
    with path.open("rb") as stream:
        return stream.read(HEAD_SIZE)


def _describe(exc: OSError) -> str:
    return exc.strerror or str(exc)


def describe_exception(exc: Exception) -> str:
    """Тип и текст исключения для диагностики в отчёте.

    Traceback остаётся в логе, а пользователь видит понятное сообщение
    вида ``ValueError: неожиданное значение``.
    """
    message = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


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
        if should_cancel is not None and should_cancel():
            return
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.lower())
        except OSError as exc:
            on_error(ScanError(str(directory), _describe(exc)))
            continue
        except Exception as exc:
            logger.exception("Неожиданная ошибка при чтении каталога %s", directory)
            on_error(ScanError(str(directory), describe_exception(exc)))
            continue

        for entry in entries:
            if should_cancel is not None and should_cancel():
                return
            path = Path(entry.path)
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = not is_dir and entry.is_file(follow_symlinks=False)
                is_reparse = is_dir and _is_reparse_point(path)
            except OSError as exc:
                on_error(ScanError(str(path), _describe(exc)))
                continue
            except Exception as exc:
                logger.exception("Неожиданная ошибка при обходе %s", path)
                on_error(ScanError(str(path), describe_exception(exc)))
                continue

            if is_dir:
                if is_reparse:
                    continue
                if depth >= max_depth:
                    on_error(ScanError(str(path), f"превышена глубина {max_depth}"))
                    continue
                stack.append((path, depth + 1))
            elif is_file:
                # yield вне try: исключение потребителя не должно попадать
                # в обработчик ошибок обхода и притворяться ошибкой файла.
                yield path


def _path_group(path: Path) -> tuple[str, bool]:
    """Не смешиваем разные диски и абсолютные/относительные пути."""
    return (str(path.anchor).lower(), path.is_absolute())


def _common_base(paths: Sequence[Path]) -> Path:
    """Общий базовый каталог или безопасный fallback для «чужих» путей."""
    anchors = [path if path.is_dir() else path.parent for path in paths]
    if not anchors:
        return Path(".")

    try:
        return Path(os.path.commonpath([str(anchor) for anchor in anchors]))
    except ValueError:
        # Разные диски Windows или смешанные абсолютные/относительные пути.
        # Считаем общий префикс внутри самой большой однородной группы.
        groups: dict[tuple[str, bool], list[Path]] = {}
        for anchor in anchors:
            groups.setdefault(_path_group(anchor), []).append(anchor)
        _, group = max(groups.items(), key=lambda item: len(item[1]))
        try:
            return Path(os.path.commonpath([str(anchor) for anchor in group]))
        except ValueError:
            return group[0]


def _safe_path_text(path: Path) -> str:
    """Понятное представление пути, если нельзя получить относительный."""
    return str(path) or "."


def _relative(path: Path, base_dir: Path) -> str:
    if path == base_dir:
        return "."
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        # Разные диски, другой тип пути или путь вне базового каталога.
        return _safe_path_text(path)


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
    max_files: int | None = DEFAULT_MAX_FILES,
    max_total_bytes: int | None = DEFAULT_MAX_TOTAL_BYTES,
    max_errors: int | None = DEFAULT_MAX_ERRORS,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> ScanResult:
    """Сканирует файлы и папки. Возвращает результат, не меняя исходники.

    ``max_files``, ``max_total_bytes`` и ``max_errors`` ограничивают скан.
    ``None`` отключает соответствующий лимит. При достижении лимита обход
    прекращается, а имя лимита сохраняется в ``ScanResult.limit_reached``.
    """
    requested = [Path(path) for path in paths]
    errors: list[ScanError] = []
    existing: list[Path] = []
    limit_reached: str | None = None
    stop_requested = False

    def add_error(error: ScanError) -> None:
        nonlocal limit_reached, stop_requested
        if max_errors is not None and len(errors) >= max_errors:
            limit_reached = limit_reached or "max_errors"
            stop_requested = True
            return
        logger.warning("Ошибка доступа: %s — %s", error.path, error.message)
        errors.append(error)
        if max_errors is not None and len(errors) >= max_errors:
            limit_reached = limit_reached or "max_errors"
            stop_requested = True

    for path in requested:
        if stop_requested:
            break
        if path.exists():
            existing.append(path)
        else:
            add_error(ScanError(str(path), "путь не найден"))

    if not existing:
        logger.info(
            "Сканирование не выполнено: файлов=0, ошибок=%d, лимит=%s",
            len(errors),
            limit_reached,
        )
        return ScanResult(
            base_dir=Path("."),
            errors=errors,
            limit_reached=limit_reached,
        )

    base_dir = _common_base(existing)
    result = ScanResult(base_dir=base_dir, errors=errors)
    seen: set[str] = set()
    cancelled = False
    processed = 0
    total_bytes = 0

    def should_stop() -> bool:
        if stop_requested:
            return True
        return should_cancel is not None and should_cancel()

    for root in existing:
        if stop_requested:
            break
        for file_path in _iter_files(
            root,
            max_depth=max_depth,
            should_cancel=should_stop,
            on_error=add_error,
        ):
            if stop_requested:
                break

            key = os.path.normcase(str(file_path))
            if key in seen:
                continue
            seen.add(key)

            if max_files is not None and len(result.files) >= max_files:
                limit_reached = limit_reached or "max_files"
                stop_requested = True
                break

            try:
                file_size = file_path.stat().st_size
            except OSError:
                file_size = 0

            if (
                max_total_bytes is not None
                and total_bytes + file_size > max_total_bytes
            ):
                limit_reached = limit_reached or "max_total_bytes"
                stop_requested = True
                break

            try:
                entry = _build_entry(file_path, base_dir, compute_hashes)
            except Exception as exc:
                # Неожиданная ошибка одного файла не должна обрывать скан.
                logger.exception("Неожиданная ошибка при обработке %s", file_path)
                entry = FileEntry(
                    path=file_path,
                    relative_path=_relative(file_path, base_dir),
                    size=file_size,
                    kind=FileKind.UNKNOWN,
                    error=describe_exception(exc),
                )
            result.files.append(entry)
            total_bytes += entry.size
            processed += 1

            if entry.error:
                add_error(ScanError(entry.relative_path, entry.error))

            if on_progress is not None:
                on_progress(
                    ProgressEvent(Stage.SCAN, processed, None, entry.relative_path)
                )

            if stop_requested:
                break
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
        if cancelled or stop_requested:
            break

    if should_cancel is not None and should_cancel():
        cancelled = True

    result.cancelled = cancelled
    result.limit_reached = limit_reached
    if limit_reached is not None:
        logger.warning(
            "Сканирование остановлено по лимиту %s: файлов=%d, ошибок=%d",
            limit_reached,
            len(result.files),
            len(errors),
        )
    logger.info("Просканировано файлов: %d, ошибок: %d", len(result.files), len(errors))
    return result
