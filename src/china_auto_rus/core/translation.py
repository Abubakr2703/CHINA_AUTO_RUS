"""Библиотека перевода: шаблон для переводчика, импорт и проверка.

Мастера по русификации работают так: извлекают строки, отдают переводчику
таблицу «оригинал → перевод», потом проверяют, что переводчик не сломал
плейсхолдеры и разметку. Здесь ровно эти три шага, без GUI и без записи
в оригинальные файлы.

Модуль только читает и проверяет. Правка APK/ARSC — отдельный этап.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from china_auto_rus.core.resources import ResourceEntry
from china_auto_rus.core.strings import contains_cjk

# Язык, на который переводим. Пока один — русский.
TARGET_LANGUAGE = "ru"

ERROR = "error"
WARNING = "warning"

# Колонки шаблона. ``original`` не перезаписывается: без него нельзя проверить,
# что переводчик сохранил плейсхолдеры.
TRANSLATION_HEADER = ("source", "key", "original", "translation")

# Откуда берём оригинал. Китайский — потому что ГУ китайское; ``default`` —
# потому что в ``res/values/`` лежит исходный язык приложения. Русский в конец:
# он уже перевод, а не оригинал.
SOURCE_LANGUAGE_PRIORITY = (
    "zh-CN",
    "zh-Hans",
    "zh",
    "zh-TW",
    "zh-Hant",
    "default",
)

# %1$s, %d, %.2f, %-5s. Пробел в флагах сознательно не поддержан: иначе
# «100% скидка» превращалось бы в плейсхолдер.
_PRINTF = re.compile(
    r"%(?:(\d+)\$)?([-+0#,(]*)(\d+)?(?:\.(\d+))?([diouxXeEfgGcsb%])"
)
# {0}, {name}, {count, plural, ...} из ICU-подобных фреймворков.
_BRACE = re.compile(r"\{[A-Za-z0-9_.:,\- ]+?\}")
# Теги, которые Android рендерит в TextView: <b>, <font color=...>, <br/>.
_HTML_TAG = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9:_-]*)")

# Строки, которые переводчику не нужны: ссылки, почта, имена пакетов, числа.
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://\S*$")
_EMAIL = re.compile(r"^\S+@\S+\.\S+$")
_PACKAGE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
_NUMBERS = re.compile(r"^[\d\s.,:%+\-/()]*$")


@dataclass(frozen=True, slots=True)
class TranslationIssue:
    """Одно замечание к переводу."""

    key: str
    source: str
    code: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class TranslationRow:
    """Строка шаблона: оригинал и (возможно пустой) перевод."""

    source: str
    key: str
    original: str
    translation: str = ""


@dataclass(frozen=True, slots=True)
class UniqueText:
    """Уникальный оригинал и места, где он встречается."""

    text: str
    count: int
    keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranslationReport:
    """Итог проверки шаблона."""

    total: int
    translated: int
    missing: tuple[str, ...]
    issues: tuple[TranslationIssue, ...]

    @property
    def coverage(self) -> float:
        return self.translated / self.total if self.total else 0.0

    @property
    def errors(self) -> tuple[TranslationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == ERROR)

    @property
    def warnings(self) -> tuple[TranslationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == WARNING)


def display_width(text: str) -> int:
    """Ширина строки в «полуширинах»: иероглиф занимает две позиции."""
    return sum(
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in text
    )


def _printf_specs(text: str) -> list[tuple[str, str, str]]:
    """(индекс, тип, как записано) для каждого %-плейсхолдера."""
    specs: list[tuple[str, str, str]] = []
    for match in _PRINTF.finditer(text):
        index, _flags, _width, _precision, conversion = match.groups()
        if conversion == "%":
            continue
        specs.append((index or "", conversion, match.group(0)))
    return specs


def _describe(specs: Sequence[tuple[str, str, str]]) -> str:
    return ", ".join(raw for _, _, raw in specs) or "нет"


def _signature(
    specs: Sequence[tuple[str, str, str]],
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Порядок нумерованных плейсхолдеров не важен, безномерных — важен."""
    indexed = tuple(sorted((index, kind) for index, kind, _ in specs if index))
    positional = tuple(kind for index, kind, _ in specs if not index)
    return indexed, positional


def validate_text(
    original: str,
    translated: str,
    *,
    key: str = "",
    source: str = "",
) -> tuple[TranslationIssue, ...]:
    """Проверяет одну пару «оригинал → перевод»."""
    issues: list[TranslationIssue] = []

    def add(code: str, message: str, severity: str = ERROR) -> None:
        issues.append(TranslationIssue(key, source, code, severity, message))

    if not translated.strip():
        add("empty", "перевод пустой")
        return tuple(issues)

    if translated == original:
        add("untranslated", "перевод совпадает с оригиналом", WARNING)
    if contains_cjk(translated):
        add("cjk_left", "в переводе остались китайские иероглифы")

    source_specs = _printf_specs(original)
    target_specs = _printf_specs(translated)
    if _signature(source_specs) != _signature(target_specs):
        add(
            "placeholder_mismatch",
            f"плейсхолдеры: было [{_describe(source_specs)}], "
            f"стало [{_describe(target_specs)}]",
        )

    source_braces = Counter(_BRACE.findall(original))
    target_braces = Counter(_BRACE.findall(translated))
    if source_braces != target_braces:
        add(
            "brace_mismatch",
            f"фигурные плейсхолдеры: было {sorted(source_braces)}, "
            f"стало {sorted(target_braces)}",
        )

    source_tags = Counter(tag.lower() for tag in _HTML_TAG.findall(original))
    target_tags = Counter(tag.lower() for tag in _HTML_TAG.findall(translated))
    if source_tags != target_tags:
        add(
            "tag_mismatch",
            f"разметка: было {sorted(source_tags)}, стало {sorted(target_tags)}",
        )

    if original.count("\n") != translated.count("\n"):
        add(
            "newline_mismatch",
            f"переводов строк: было {original.count(chr(10))}, "
            f"стало {translated.count(chr(10))}",
            WARNING,
        )

    source_width = display_width(original)
    target_width = display_width(translated)
    if source_width >= 2 and target_width > source_width * 2.5 + 8:
        add(
            "too_long",
            f"строка заметно длиннее оригинала: {target_width} против "
            f"{source_width} (риск обрезки в интерфейсе)",
            WARNING,
        )

    return tuple(issues)


def is_translatable(text: str) -> bool:
    """Строка похожа на текст интерфейса, а не на адрес или число."""
    stripped = text.strip()
    if not stripped:
        return False
    if _NUMBERS.fullmatch(stripped):
        return False
    return not (
        _URL.match(stripped)
        or _EMAIL.match(stripped)
        or _PACKAGE.match(stripped)
    )


def _source_rank(language: str) -> tuple[int, int]:
    """Чем меньше ранг, тем охотнее берём строку как оригинал."""
    normalized = language.lower()
    if normalized.split("-")[0] == TARGET_LANGUAGE:
        return (1, 0)
    for index, candidate in enumerate(SOURCE_LANGUAGE_PRIORITY):
        if normalized == candidate.lower():
            return (0, index)
    return (0, len(SOURCE_LANGUAGE_PRIORITY))


def export_translation_csv(
    entries: Iterable[ResourceEntry], path: Path
) -> int:
    """Пишет шаблон для переводчика и возвращает число строк.

    Для каждого ключа берётся оригинал на китайском (или на языке по
    умолчанию), а не случайная локаль: иначе переводчику достался бы
    африкаанс. Одна и та же строка в двух местах переводится один раз.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    best: dict[tuple[str, str], ResourceEntry] = {}
    for entry in entries:
        if not is_translatable(entry.text):
            continue
        identity = (entry.source, entry.key)
        current = best.get(identity)
        if current is None or _source_rank(entry.language) < _source_rank(
            current.language
        ):
            best[identity] = entry

    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(TRANSLATION_HEADER)
        for entry in best.values():
            writer.writerow((entry.source, entry.key, entry.text, ""))
    return len(best)


def read_translation_csv(path: Path) -> tuple[TranslationRow, ...]:
    """Читает заполненный шаблон. Пустые строки Excel не считаются переводом."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            return ()
        missing = set(TRANSLATION_HEADER) - set(reader.fieldnames)
        if missing:
            raise ValueError(
                "в CSV нет колонок: " + ", ".join(sorted(missing))
            )
        return tuple(
            TranslationRow(
                source=row.get("source") or "",
                key=row.get("key") or "",
                original=row.get("original") or "",
                translation=row.get("translation") or "",
            )
            for row in reader
        )


def unique_texts(rows: Iterable[TranslationRow]) -> tuple[UniqueText, ...]:
    """Группирует одинаковые оригиналы: столько строк реально нужно перевести."""
    grouped: dict[str, list[TranslationRow]] = {}
    for row in rows:
        if row.original.strip():
            grouped.setdefault(row.original, []).append(row)

    items = [
        UniqueText(
            text=text,
            count=len(group),
            keys=tuple(f"{row.source}:{row.key}" for row in group[:5]),
        )
        for text, group in grouped.items()
    ]
    items.sort(key=lambda item: (-item.count, item.text))
    return tuple(items)


def _label(row: TranslationRow) -> str:
    return f"{row.source}:{row.key}" if row.source else row.key


def check_translations(
    rows: Sequence[TranslationRow],
) -> TranslationReport:
    """Проверяет весь шаблон: пустые переводы, дубли, сломанные плейсхолдеры."""
    issues: list[TranslationIssue] = []
    missing: list[str] = []
    translated = 0
    seen: Counter[tuple[str, str]] = Counter()

    for row in rows:
        identity = (row.source, row.key)
        seen[identity] += 1
        if seen[identity] > 1:
            issues.append(
                TranslationIssue(
                    row.key,
                    row.source,
                    "duplicate",
                    WARNING,
                    f"строка повторяется {seen[identity]}-й раз",
                )
            )
        if not row.translation.strip():
            missing.append(_label(row))
            continue
        translated += 1
        issues.extend(
            validate_text(
                row.original,
                row.translation,
                key=row.key,
                source=row.source,
            )
        )

    return TranslationReport(
        total=len(rows),
        translated=translated,
        missing=tuple(missing),
        issues=tuple(issues),
    )


def build_replacements(rows: Iterable[TranslationRow]) -> dict[str, str]:
    """Карта «оригинал → перевод» для замены строк в resources.arsc.

    Пустые переводы и строки без изменений пропускаются. Если один оригинал
    встретился несколько раз, побеждает первый: шаблон дедуплицирован,
    а расхождения лучше ловить через ``check_translations``.
    """
    replacements: dict[str, str] = {}
    for row in rows:
        if not row.original or not row.translation.strip():
            continue
        if row.original == row.translation:
            continue
        replacements.setdefault(row.original, row.translation)
    return replacements


def apply_translations(
    rows: Iterable[TranslationRow],
) -> tuple[ResourceEntry, ...]:
    """Готовые русские строки в формате извлечённых ресурсов.

    Пригодится на этапе сборки: ключ + текст + язык ``ru``.
    """
    return tuple(
        ResourceEntry(
            key=row.key,
            text=row.translation,
            language=TARGET_LANGUAGE,
            source=row.source,
        )
        for row in rows
        if row.translation.strip()
    )
