"""Smoke-тесты вкладки русификации на offscreen-платформе."""

from __future__ import annotations

import csv
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from china_auto_rus.core.arsc import parse_arsc
from china_auto_rus.ui.russification_tab import RussificationTab
from tests.arsc_fixture import build_sample

TRANSLATION_CSV = """source,key,original,translation
zh-CN,string/settings_title,设置,Параметры
"""


def _pump_until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        QApplication.processEvents()
        if time.monotonic() > deadline:
            pytest.fail("условие не выполнено за отведённое время")
        time.sleep(0.005)


def _write_apk(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        archive.writestr("resources.arsc", build_sample())


def _texts(apk: Path) -> set[str]:
    with zipfile.ZipFile(apk) as archive:
        return {entry.text for entry in parse_arsc(archive.read("resources.arsc")).entries}


def test_buttons_follow_inputs(qapp: object, tmp_path: Path) -> None:
    apk = tmp_path / "app.apk"
    _write_apk(apk)
    template = tmp_path / "ru.csv"
    template.write_text(TRANSLATION_CSV, encoding="utf-8")

    tab = RussificationTab()
    assert not tab.extract_button.isEnabled()
    assert not tab.check_button.isEnabled()

    tab.apk_edit.setText(str(apk))
    assert tab.extract_button.isEnabled()
    assert not tab.check_button.isEnabled()

    tab.template_edit.setText(str(template))
    assert tab.check_button.isEnabled()
    assert tab.build_apk_button.isEnabled()

    tab.template_edit.setText(str(tmp_path / "нет.csv"))
    assert not tab.build_apk_button.isEnabled()

    tab.deleteLater()


def test_extract_template_writes_csv(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apk = tmp_path / "app.apk"
    _write_apk(apk)
    template = tmp_path / "translation.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(template), "")),
    )

    tab = RussificationTab()
    tab.apk_edit.setText(str(apk))
    tab._extract_template()
    _pump_until(lambda: not tab.is_busy())

    assert template.is_file()
    with template.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert set(rows[0]) == {"source", "key", "original", "translation"}
    assert tab.template_edit.text() == str(template)

    tab.deleteLater()


def test_build_apk_writes_translated_copy(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apk = tmp_path / "app.apk"
    _write_apk(apk)
    template = tmp_path / "ru.csv"
    template.write_text(TRANSLATION_CSV, encoding="utf-8")
    output = tmp_path / "app-ru.apk"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "")),
    )

    tab = RussificationTab()
    tab.apk_edit.setText(str(apk))
    tab.template_edit.setText(str(template))
    tab._build_apk()
    _pump_until(lambda: not tab.is_busy())

    assert output.is_file()
    assert "Параметры" in _texts(output)
    assert "Параметры" not in _texts(apk)
    assert tab.status.text() == "APK собран"

    tab.deleteLater()


def test_build_apk_reports_mismatched_template(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apk = tmp_path / "app.apk"
    _write_apk(apk)
    template = tmp_path / "ru.csv"
    template.write_text(
        "source,key,original,translation\n"
        "zh-CN,string/other,строки нет в APK,Перевод\n",
        encoding="utf-8",
    )
    output = tmp_path / "app-ru.apk"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(output), "")),
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda _parent, _title, text: warnings.append(text)),
    )

    tab = RussificationTab()
    tab.apk_edit.setText(str(apk))
    tab.template_edit.setText(str(template))
    tab._build_apk()
    _pump_until(lambda: not tab.is_busy())

    assert not output.exists()
    assert warnings
    assert "не совпала" in warnings[0]
    assert tab.status.text() == "Ошибка"

    tab.deleteLater()
