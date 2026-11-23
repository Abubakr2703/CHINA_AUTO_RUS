"""Тесты глобальной обработки исключений и логирования без консоли."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

import china_auto_rus.error_handling as error_handling
from china_auto_rus import config
from china_auto_rus.error_handling import (
    USER_MESSAGE,
    handle_exception,
    install_exception_hooks,
)
from china_auto_rus.logging_setup import setup_logging


def _raise_and_handle(notifier: Callable[[str], None] | None = None) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        assert exc_type is not None and exc_value is not None
        handle_exception(exc_type, exc_value, exc_tb, user_notifier=notifier)


def test_handle_exception_logs_traceback(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.CRITICAL):
        _raise_and_handle()

    assert "ValueError" in caplog.text
    assert "boom" in caplog.text
    assert "Traceback" in caplog.text


def test_handle_exception_shows_short_message() -> None:
    messages: list[str] = []

    _raise_and_handle(messages.append)

    assert messages == [USER_MESSAGE]
    assert "Traceback" not in USER_MESSAGE


def test_handle_exception_survives_failing_notifier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_notifier(message: str) -> None:
        raise RuntimeError("notifier failed")

    with caplog.at_level(logging.DEBUG):
        _raise_and_handle(broken_notifier)

    assert "notifier failed" in caplog.text


def test_handle_exception_does_not_recurse() -> None:
    calls: list[str] = []

    def recursive_notifier(message: str) -> None:
        calls.append(message)
        try:
            raise RuntimeError("inner")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None and exc_value is not None
            handle_exception(
                exc_type, exc_value, exc_tb, user_notifier=recursive_notifier
            )

    _raise_and_handle(recursive_notifier)

    assert len(calls) == 1


def test_install_exception_hooks_sets_both_hooks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_excepthook = sys.excepthook
    old_thread_hook = threading.excepthook
    try:
        install_exception_hooks()
        assert sys.excepthook is not old_excepthook
        assert threading.excepthook is not old_thread_hook

        with caplog.at_level(logging.CRITICAL):
            try:
                raise RuntimeError("unhandled")
            except RuntimeError:
                exc_type, exc_value, exc_tb = sys.exc_info()
                assert exc_type is not None and exc_value is not None
                sys.excepthook(exc_type, exc_value, exc_tb)

        assert "RuntimeError" in caplog.text
        assert "unhandled" in caplog.text
    finally:
        sys.excepthook = old_excepthook
        threading.excepthook = old_thread_hook


def test_setup_logging_works_without_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "app.log")
    monkeypatch.setattr(sys, "stderr", None)

    try:
        root.handlers.clear()
        setup_logging()
        console_handlers = [
            handler
            for handler in root.handlers
            if type(handler) is logging.StreamHandler
        ]
        assert console_handlers == []
        assert (tmp_path / "logs" / "app.log").parent.is_dir()
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:] = previous_handlers


def test_error_handling_module_has_no_file_content_access() -> None:
    # Обработчик не должен читать анализируемые файлы: в модуле нет Path/open.
    source = Path(error_handling.__file__).read_text(encoding="utf-8")
    assert "open(" not in source
    assert "read_bytes" not in source
