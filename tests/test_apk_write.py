"""Тесты сборки APK: подмена resources.arsc внутри zip."""

from __future__ import annotations

import io
import zipfile

import pytest

from china_auto_rus.core.apk_write import ApkWriteError, replace_resources
from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.core.arsc_write import replace_strings
from tests.arsc_fixture import build_sample

MANIFEST = b"\x03\x00\x08\x00\x00\x00\x01\x00\x01\x00\x1c\x00manifest"


def build_apk(*, with_arsc: bool = True, comment: bytes = b"comment") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.comment = comment
        manifest = zipfile.ZipInfo("AndroidManifest.xml")
        manifest.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(manifest, MANIFEST)
        if with_arsc:
            stored = zipfile.ZipInfo("resources.arsc")
            stored.compress_type = zipfile.ZIP_STORED
            archive.writestr(stored, build_sample())
        archive.writestr(zipfile.ZipInfo("res/values/strings.xml"), b"<resources/>")
        archive.writestr(zipfile.ZipInfo("assets/файл.txt"), "привет".encode())
    return buffer.getvalue()


def _entries(apk: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(apk)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def test_replace_resources_swaps_only_arsc() -> None:
    original = build_apk()
    translated = replace_strings(build_sample(), {"设置": "Параметры"})

    rebuilt = replace_resources(original, translated)

    before = _entries(original)
    after = _entries(rebuilt)
    assert list(before) == list(after)
    assert after["resources.arsc"] == translated
    for name in before:
        if name != "resources.arsc":
            assert after[name] == before[name]


def test_replace_resources_keeps_comment_and_compression() -> None:
    original = build_apk(comment=b"custom-comment")

    rebuilt = replace_resources(original, build_sample())

    with zipfile.ZipFile(io.BytesIO(rebuilt)) as archive:
        assert archive.comment == b"custom-comment"
        assert archive.getinfo("resources.arsc").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("AndroidManifest.xml").compress_type == zipfile.ZIP_DEFLATED


def test_replace_resources_result_is_parsable() -> None:
    original = build_apk()
    translated = replace_strings(build_sample(), {"设置": "Параметры"})

    rebuilt = replace_resources(original, translated)

    table = parse_arsc(_entries(rebuilt)["resources.arsc"])
    texts = {entry.text for entry in table.entries}
    assert "Параметры" in texts
    assert "开始导航" in texts  # не все строки переведены


def test_replace_resources_rejects_apk_without_arsc() -> None:
    with pytest.raises(ApkWriteError):
        replace_resources(build_apk(with_arsc=False), build_sample())


def test_replace_resources_rejects_broken_zip() -> None:
    with pytest.raises(ApkWriteError):
        replace_resources(b"not a zip file", build_sample())


def test_replace_resources_rejects_empty_input() -> None:
    with pytest.raises(ApkWriteError):
        replace_resources(b"", build_sample())
    with pytest.raises(ApkWriteError):
        replace_resources(build_apk(), b"")
