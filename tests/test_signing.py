"""Тесты снятия подписи APK."""

from __future__ import annotations

import io
import zipfile

import pytest

from china_auto_rus.core.signing import (
    SigningError,
    is_signature_entry,
    strip_signatures,
)

MANIFEST = b"manifest"
SIGNATURE_FILES = (
    "META-INF/MANIFEST.MF",
    "META-INF/CERT.SF",
    "META-INF/CERT.RSA",
    "META-INF/OTHER.DSA",
    "META-INF/KEY.EC",
)


def _apk() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AndroidManifest.xml", MANIFEST)
        archive.writestr("classes.dex", b"dex")
        for name in SIGNATURE_FILES:
            archive.writestr(name, b"signature")
        archive.writestr("META-INF/services/foo", b"not a signature")
    return buffer.getvalue()


def _names(apk: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(apk)) as archive:
        return [info.filename for info in archive.infolist()]


def test_is_signature_entry() -> None:
    assert is_signature_entry("META-INF/CERT.SF")
    assert is_signature_entry("META-INF/CERT.RSA")
    assert is_signature_entry("META-INF/CERT.DSA")
    assert is_signature_entry("META-INF/CERT.EC")
    assert not is_signature_entry("META-INF/MANIFEST.MF")
    assert not is_signature_entry("META-INF/services/foo")
    assert not is_signature_entry("assets/CERT.SF")


def test_strip_signatures_removes_only_signatures() -> None:
    stripped = strip_signatures(_apk())

    names = _names(stripped)
    assert "AndroidManifest.xml" in names
    assert "classes.dex" in names
    assert "META-INF/services/foo" in names
    for name in ("META-INF/CERT.SF", "META-INF/CERT.RSA", "META-INF/CERT.DSA",
                 "META-INF/KEY.EC"):
        assert name not in names
    # MANIFEST.MF не подпись, но при переподписи он не нужен: apksigner
    # пересоберёт его сам. Проверяем, что мы его не трогаем.
    assert "META-INF/MANIFEST.MF" in names


def test_strip_signatures_keeps_content() -> None:
    stripped = strip_signatures(_apk())

    with zipfile.ZipFile(io.BytesIO(stripped)) as archive:
        assert archive.read("AndroidManifest.xml") == MANIFEST
        assert archive.read("classes.dex") == b"dex"


def test_strip_signatures_is_deterministic() -> None:
    apk = _apk()

    assert strip_signatures(apk) == strip_signatures(apk)


def test_strip_signatures_rejects_empty() -> None:
    with pytest.raises(SigningError):
        strip_signatures(b"")


def test_strip_signatures_rejects_broken_zip() -> None:
    with pytest.raises(SigningError):
        strip_signatures(b"not a zip")
