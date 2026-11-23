"""Глобальная обработка необработанных исключений.

Обработчик пишет traceback в лог и показывает пользователю понятное
сообщение вместо технической трассировки. Работает и при запуске через
``pythonw.exe``, когда консоли и ``sys.stderr`` нет.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from types import TracebackType

logger = logging.getLogger(__name__)

USER_MESSAGE = "Произошла непредвиденная ошибка. Подробности записаны в лог."

_user_notifier: Callable[[str], None] | None = None
# Защита от рекурсии: исключение внутри обработчика не должно вызывать
# новый обработчик бесконечно.
_handler_state = threading.local()


def _format_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    *,
    user_notifier: Callable[[str], None] | None = None,
) -> None:
    """Логирует исключение и безопасно уведомляет пользователя."""
    if getattr(_handler_state, "active", False):
        return

    _handler_state.active = True
    try:
        try:
            logger.critical(
                "Необработанное исключение:\n%s",
                _format_exception(exc_type, exc_value, exc_tb),
            )
        except Exception:
            if sys.stderr is not None:
                traceback.print_exception(exc_type, exc_value, exc_tb)

        notifier = user_notifier if user_notifier is not None else _user_notifier
        if notifier is not None:
            try:
                notifier(USER_MESSAGE)
            except Exception:
                try:
                    logger.exception("Не удалось показать сообщение об ошибке")
                except Exception:
                    if sys.stderr is not None:
                        traceback.print_exc()
    finally:
        _handler_state.active = False


def install_exception_hooks(
    user_notifier: Callable[[str], None] | None = None,
) -> None:
    """Ставит обработчики для главного и фоновых потоков."""
    global _user_notifier
    _user_notifier = user_notifier

    def main_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        handle_exception(exc_type, exc_value, exc_tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = main_hook
    threading.excepthook = thread_hook
