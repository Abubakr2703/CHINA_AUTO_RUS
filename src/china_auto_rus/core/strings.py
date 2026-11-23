"""Поиск текстовых строк в бинарных данных.

Модуль не зависит от формата контейнера: он ищет последовательности
печатных символов в UTF-8, UTF-16 LE/BE и GBK. Это позволяет находить
текст в незнакомой прошивке, структура которой ещё не разобрана.

Только чтение: модуль не меняет ни байты, ни файлы.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from china_auto_rus.core.cjk_frequency import COMMON_CJK

DEFAULT_MIN_LENGTH = 4
DEFAULT_MAX_STRINGS = 20_000
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

_ASCII_PRINTABLE = frozenset(range(0x20, 0x7F))
_TAB = 0x09
_VOWELS = frozenset("aeiouAEIOU")
_CJK_PUNCT = frozenset("，。！？：；、（）《》「」【】…—·～　")


@dataclass(frozen=True, slots=True)
class StringHit:
    """Найденная строка: смещение в байтах, кодировка и текст."""

    offset: int
    encoding: str
    text: str


@dataclass(frozen=True, slots=True)
class StringScan:
    """Результат поиска строк в одном файле или буфере."""

    hits: tuple[StringHit, ...]
    scanned_bytes: int
    truncated: bool


def is_cjk(char: str) -> bool:
    """Иероглифы, включая расширение A и совместимость."""
    return (
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
    )


def contains_cjk(text: str) -> bool:
    return any(is_cjk(char) for char in text)


def _is_text_char(char: str) -> bool:
    """Символ, который может быть частью строки интерфейса.

    Разрешаем только письменности, которые встречаются в ГУ: латиницу,
    иероглифы, кириллицу и китайскую пунктуацию. Хангыль и кана в случайных
    байтах дают слишком много ложных строк.
    """
    if char == "\t":
        return True
    if not char.isprintable():
        return False
    if unicodedata.category(char)[0] == "C":
        return False
    return (
        char.isascii()
        or is_cjk(char)
        or "\u0400" <= char <= "\u04ff"
        or "\u3000" <= char <= "\u303f"
        or "\uff00" <= char <= "\uffef"
    )


def _looks_like_text(text: str) -> bool:
    """Отсекает мусорные последовательности, где почти нет букв и цифр."""
    if not text:
        return False
    meaningful = sum(1 for char in text if char.isalnum() or char.isspace())
    return meaningful / len(text) >= 0.5


def _cjk_share_ok(text: str) -> bool:
    """В настоящем тексте иероглифы в основном частотные, в мусоре — редкие."""
    cjk = [char for char in text if is_cjk(char)]
    if not cjk:
        return True
    # Два случайных иероглифа рядом с латиницей — ещё не китайская строка.
    if len(cjk) < 3:
        return False
    common = sum(1 for char in cjk if char in COMMON_CJK)
    return common / len(cjk) >= 0.75


def _odd_chars_ok(text: str) -> bool:
    """Разрешает китайскую пунктуацию, но не случайные экзотические символы."""
    for char in text:
        if char.isascii() or is_cjk(char) or "\u0400" <= char <= "\u04ff":
            continue
        if char in _CJK_PUNCT:
            continue
        return False
    return True


def _cyrillic_ok(text: str) -> bool:
    """Одна случайная кириллическая буква в мусоре — не русская строка."""
    cyrillic = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
    return cyrillic == 0 or cyrillic >= 3


def _ascii_plausible(text: str) -> bool:
    """Случайные 4-6 символов латиницы — ещё не строка интерфейса."""
    if not text.isascii():
        return True
    stripped = text.strip()
    words = [word for word in stripped.split() if len(word) >= 3]
    if len(words) >= 2 and any(
        char in _VOWELS for word in words for char in word
    ):
        return True
    vowels = sum(1 for char in stripped if char in _VOWELS)
    return len(stripped) >= 8 and vowels >= 2


def _plausible(text: str) -> bool:
    return (
        _looks_like_text(text)
        and _cjk_share_ok(text)
        and _cyrillic_ok(text)
        and _odd_chars_ok(text)
        and _ascii_plausible(text)
    )


def _trim_edges(text: str) -> str:
    """Срезает редкие иероглифы и мусор по краям найденной строки.

    Начало и конец строки в бинарнике часто «залипают» на соседних байтах:
    получается один редкий иероглиф перед настоящим текстом. Частотные
    иероглифы и латиница остаются, редкие — отбрасываются.
    """

    def edge_junk(char: str) -> bool:
        if char.isascii():
            return False
        return not (is_cjk(char) and char in COMMON_CJK)

    start, end = 0, len(text)
    while start < end and edge_junk(text[start]):
        start += 1
    while end > start and edge_junk(text[end - 1]):
        end -= 1
    return text[start:end]


def _utf8_sequence_length(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 2
    if 0xE0 <= lead <= 0xEF:
        return 3
    if 0xF0 <= lead <= 0xF4:
        return 4
    return 0


def _utf8_runs(data: bytes, min_length: int) -> list[tuple[int, str]]:
    runs: list[tuple[int, str]] = []
    start = -1
    chars: list[str] = []
    index = 0
    size = len(data)

    while index < size:
        byte = data[index]
        char: str | None = None
        step = 1
        if byte in _ASCII_PRINTABLE or byte == _TAB:
            char = chr(byte)
        elif byte >= 0x80:
            step = _utf8_sequence_length(byte)
            if step and index + step <= size:
                try:
                    char = data[index : index + step].decode("utf-8")
                except UnicodeDecodeError:
                    char = None
            else:
                step = 1

        if char is not None and _is_text_char(char):
            if start < 0:
                start = index
            chars.append(char)
        else:
            if start >= 0 and len(chars) >= min_length:
                runs.append((start, "".join(chars)))
            start = -1
            chars = []
        index += step

    if start >= 0 and len(chars) >= min_length:
        runs.append((start, "".join(chars)))
    return runs


def _utf16_runs(
    data: bytes, encoding: str, min_length: int
) -> list[tuple[int, str]]:
    """Читает пары байтов, поэтому работает и для ASCII, и для иероглифов."""
    byteorder: Literal["little", "big"] = (
        "little" if encoding.endswith("le") else "big"
    )
    runs: list[tuple[int, str]] = []
    size = len(data)

    for offset in (0, 1):
        start = -1
        chars: list[str] = []
        index = offset
        while index + 1 < size:
            value = int.from_bytes(data[index : index + 2], byteorder)
            char = chr(value)
            if _is_text_char(char):
                if start < 0:
                    start = index
                chars.append(char)
            else:
                if start >= 0 and len(chars) >= min_length:
                    runs.append((start, "".join(chars)))
                start = -1
                chars = []
            index += 2
        if start >= 0 and len(chars) >= min_length:
            runs.append((start, "".join(chars)))
    return runs


def _gbk_runs(data: bytes, min_length: int) -> list[tuple[int, str]]:
    threshold = min_length
    runs: list[tuple[int, str]] = []
    start = -1
    chars: list[str] = []
    index = 0
    size = len(data)

    while index < size:
        byte = data[index]
        char: str | None = None
        step = 1
        if byte in _ASCII_PRINTABLE or byte == _TAB:
            char = chr(byte)
        elif 0x81 <= byte <= 0xFE and index + 1 < size:
            step = 2
            try:
                char = data[index : index + 2].decode("gbk")
            except UnicodeDecodeError:
                char = None

        if char is not None and _is_text_char(char):
            if start < 0:
                start = index
            chars.append(char)
        else:
            if start >= 0 and len(chars) >= threshold:
                runs.append((start, "".join(chars)))
            start = -1
            chars = []
        index += step

    if start >= 0 and len(chars) >= threshold:
        runs.append((start, "".join(chars)))
    return runs


def extract_strings(
    data: bytes,
    *,
    min_length: int = DEFAULT_MIN_LENGTH,
    max_strings: int = DEFAULT_MAX_STRINGS,
    encodings: Sequence[str] = ("utf-8", "utf-16-le", "utf-16-be", "gbk"),
) -> tuple[StringHit, ...]:
    """Ищет печатные строки в буфере и возвращает их по возрастанию смещения."""
    candidates: list[StringHit] = []

    if "utf-8" in encodings:
        candidates.extend(
            StringHit(offset, "utf-8", text)
            for offset, text in _utf8_runs(data, min_length)
        )
    for encoding in ("utf-16-le", "utf-16-be"):
        if encoding in encodings:
            candidates.extend(
                StringHit(offset, encoding, text)
                for offset, text in _utf16_runs(data, encoding, min_length)
            )
    if "gbk" in encodings:
        candidates.extend(
            StringHit(offset, "gbk", text)
            for offset, text in _gbk_runs(data, min_length)
        )

    # Один и тот же текст часто виден в нескольких кодировках: оставляем
    # первое вхождение, чтобы отчёт не раздувался дублями.
    unique: dict[str, StringHit] = {}
    for hit in candidates:
        text = _trim_edges(hit.text)
        if len(text) < min_length:
            continue
        if not _plausible(text):
            continue
        hit = StringHit(hit.offset, hit.encoding, text)
        current = unique.get(text)
        if current is None or hit.offset < current.offset:
            unique[text] = hit

    hits = sorted(unique.values(), key=lambda hit: (hit.offset, hit.encoding))
    return tuple(hits[:max_strings])


def extract_strings_from_file(
    path: Path,
    *,
    min_length: int = DEFAULT_MIN_LENGTH,
    max_strings: int = DEFAULT_MAX_STRINGS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> StringScan:
    """Читает начало файла и ищет строки. Большие файлы обрезаются."""
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]

    hits = extract_strings(data, min_length=min_length, max_strings=max_strings)
    return StringScan(hits=hits, scanned_bytes=len(data), truncated=truncated)
