"""Тесты поиска строк в бинарных данных."""

from __future__ import annotations

import random
from pathlib import Path

from china_auto_rus.core.strings import (
    contains_cjk,
    extract_strings,
    extract_strings_from_file,
    is_cjk,
)


def test_extract_utf8_chinese() -> None:
    hits = extract_strings("设置导航目的地".encode())

    assert [hit.text for hit in hits] == ["设置导航目的地"]
    assert hits[0].encoding == "utf-8"


def test_extract_utf16le_chinese() -> None:
    hits = extract_strings("蓝牙连接失败".encode("utf-16-le"))

    assert any(hit.text == "蓝牙连接失败" for hit in hits)
    assert any(hit.encoding == "utf-16-le" for hit in hits)


def test_extract_utf16be_ascii() -> None:
    hits = extract_strings("Hello world".encode("utf-16-be"))

    assert any(hit.text == "Hello world" for hit in hits)


def test_extract_gbk_chinese() -> None:
    hits = extract_strings("请选择系统语言".encode("gbk"), encodings=("gbk",))

    assert [hit.text for hit in hits] == ["请选择系统语言"]
    assert hits[0].encoding == "gbk"


def test_gbk_short_label_needs_lower_min_length() -> None:
    raw = "引擎盖".encode("gbk")

    assert extract_strings(raw, encodings=("gbk",)) == ()
    hits = extract_strings(raw, min_length=3, encodings=("gbk",))
    assert [hit.text for hit in hits] == ["引擎盖"]


def test_offsets_are_byte_positions() -> None:
    prefix = b"\x00\x01\x02"
    hits = extract_strings(prefix + "你好世界".encode())

    assert hits
    assert hits[0].offset == len(prefix)


def test_min_length_filters_short_runs() -> None:
    hits = extract_strings(b"ab\x00\x00cd", min_length=4)

    assert hits == ()


def test_duplicates_are_collapsed() -> None:
    hits = extract_strings("设置导航目的地".encode() * 3)

    assert len(hits) == 1


def test_random_bytes_produce_few_candidates() -> None:
    data = random.Random(1).randbytes(50_000)

    hits = extract_strings(data)

    # Полностью убрать ложные срабатывания нельзя, но их должно быть мало.
    assert len(hits) < 10


def test_mixed_payload_finds_all_encodings() -> None:
    payload = (
        b"\x00\x01"
        + "设置导航目的地".encode()
        + b"\xff"
        + "蓝牙连接失败".encode("utf-16-le")
        + b"\x00"
        + "请选择系统语言".encode("gbk")
        + b"\x00"
        + b"Hello world settings"
    )

    texts = {hit.text for hit in extract_strings(payload)}

    assert "设置导航目的地" in texts
    assert "蓝牙连接失败" in texts
    assert "请选择系统语言" in texts
    assert "Hello world settings" in texts


def test_contains_cjk_and_is_cjk() -> None:
    assert is_cjk("你")
    assert is_cjk("\u3400")
    assert not is_cjk("A")
    assert contains_cjk("蓝牙 2.0")
    assert not contains_cjk("Bluetooth")


def test_extract_from_file_keeps_bytes(tmp_path: Path) -> None:
    raw = b"\x00" * 4 + "设置导航目的地".encode() + b"\x00" * 4
    path = tmp_path / "blob.bin"
    path.write_bytes(raw)

    scan = extract_strings_from_file(path)

    assert path.read_bytes() == raw
    assert any(hit.text == "设置导航目的地" for hit in scan.hits)
    assert scan.scanned_bytes == len(raw)
    assert not scan.truncated


def test_extract_from_file_reports_truncation(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"Hello world " * 100)

    scan = extract_strings_from_file(path, max_bytes=64)

    assert scan.truncated
    assert scan.scanned_bytes == 64
