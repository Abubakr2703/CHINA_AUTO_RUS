"""Сборка переведённого APK: CSV → замена строк → новый архив.

Всё в памяти и без побочных эффектов: функция принимает байты APK и строки
шаблона, возвращает новые байты и отчёт. Запись на диск — дело вызывающего.

Подпись после замены недействительна. Финальные шаги — ``zipalign`` и
``apksigner`` — внешние инструменты, в проект не входят.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass

from china_auto_rus.core.apk_write import ApkWriteError, replace_resources
from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.core.arsc_write import ArscWriteError, replace_strings
from china_auto_rus.core.translation import TranslationRow, build_replacements

RESOURCES_ARSC = "resources.arsc"


class BuildError(Exception):
    """APK нельзя собрать с этим шаблоном перевода."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Результат сборки и цифры для отчёта."""

    apk: bytes
    replacements: int
    changed_entries: int
    entries: int
    missing: tuple[str, ...]


def _read_arsc(apk: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(apk)) as archive:
            return archive.read(RESOURCES_ARSC)
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise BuildError(f"resources.arsc не читается: {error}") from error


def build_apk(apk: bytes, rows: Iterable[TranslationRow]) -> BuildResult:
    """Возвращает APK с русскими строками и сводку замен."""
    replacements = build_replacements(rows)
    if not replacements:
        raise BuildError("в шаблоне нет ни одного заполненного перевода")

    arsc = _read_arsc(apk)
    original = parse_arsc(arsc)
    if not original.entries:
        message = "; ".join(original.notes) or "таблица пуста"
        raise BuildError(f"resources.arsc не разобран: {message}")

    known = {entry.text for entry in original.entries}
    missing = tuple(text for text in replacements if text not in known)

    try:
        translated = replace_strings(arsc, replacements)
        rebuilt = replace_resources(apk, translated)
    except (ArscWriteError, ApkWriteError) as error:
        raise BuildError(str(error)) from error

    updated = parse_arsc(translated)
    changed = sum(
        1
        for before, after in zip(original.entries, updated.entries, strict=False)
        if before.text != after.text
    )

    return BuildResult(
        apk=rebuilt,
        replacements=len(replacements),
        changed_entries=changed,
        entries=len(original.entries),
        missing=missing,
    )
