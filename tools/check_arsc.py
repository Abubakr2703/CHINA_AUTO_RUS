"""Проверка записи resources.arsc на реальном файле или APK.

Только чтение: скрипт ничего не сохраняет и не меняет. Нужен, чтобы до
сборки APK убедиться, что writer пересобирает таблицу без потерь.

Запуск:

    python tools/check_arsc.py "C:\\путь\\app.apk"
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.core.arsc_write import ArscWriteError, rebuild_arsc, replace_strings


def load_arsc(path: Path) -> bytes:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return archive.read("resources.arsc")
    return path.read_bytes()


def check(path: Path) -> int:
    data = load_arsc(path)
    original = parse_arsc(data)
    if not original.entries:
        print(f"таблица не разобрана: {original.notes}")
        return 1

    rebuilt = rebuild_arsc(data)
    reparsed = parse_arsc(rebuilt)
    same_model = (
        original.package,
        original.entries,
        original.notes,
    ) == (
        reparsed.package,
        reparsed.entries,
        reparsed.notes,
    )

    print(f"файл: {path.name}")
    print(f"пакет: {original.package}")
    print(f"строк: {len(original.entries)}")
    print(f"размер таблицы: {len(data)} байт")
    print(f"пересборка: {'байт-в-байт' if rebuilt == data else 'изменилась'}")
    print(f"повторный разбор: {'совпадает' if same_model else 'РАСХОДИТСЯ'}")

    sample = [entry.text for entry in original.entries if entry.language.startswith("zh")][:3]
    if not sample:
        sample = [entry.text for entry in original.entries][:3]
    mapping = {text: f"RU::{text}" for text in sample}
    replaced = parse_arsc(replace_strings(data, mapping))
    replaced_texts = {entry.text for entry in replaced.entries}
    applied = sum(1 for text in sample if f"RU::{text}" in replaced_texts)
    print(f"тестовая замена: {applied} из {len(sample)}")

    if not same_model or applied != len(sample):
        return 1
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Проверить запись resources.arsc")
    parser.add_argument("path", type=Path, help="APK или файл resources.arsc")
    arguments = parser.parse_args()

    try:
        return check(arguments.path)
    except (ArscWriteError, KeyError, zipfile.BadZipFile, OSError) as error:
        print(f"ошибка: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
