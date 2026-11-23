"""Извлечение данных: текст, кодировки, содержимое ZIP/APK. Только чтение."""

from __future__ import annotations

import codecs
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

from china_auto_rus.core.models import (
    ArchiveEntry,
    EncodingConfidence,
    FileEntry,
    FileInsight,
    FileKind,
)

SAMPLE_SIZE = 64 * 1024
DEFAULT_PREVIEW_CHARS = 2000
DEFAULT_MAX_ARCHIVE_ENTRIES = 2000

AMBIGUOUS_ENCODING = "ambiguous"
UNKNOWN_ENCODING = "unknown"

# UTF-32 начинается с BOM UTF-16, поэтому проверяем его раньше.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

_CJK_RANGES = (
    ("\u3400", "\u4dbf"),
    ("\u4e00", "\u9fff"),
    # GB18030 кодирует расширение B и совместимость иероглифов 4 байтами.
    ("\U00020000", "\U0002a6df"),
    ("\U0002f800", "\U0002fa1f"),
)
_CYRILLIC_START, _CYRILLIC_END = "\u0400", "\u04ff"
_COMMON_RUSSIAN = frozenset("оеаинтсрвлкмдпуяыьгзбчйхжшюцщэфъё")


@dataclass(frozen=True, slots=True)
class TextPreview:
    encoding: str
    text: str
    truncated: bool
    confidence: EncodingConfidence = EncodingConfidence.HIGH
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArchiveListing:
    entries: tuple[ArchiveEntry, ...]
    total: int
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EncodingDecision:
    """Результат определения кодировки вместе с обещанием честности.

    При низкой уверенности ``encoding`` не является названием кодировки:
    пользователю показываются все правдоподобные варианты и исходные байты.
    """

    encoding: str
    confidence: EncodingConfidence
    candidates: tuple[str, ...] = ()
    variants: tuple[tuple[str, str], ...] = ()
    raw: bytes = b""


def _decode(raw: bytes, encoding: str) -> str | None:
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return None


def _sane_ratio(text: str) -> float:
    """Доля «обычных» символов: без управляющих и без U+FFFD."""
    if not text:
        return 0.0
    sane = sum(
        1
        for char in text
        if char != "\ufffd" and not unicodedata.category(char).startswith("C")
    )
    return sane / len(text)


def _in_ranges(char: str, ranges: tuple[tuple[str, str], ...]) -> bool:
    return any(start <= char <= end for start, end in ranges)


def _script_plausible(text: str, script: str) -> bool:
    """Эвристика: похож ли текст на письмо, которое мы проверяем."""
    if _sane_ratio(text) < 0.9:
        return False
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    if script == "cjk":
        hits = sum(1 for char in letters if _in_ranges(char, _CJK_RANGES))
        return hits / len(letters) >= 0.6

    cyrillic = [
        char for char in letters if _CYRILLIC_START <= char <= _CYRILLIC_END
    ]
    if not cyrillic or len(cyrillic) / len(letters) < 0.6:
        return False
    # Кириллица сама по себе ещё не доказательство: GBK-байты тоже могут
    # дать «похожие» буквы. Проверяем частотность букв русского языка.
    common = sum(1 for char in cyrillic if char.lower() in _COMMON_RUSSIAN)
    return common / len(cyrillic) >= 0.85


def _utf16_without_bom(raw: bytes) -> tuple[str, str] | None:
    """Распознаёт UTF-16 без BOM по регулярным нулевым байтам."""
    if len(raw) < 4 or len(raw) % 2:
        return None
    half = len(raw) // 2
    even_zero = raw[0::2].count(0) / half
    odd_zero = raw[1::2].count(0) / half
    if odd_zero >= 0.6 and even_zero <= 0.2:
        encoding = "utf-16-le"
    elif even_zero >= 0.6 and odd_zero <= 0.2:
        encoding = "utf-16-be"
    else:
        return None
    text = _decode(raw, encoding)
    if text is None or _sane_ratio(text) < 0.9:
        return None
    return encoding, text


def detect_encoding_detailed(raw: bytes) -> EncodingDecision:
    """Определяет кодировку, не выдавая гадание за достоверный факт."""
    if not raw:
        return EncodingDecision(
            encoding="utf-8",
            confidence=EncodingConfidence.HIGH,
            candidates=("utf-8",),
            variants=(("utf-8", ""),),
        )

    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            text = _decode(raw, encoding)
            if text is not None:
                text = text.lstrip("\ufeff")
                return EncodingDecision(
                    encoding,
                    EncodingConfidence.HIGH,
                    (encoding,),
                    ((encoding, text),),
                    raw,
                )
            # BOM есть, но данные битые: не гадаем по остатку байтов.
            break

    text = _decode(raw, "utf-8")
    if text is not None and _sane_ratio(text) >= 0.9:
        return EncodingDecision(
            "utf-8",
            EncodingConfidence.HIGH,
            ("utf-8",),
            (("utf-8", text),),
            raw,
        )

    utf16 = _utf16_without_bom(raw)
    if utf16 is not None:
        encoding, text = utf16
        return EncodingDecision(
            encoding,
            EncodingConfidence.HIGH,
            (encoding,),
            ((encoding, text),),
            raw,
        )

    variants: list[tuple[str, str]] = []
    for encoding, script in (("gbk", "cjk"), ("gb18030", "cjk"), ("cp1251", "cyr")):
        candidate = _decode(raw, encoding)
        if candidate is None or not _script_plausible(candidate, script):
            continue
        # GB18030 — надмножество GBK: те же байты дают тот же текст.
        if any(candidate == known for _, known in variants):
            continue
        variants.append((encoding, candidate))

    if not variants:
        return EncodingDecision(
            UNKNOWN_ENCODING, EncodingConfidence.LOW, (), (), raw
        )
    if len(variants) == 1:
        encoding, text = variants[0]
        return EncodingDecision(
            encoding,
            EncodingConfidence.HIGH,
            (encoding,),
            tuple(variants),
            raw,
        )
    return EncodingDecision(
        AMBIGUOUS_ENCODING,
        EncodingConfidence.LOW,
        tuple(name for name, _ in variants),
        tuple(variants),
        raw,
    )


def detect_encoding(raw: bytes) -> str:
    """Упрощённый API: имя кодировки или 'ambiguous' / 'unknown'.

    Для неоднозначных байтов используйте ``detect_encoding_detailed()``:
    он возвращает список кандидатов и их тексты.
    """
    return detect_encoding_detailed(raw).encoding


def read_text_preview(
    path: Path,
    *,
    limit: int = DEFAULT_PREVIEW_CHARS,
    sample_size: int = SAMPLE_SIZE,
) -> TextPreview:
    with path.open("rb") as stream:
        raw = stream.read(sample_size)

    decision = detect_encoding_detailed(raw)
    if decision.confidence is EncodingConfidence.LOW:
        parts = [
            "Кодировка определена неточно: "
            + (", ".join(decision.candidates) or "нет вариантов"),
            "Исходные байты (hex): " + raw[:512].hex(" "),
        ]
        for name, variant in decision.variants:
            parts += ["", f"--- {name} ---", variant]
        text = "\n".join(parts)
    else:
        text = decision.variants[0][1] if decision.variants else ""

    truncated = len(raw) == sample_size or len(text) > limit
    return TextPreview(
        encoding=decision.encoding,
        text=text[:limit],
        truncated=truncated,
        confidence=decision.confidence,
        candidates=decision.candidates,
    )


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
        notes.append("resources.arsc — бинарная таблица ресурсов, см. --resources")
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
        if preview.confidence is EncodingConfidence.LOW:
            notes += (
                "кодировка неоднозначна: "
                + (", ".join(preview.candidates) or "вариантов нет"),
            )
        return FileInsight(
            relative_path=entry.relative_path,
            encoding=preview.encoding,
            preview=preview.text,
            notes=notes,
            encoding_confidence=preview.confidence,
            encoding_candidates=preview.candidates,
        )

    if entry.kind in {FileKind.ZIP, FileKind.APK}:
        listing = list_archive(entry.path, max_entries=max_archive_entries)
        notes = listing.notes
        if entry.kind is FileKind.APK:
            notes += ("APK: строки интерфейса — в resources.arsc, см. --resources",)
        return FileInsight(
            relative_path=entry.relative_path,
            archive_entries=listing.entries,
            notes=notes,
        )

    return FileInsight(relative_path=entry.relative_path)
