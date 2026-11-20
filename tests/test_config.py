"""Тесты конфигурации и профиля автомобиля."""

from __future__ import annotations

from pathlib import Path

from china_auto_rus import config


def test_default_profile_matches_deepal_s07() -> None:
    profile = config.DEFAULT_PROFILE
    assert profile.brand == "Changan"
    assert profile.model == "Deepal S07"
    assert profile.year == 2026
    assert profile.market == "CN"


def test_unknown_characteristics_stay_unknown() -> None:
    profile = config.DEFAULT_PROFILE
    assert profile.head_unit is None
    assert profile.hardware_platform is None


def test_display_name() -> None:
    assert config.DEFAULT_PROFILE.display_name == "Changan Deepal S07 2026 (CN)"


def test_ensure_directories_creates_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(config, "WORKSPACE_DIR", workspace)
    monkeypatch.setattr(config, "REPORTS_DIR", workspace / "reports")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")

    config.ensure_directories()

    assert (workspace / "reports").is_dir()
    assert (tmp_path / "logs").is_dir()
