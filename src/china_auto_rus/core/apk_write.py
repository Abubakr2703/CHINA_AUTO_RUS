"""Сборка APK: замена ``resources.arsc`` без перепаковки остальных записей.

Zip пересобирается целиком (так работает ``zipfile``), но содержимое всех
файлов, кроме таблицы ресурсов, копируется байт-в-байт. Порядок записей,
сжатие и атрибуты сохраняются.

Подпись после такой замены становится недействительной — это ожидаемо.
Готовый APK нужно выровнять и подписать внешними инструментами
(``zipalign`` и ``apksigner``); в зависимости проекта они не входят.
"""

from __future__ import annotations

import io
import zipfile

RESOURCES_ARSC = "resources.arsc"


class ApkWriteError(Exception):
    """APK нельзя пересобрать."""


def _clone_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """Копия метаданных записи без размеров и CRC."""
    clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    clone.compress_type = info.compress_type
    clone.external_attr = info.external_attr
    clone.internal_attr = info.internal_attr
    clone.create_system = info.create_system
    clone.comment = info.comment
    clone.extra = info.extra
    return clone


def replace_resources(apk: bytes, arsc: bytes) -> bytes:
    """Возвращает новый APK с подменённой таблицей ресурсов.

    Оригинальные байты не меняются: результат — отдельный объект ``bytes``.
    """
    if not apk:
        raise ApkWriteError("пустой APK")
    if not arsc:
        raise ApkWriteError("пустая таблица ресурсов")

    try:
        with zipfile.ZipFile(io.BytesIO(apk)) as source:
            infos = source.infolist()
            names = [info.filename for info in infos]
            if RESOURCES_ARSC not in names:
                raise ApkWriteError("в APK нет resources.arsc")
            payloads = [(info, source.read(info)) for info in infos]
            comment = source.comment
    except zipfile.BadZipFile as error:
        raise ApkWriteError(f"APK повреждён: {error}") from error
    except (KeyError, OSError, RuntimeError) as error:
        raise ApkWriteError(f"APK не читается: {error}") from error

    output = io.BytesIO()
    try:
        with zipfile.ZipFile(output, "w") as target:
            target.comment = comment
            for info, data in payloads:
                if info.filename == RESOURCES_ARSC:
                    data = arsc
                target.writestr(_clone_info(info), data)
    except (OSError, RuntimeError, ValueError) as error:
        raise ApkWriteError(f"APK не собирается: {error}") from error
    return output.getvalue()
