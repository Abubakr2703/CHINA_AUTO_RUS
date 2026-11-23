"""Тесты точки входа: понятная ошибка при отсутствии PySide6."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import china_auto_rus.__main__ as main_module
from china_auto_rus import config


def _isolate_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает побочные эффекты: консоль, логи, глобальные хуки."""
    monkeypatch.setattr(main_module, "_configure_console", lambda: None)
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "install_exception_hooks", lambda *args, **kwargs: None)


def test_missing_pyside6_returns_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)

    def missing() -> Callable[[list[str]], int]:
        raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")

    monkeypatch.setattr(main_module, "_load_gui", missing)

    assert main_module.main([]) == main_module.EXIT_MISSING_GUI

    stderr = capsys.readouterr().err
    assert "PySide6" in stderr
    assert ".venv" in stderr
    assert "Traceback" not in stderr


def test_unrelated_import_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_main(monkeypatch)

    def broken() -> Callable[[list[str]], int]:
        raise ModuleNotFoundError("No module named 'requests'", name="requests")

    monkeypatch.setattr(main_module, "_load_gui", broken)

    with pytest.raises(ModuleNotFoundError):
        main_module.main([])


def test_gui_mode_starts_application(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate_main(monkeypatch)
    calls: list[list[str]] = []

    def fake_gui(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(main_module, "_load_gui", lambda: fake_gui)

    assert main_module.main([]) == 0
    assert calls == [[]]


def test_check_mode_does_not_start_gui(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    monkeypatch.setattr(main_module, "ensure_directories", lambda: None)

    def fail() -> Callable[[list[str]], int]:
        raise AssertionError("GUI не должен запускаться в режиме --check")

    monkeypatch.setattr(main_module, "_load_gui", fail)

    assert main_module.main(["--check"]) == 0
    assert "CHINA AUTO RUS" in capsys.readouterr().out


def test_strings_mode_finds_chinese_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x00\x00" + "设置导航目的地".encode())

    assert main_module.main(["--strings", str(path)]) == 0

    output = capsys.readouterr().out
    assert "设置导航目的地" in output
    assert "С китайскими иероглифами: 1" in output


def test_strings_mode_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)

    assert main_module.main(["--strings", str(tmp_path / "nope.bin")]) == 1
    assert "не найден" in capsys.readouterr().err


def test_resources_mode_extracts_and_exports_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    values = tmp_path / "res" / "values-zh-rCN"
    values.mkdir(parents=True)
    (values / "strings.xml").write_text(
        '<resources><string name="settings_title">设置</string></resources>',
        encoding="utf-8",
    )
    csv_path = tmp_path / "out" / "strings.csv"

    assert (
        main_module.main(
            ["--resources", str(tmp_path / "res"), "--csv", str(csv_path)]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Строк: 1" in output
    assert "zh-CN" in output
    assert csv_path.exists()
    assert "设置" in csv_path.read_text(encoding="utf-8-sig")


def test_resources_mode_missing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)

    assert main_module.main(["--resources", str(tmp_path / "nope")]) == 1
    assert "не найден" in capsys.readouterr().err


def _translation_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Path:
    _isolate_main(monkeypatch)
    values = tmp_path / "res" / "values"
    values.mkdir(parents=True)
    (values / "strings.xml").write_text(
        "<resources>"
        '<string name="settings_title">设置</string>'
        '<string name="files">文件 %d</string>'
        "</resources>",
        encoding="utf-8",
    )
    path = tmp_path / "translations.csv"

    assert (
        main_module.main(
            ["--resources", str(tmp_path / "res"), "--translation-csv", str(path)]
        )
        == 0
    )
    capsys.readouterr()
    return path


def test_translation_template_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _translation_template(tmp_path, monkeypatch, capsys)

    template = path.read_text(encoding="utf-8-sig")
    assert "original,translation" in template
    assert "设置" in template


def test_check_translations_reports_broken_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _translation_template(tmp_path, monkeypatch, capsys)
    path.write_text(
        "source,key,original,translation\n"
        "strings.xml,settings_title,设置,Настройки\n"
        "strings.xml,files,文件 %d,Файлов\n",
        encoding="utf-8-sig",
    )

    assert main_module.main(["--check-translations", str(path)]) == 1

    output = capsys.readouterr().out
    assert "переведено: 2 (100.0%)" in output
    assert "плейсхолдеры" in output
    assert "Ошибок: 1" in output


def test_check_translations_clean_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    path = tmp_path / "translations.csv"
    path.write_text(
        "source,key,original,translation\n"
        "strings.xml,settings_title,设置,Настройки\n"
        "strings.xml,files,文件 %d,Файлов: %d\n",
        encoding="utf-8-sig",
    )

    assert main_module.main(["--check-translations", str(path)]) == 0

    output = capsys.readouterr().out
    assert "Ошибок: 0" in output
    assert "Уникальных текстов: 2" in output


def test_check_translations_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)

    assert (
        main_module.main(["--check-translations", str(tmp_path / "nope.csv")]) == 1
    )
    assert "не найден" in capsys.readouterr().err


def test_profiles_mode_lists_builtin_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")

    assert main_module.main(["--profiles"]) == 0

    output = capsys.readouterr().out
    assert "deepal-s07-2026-cn-restyling" in output
    assert "Changan Deepal S07 2026 (CN)" in output


def test_profiles_mode_reports_broken_user_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    directory = tmp_path / "profiles"
    directory.mkdir()
    (directory / "broken.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(config, "PROFILES_DIR", directory)

    assert main_module.main(["--profiles"]) == 1

    output = capsys.readouterr().out
    assert "broken.json" in output
    assert "Сломанных профилей: 1" in output


def test_unknown_profile_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate_main(monkeypatch)
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    source = tmp_path / "source"
    source.mkdir()

    assert (
        main_module.main(["--analyze", str(source), "--profile", "nope"]) == 1
    )

    assert "Профиль не найден: nope" in capsys.readouterr().err

