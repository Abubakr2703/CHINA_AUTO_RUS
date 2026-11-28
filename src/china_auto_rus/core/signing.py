"""Подготовка APK к переподписи: снятие старой подписи.

Подпись APK живёт в двух местах: файлы ``META-INF/*.SF``, ``*.RSA``, ``*.DSA``,
``*.EC`` (v1) и блок подписи между данными и central directory (v2/v3).
Пересборка архива через ``zipfile`` убирает блок подписи сама, остаётся
удалить файлы v1.
"""

from __future__ import annotations

import io
import zipfile

SIGNATURE_SUFFIXES = (".SF", ".RSA", ".DSA", ".EC")


class SigningError(Exception):
    """APK не удалось подготовить к переподписи."""


def is_signature_entry(name: str) -> bool:
    """Файл подписи v1 внутри ``META-INF``."""
    if not name.startswith("META-INF/"):
        return False
    return name.upper().endswith(SIGNATURE_SUFFIXES)


def strip_signatures(apk: bytes) -> bytes:
    """Возвращает копию APK без старой подписи.

    Содержимое остальных записей, порядок и сжатие сохраняются.
    """
    if not apk:
        raise SigningError("пустой APK")
    try:
        with zipfile.ZipFile(io.BytesIO(apk)) as source:
            entries = [
                (info, source.read(info))
                for info in source.infolist()
                if not is_signature_entry(info.filename)
            ]
            comment = source.comment
    except zipfile.BadZipFile as error:
        raise SigningError(f"APK повреждён: {error}") from error
    except (KeyError, OSError, RuntimeError) as error:
        raise SigningError(f"APK не читается: {error}") from error

    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w") as target:
            target.comment = comment
            for info, data in entries:
                clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                clone.compress_type = info.compress_type
                clone.external_attr = info.external_attr
                clone.internal_attr = info.internal_attr
                clone.create_system = info.create_system
                clone.comment = info.comment
                clone.extra = info.extra
                target.writestr(clone, data)
    except (OSError, RuntimeError, ValueError) as error:
        raise SigningError(f"APK не собирается: {error}") from error
    return output.getvalue()
