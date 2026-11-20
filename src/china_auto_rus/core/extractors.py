"""Извлечение данных: текст, кодировки, содержимое ZIP/APK. Только чтение."""

from __future__ import annotations

import codecs
import zipfile
from dataclasses import dataclass
from pathlib import Path

from china_auto_rus.core.models import ArchiveEntry, FileEntry, FileInsight, FileKind

SAMPLE_SIZE = 64 * 1024
DEFAULT_PREVIEW_CHARS = 2000
DEFAULT_MAX_ARCHIVE_ENTRIES = 2000


@dataclass(frozen=True, slots=True)
class TextPreview:
    encoding: str
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class ArchiveListing:
    entries: tuple[ArchiveEntry, ...]
    total: int
    notes: tuple[str, ...]


def detect_encoding(raw: bytes) -> str:
    """UTF-8 → UTF-16 (BOM) → GBK. Без внешних зависимостей."""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    for encoding in ("utf-8", "gbk"):
        try:
            raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return "utf-8"


def read_text_preview(
    path: Path,
    *,
    limit: int = DEFAULT_PREVIEW_CHARS,
    sample_size: int = SAMPLE_SIZE,
) -> TextPreview:
    with path.open("rb") as stream:
        raw = stream.read(sample_size)
    encoding = detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    truncated = len(raw) == sample_size or len(text) > limit
    return TextPreview(encoding=encoding, text=text[:limit], truncated=truncated)


def list_archive(
    path: Path,
    *,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
) -> ArchiveListing:
    """Читает только центральный каталог архива, ничего не распаковывая."""
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()

    entries = tuple(
        ArchiveEntry(
            name=info.filename,
            size=info.file_size,
            compressed_size=info.compress_size,
            is_dir=info.is_dir(),
        )
        for info in infos[:max_entries]
    )

    names = {info.filename for info in infos}
    notes: list[str] = []
    if len(infos) > max_entries:
        notes.append(f"показаны первые {max_entries} из {len(infos)} записей")
    if "resources.arsc" in names:
        notes.append("resources.arsc — бинарная таблица ресурсов, разбор на Этапе 3")
    if "AndroidManifest.xml" in names:
        notes.append("AndroidManifest.xml — бинарный AXML, разбор на Этапе 3")

    return ArchiveListing(entries=entries, total=len(infos), notes=tuple(notes))


def analyze_entry(
    entry: FileEntry,
    *,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
    max_archive_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
) -> FileInsight:
    """Разбирает содержимое файла в зависимости от определённого формата."""
    if entry.kind in {FileKind.TEXT, FileKind.XML, FileKind.JSON}:
        preview = read_text_preview(entry.path, limit=preview_chars)
        notes: tuple[str, ...] = ("предпросмотр обрезан",) if preview.truncated else ()
        return FileInsight(
            relative_path=entry.relative_path,
            encoding=preview.encoding,
            preview=preview.text,
            notes=notes,
        )

    if entry.kind in {FileKind.ZIP, FileKind.APK}:
        listing = list_archive(entry.path, max_entries=max_archive_entries)
        notes = listing.notes
        if entry.kind is FileKind.APK:
            notes += ("APK: языковые строки в resources.arsc/AXML — Этап 3",)
        return FileInsight(
            relative_path=entry.relative_path,
            archive_entries=listing.entries,
            notes=notes,
        )

    return FileInsight(relative_path=entry.relative_path)
