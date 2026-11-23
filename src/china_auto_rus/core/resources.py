"""Извлечение языковых ресурсов: ключ → текст → язык. Только чтение.

Модуль понимает три источника текста, которые встречаются в Android-ГУ:

* бинарную таблицу ``resources.arsc`` внутри APK — основной источник строк
  системных приложений;
* XML-ресурсы Android (``res/values/strings.xml`` и локализованные
  ``res/values-<язык>/strings.xml``);
* JSON-файлы локализации (``assets/lang/ru.json``, ``i18n/zh-CN.json``).

Плюс обратный импорт уже переведённой таблицы CSV.

Сжатый ``AndroidManifest.xml`` (бинарный AXML) здесь не разбирается: его
строки почти не участвуют в интерфейсе, а формат требует отдельного парсера.
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.core.locale import (
    DEFAULT_LANGUAGE,
    is_known_language,
    normalize_language,
)

DEFAULT_MAX_FILES = 500
DEFAULT_MAX_ENTRIES = 50_000
MAX_FILE_BYTES = 8 * 1024 * 1024

CSV_HEADER = ("source", "language", "key", "text")

# res/values/strings.xml, res/values-zh-rCN/strings.xml, values-ru/strings.xml
_ANDROID_VALUES = re.compile(
    r"(?:^|[\\/])values(?:-([A-Za-z0-9+_\-]+))?[\\/]([^\\/]+\.xml)$"
)
_LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}$")
_REGION_TAG = re.compile(r"^(?:r([A-Z]{2})|([A-Z]{2}))$")
# Языковой суффикс в имени файла: ru.json, strings_zh-CN.json, lang.de.json
_NAME_LANGUAGE = re.compile(r"(?:^|[._-])([a-z]{2,3}(?:-[A-Za-z]{2,4})?)$")


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    """Одна пара «ключ → текст» с указанием языка и источника."""

    key: str
    text: str
    language: str
    source: str


@dataclass(frozen=True, slots=True)
class ResourceFile:
    """Все строки одного файла ресурсов."""

    source: str
    language: str
    entries: tuple[ResourceEntry, ...]
    notes: tuple[str, ...] = ()


def language_from_qualifiers(qualifiers: str) -> str:
    """``zh-rCN`` → ``zh-CN``, ``ru`` → ``ru``, ``b+sr+Latn`` → ``sr-Latn``."""
    if not qualifiers:
        return DEFAULT_LANGUAGE
    qualifiers = qualifiers.split("-")[0] if qualifiers.startswith("b+") else qualifiers
    if qualifiers.startswith("b+"):
        return normalize_language("-".join(
            part for part in qualifiers[2:].split("+") if part
        ))

    parts = qualifiers.split("-")
    language = parts[0]
    if not _LANGUAGE_TAG.match(language) or not is_known_language(language):
        return DEFAULT_LANGUAGE
    for part in parts[1:]:
        match = _REGION_TAG.match(part)
        if match:
            return normalize_language(
                f"{language}-{match.group(1) or match.group(2)}"
            )
    return normalize_language(language)


def language_from_path(name: str) -> str:
    """Определяет язык по пути внутри дерева ресурсов или по имени файла."""
    match = _ANDROID_VALUES.search(name)
    if match:
        return language_from_qualifiers(match.group(1) or "")

    stem = Path(name.replace("\\", "/")).stem
    match = _NAME_LANGUAGE.search(stem)
    if match:
        code = match.group(1)
        if is_known_language(code):
            return normalize_language(code)
    return DEFAULT_LANGUAGE


def is_resource_candidate(name: str) -> bool:
    """Файл вообще может содержать строки интерфейса?"""
    normalized = name.replace("\\", "/")
    if normalized.endswith(".json"):
        return True
    return bool(_ANDROID_VALUES.search(normalized))


def _xml_text(element: ElementTree.Element) -> str:
    """Текст элемента вместе с вложенными тегами (``<b>``, ``<xliff:g>``)."""
    return "".join(element.itertext()).strip()


def _local_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_xml_strings(
    data: bytes,
    *,
    source: str,
    language: str = DEFAULT_LANGUAGE,
) -> ResourceFile:
    """Разбирает ``strings.xml``-подобный файл Android."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return ResourceFile(
            source,
            language,
            (),
            ("не удалось разобрать XML: возможно, это бинарный AXML",),
        )

    entries: list[ResourceEntry] = []

    def add(key: str, text: str) -> None:
        if key:
            entries.append(ResourceEntry(key, text, language, source))

    if _local_tag(root) in {"string", "item"}:
        add(root.get("name") or "", _xml_text(root))

    for child in root:
        tag = _local_tag(child)
        name = child.get("name") or ""
        if tag == "string":
            add(name, _xml_text(child))
        elif tag in {"string-array", "array", "integer-array"}:
            for index, item in enumerate(child):
                add(f"{name}[{index}]", _xml_text(item))
        elif tag == "plurals":
            for item in child:
                quantity = item.get("quantity") or str(len(entries))
                add(f"{name}[{quantity}]", _xml_text(item))
        elif tag == "item":
            add(name, _xml_text(child))

    return ResourceFile(source, language, tuple(entries))


def _flatten_json(node: object, prefix: str) -> Iterator[tuple[str, str]]:
    """Превращает вложенный JSON в плоские ключи ``a.b[0].c``."""
    if isinstance(node, dict):
        for key, value in node.items():
            nested = f"{prefix}.{key}" if prefix else str(key)
            yield from _flatten_json(value, nested)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _flatten_json(value, f"{prefix}[{index}]")
    elif isinstance(node, str):
        yield prefix, node


def parse_json_strings(
    data: bytes,
    *,
    source: str,
    language: str = DEFAULT_LANGUAGE,
) -> ResourceFile:
    """Разбирает JSON-файл локализации, оставляя только строковые значения."""
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return ResourceFile(
            source, language, (), (f"не удалось разобрать JSON: {error}",)
        )

    entries = tuple(
        ResourceEntry(key, text, language, source)
        for key, text in _flatten_json(payload, "")
    )
    return ResourceFile(source, language, entries)


def parse_resource_bytes(
    data: bytes,
    *,
    source: str,
    language: str | None = None,
) -> ResourceFile:
    """Выбирает парсер по расширению источника."""
    resolved = language or language_from_path(source)
    if source.lower().endswith(".json"):
        return parse_json_strings(data, source=source, language=resolved)
    return parse_xml_strings(data, source=source, language=resolved)


def extract_resource_file(
    path: Path,
    *,
    source: str | None = None,
    language: str | None = None,
    max_bytes: int = MAX_FILE_BYTES,
) -> ResourceFile:
    """Читает файл ресурсов с диска. Большие файлы не читаются целиком."""
    label = source or path.name
    if path.stat().st_size > max_bytes:
        return ResourceFile(
            label,
            language or language_from_path(label),
            (),
            (f"файл больше {max_bytes} байт и пропущен",),
        )
    return parse_resource_bytes(
        path.read_bytes(), source=label, language=language
    )


def extract_from_directory(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> tuple[ResourceFile, ...]:
    """Обходит каталог и собирает все файлы ресурсов."""
    collected: list[ResourceFile] = []
    total = 0
    skipped = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        source = path.relative_to(root).as_posix()
        if not is_resource_candidate(source):
            continue
        if len(collected) >= max_files:
            skipped += 1
            continue
        result = extract_resource_file(path, source=source)
        total += len(result.entries)
        collected.append(result)
        if total >= max_entries:
            break

    if skipped:
        collected.append(
            ResourceFile(
                "<каталог>",
                DEFAULT_LANGUAGE,
                (),
                (f"пропущено файлов сверх лимита: {skipped}",),
            )
        )
    return tuple(collected)


def extract_from_zip(
    path: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> tuple[ResourceFile, ...]:
    """Читает ресурсы прямо из APK/ZIP, не распаковывая архив на диск."""
    collected: list[ResourceFile] = []
    total = 0
    skipped_big = 0
    skipped_limit = 0

    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not is_resource_candidate(info.filename):
                continue
            if info.file_size > MAX_FILE_BYTES:
                skipped_big += 1
                continue
            if len(collected) >= max_files:
                skipped_limit += 1
                continue
            data = archive.read(info)
            result = parse_resource_bytes(data, source=info.filename)
            collected.append(result)
            total += len(result.entries)
            if total >= max_entries:
                break

        names = set(archive.namelist())
        arsc_data = archive.read("resources.arsc") if "resources.arsc" in names else b""

    notes: list[str] = []
    if skipped_big:
        notes.append(f"пропущено файлов больше {MAX_FILE_BYTES} байт: {skipped_big}")
    if skipped_limit:
        notes.append(f"пропущено файлов сверх лимита: {skipped_limit}")

    if arsc_data:
        table = parse_arsc(arsc_data)
        grouped: dict[str, list[ResourceEntry]] = {}
        for arsc_entry in table.entries:
            language = normalize_language(arsc_entry.language)
            grouped.setdefault(language, []).append(
                ResourceEntry(
                    key=arsc_entry.resource,
                    text=arsc_entry.text,
                    language=language,
                    source="resources.arsc",
                )
            )
        for language in sorted(grouped):
            collected.append(
                ResourceFile("resources.arsc", language, tuple(grouped[language]))
            )
        notes.extend(table.notes)
    elif "resources.arsc" in names:
        notes.append("resources.arsc не прочитан")

    if notes:
        collected.append(ResourceFile("<APK>", DEFAULT_LANGUAGE, (), tuple(notes)))
    return tuple(collected)


def extract_resources(
    path: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> tuple[ResourceFile, ...]:
    """Единая точка входа: каталог, APK/ZIP или отдельный файл."""
    if path.is_dir():
        return extract_from_directory(
            path, max_files=max_files, max_entries=max_entries
        )
    if zipfile.is_zipfile(path):
        return extract_from_zip(path, max_files=max_files, max_entries=max_entries)
    return (extract_resource_file(path),)


def export_csv(files: Iterable[ResourceFile], path: Path) -> int:
    """Пишет таблицу перевода и возвращает число строк.

    Кодировка ``utf-8-sig``: Excel открывает китайский текст без «кракозябр».
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(CSV_HEADER)
        for resource_file in files:
            for entry in resource_file.entries:
                writer.writerow(
                    (entry.source, entry.language, entry.key, entry.text)
                )
                count += 1
    return count


def read_csv(path: Path) -> tuple[ResourceEntry, ...]:
    """Обратный импорт: читает таблицу, полученную ``export_csv``."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            return ()
        missing = set(CSV_HEADER) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"в CSV нет колонок: {', '.join(sorted(missing))}")
        return tuple(
            ResourceEntry(
                key=row["key"] or "",
                text=row["text"] or "",
                language=row["language"] or DEFAULT_LANGUAGE,
                source=row["source"] or "",
            )
            for row in reader
        )
