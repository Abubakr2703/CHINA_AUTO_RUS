"""RRO-оверлей: отдельный APK с русскими строками, оригинал не меняется.

Генератор собирает исходники оверлея: ``AndroidManifest.xml`` и
``res/values-ru/strings.xml``. Компиляция и подпись — внешние шаги
(``aapt2 link``, ``zipalign``, ``apksigner``), в зависимости проекта они
не входят.

Важное ограничение записано в ``docs/russification.md``: пользовательский
оверлей не накроет системное приложение, подписанное ключом производителя.
Генератор даёт корректный проект, но применимость проверяется на живом ГУ.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from china_auto_rus.core.translation import TranslationRow

_NAME = re.compile(r"^[a-z_][a-z0-9_.]*$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")
_INVALID_PACKAGE_CHARS = re.compile(r"[^a-z0-9_]")


class RroError(Exception):
    """Оверлей нельзя собрать из этих данных."""


@dataclass(frozen=True, slots=True)
class RroOverlay:
    """Исходники оверлея и статистика."""

    package: str
    target_package: str
    locale: str
    manifest: str
    strings_xml: str
    strings: int
    skipped: tuple[str, ...]


def _escape(text: str) -> str:
    """Экранирует строку для ``strings.xml`` по правилам aapt."""
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    escaped = escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if escaped.startswith("@") or escaped.startswith("?"):
        escaped = "\\" + escaped
    return escaped


def _overlay_package(target_package: str) -> str:
    """Имя пакета оверлея: точки пакета-цели становятся подчёркиваниями."""
    suffix = _INVALID_PACKAGE_CHARS.sub("_", target_package.lower())
    if not suffix or not suffix[0].isalpha():
        suffix = f"p_{suffix}"
    return f"ru.chinaautorius.overlay.{suffix}"


def build_overlay(
    target_package: str,
    rows: Iterable[TranslationRow],
    *,
    locale: str = "ru",
) -> RroOverlay:
    """Собирает манифест и ``strings.xml`` из заполненного шаблона."""
    if not _PACKAGE.fullmatch(target_package):
        raise RroError(f"некорректное имя пакета: {target_package}")
    if not re.fullmatch(r"[a-z]{2,3}(-r[A-Z]{2})?", locale):
        raise RroError(f"некорректная локаль: {locale}")

    strings: dict[str, str] = {}
    skipped: list[str] = []

    for row in rows:
        translation = row.translation.strip()
        if not translation:
            continue
        if not row.key.startswith("string/"):
            skipped.append(f"{row.key}: поддерживаются только строки")
            continue
        name = row.key.split("/", 1)[1]
        if not _NAME.fullmatch(name):
            skipped.append(f"{row.key}: имя не подходит для ресурса")
            continue
        if name in strings and strings[name] != translation:
            skipped.append(f"{row.key}: повтор с другим переводом")
            continue
        strings[name] = translation

    if not strings:
        raise RroError("в шаблоне нет строк для оверлея")

    lines = []
    for name, text in strings.items():
        formatted = ' formatted="false"' if "%" in text else ""
        lines.append(f'    <string name="{name}"{formatted}>{_escape(text)}</string>')

    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
        f'    package="{_overlay_package(target_package)}">\n'
        f'    <overlay android:targetPackage="{target_package}"\n'
        '        android:isStatic="false" android:priority="1" />\n'
        '    <application android:hasCode="false" />\n'
        "</manifest>\n"
    )
    strings_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n" + "\n".join(lines) + "\n</resources>\n"
    )

    return RroOverlay(
        package=_overlay_package(target_package),
        target_package=target_package,
        locale=locale,
        manifest=manifest,
        strings_xml=strings_xml,
        strings=len(strings),
        skipped=tuple(skipped),
    )


def write_overlay(overlay: RroOverlay, directory: Path) -> tuple[Path, Path]:
    """Записывает исходники оверлея. Возвращает пути манифеста и строк."""
    manifest_path = directory / "AndroidManifest.xml"
    strings_path = directory / "res" / f"values-{overlay.locale}" / "strings.xml"
    strings_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(overlay.manifest, encoding="utf-8")
    strings_path.write_text(overlay.strings_xml, encoding="utf-8")
    return manifest_path, strings_path
