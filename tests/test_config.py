"""Тесты конфигурации и профиля автомобиля."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import china_auto_rus.core.report as report_module
from china_auto_rus import config
from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.core.models import AnalysisReport
from china_auto_rus.logging_setup import setup_logging


def test_profiles_dir_is_inside_user_data() -> None:
    assert config.get_profiles_dir() == config.USER_DATA_DIR / "profiles"


def test_ensure_directories_creates_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(config, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(config, "REPORTS_DIR", workspace / "reports")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")

    config.ensure_directories()

    assert (workspace / "reports").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "profiles").is_dir()


def test_user_data_dir_uses_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert config._default_user_data_dir() == tmp_path / config.APP_DIR_NAME


def test_user_data_dir_falls_back_without_localappdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert config._default_user_data_dir() == (
        Path.home() / ".local" / "share" / config.APP_DIR_NAME
    )


def test_user_data_never_goes_to_install_directory() -> None:
    for path in (
        config.USER_DATA_DIR,
        config.REPORTS_DIR,
        config.LOGS_DIR,
        config.SETTINGS_DIR,
    ):
        assert path.parent == config.USER_DATA_DIR or path == config.USER_DATA_DIR
        assert config.PROJECT_ROOT not in path.parents


def test_ensure_directories_creates_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path / "workspace")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")

    config.ensure_directories()

    assert (tmp_path / "reports").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "settings").is_dir()
    assert (tmp_path / "workspace").is_dir()
    assert (tmp_path / "profiles").is_dir()


def test_save_report_default_dir_follows_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    report: AnalysisReport = analyze_paths([source])
    target = tmp_path / "user_data" / "reports"
    monkeypatch.setattr(config, "REPORTS_DIR", target)

    json_path, md_path = report_module.save_report(report)

    assert json_path.parent == target
    assert md_path.parent == target
    assert json_path.exists() and md_path.exists()


def test_setup_logging_uses_configured_log_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "app.log")

    try:
        root.handlers.clear()
        setup_logging()
        file_handlers = [
            handler
            for handler in root.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == tmp_path / "logs" / "app.log"
        assert (tmp_path / "logs" / "app.log").parent.is_dir()
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = previous_handlers
