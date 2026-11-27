"""Вкладка русификации: шаблон → проверка → APK или RRO-оверлей.

Оригинальный APK не изменяется: результат всегда пишется в новый файл,
а оверлей — в отдельную папку с исходниками.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from china_auto_rus.core.build import BuildError, BuildResult, build_apk
from china_auto_rus.core.report import human_size
from china_auto_rus.core.resources import extract_resources
from china_auto_rus.core.rro import RroError, RroOverlay, build_overlay, write_overlay
from china_auto_rus.core.translation import (
    TranslationIssue,
    TranslationReport,
    check_translations,
    export_translation_csv,
    read_translation_csv,
)
from china_auto_rus.ui.workers import FunctionWorker

logger = logging.getLogger(__name__)

T = TypeVar("T")

APK_FILTER = "APK (*.apk);;Все файлы (*)"
CSV_FILTER = "CSV (*.csv);;Все файлы (*)"


def _issue_label(issue: TranslationIssue) -> str:
    return f"{issue.source}:{issue.key}" if issue.source else issue.key


class RussificationTab(QWidget):
    """Пошаговая русификация одного APK без записи в оригинал."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: FunctionWorker | None = None
        self._busy = False
        self._build_ui()
        self._update_buttons()

    # ---------- построение ----------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Оригинальный APK только читается. Результат — новый файл "
            "или отдельная папка оверлея."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.apk_edit = QLineEdit()
        self.apk_edit.setPlaceholderText("APK с головного устройства")
        self.apk_edit.textChanged.connect(self._update_buttons)
        browse_apk = QPushButton("Выбрать…")
        browse_apk.clicked.connect(self._choose_apk)
        self.extract_button = QPushButton("Извлечь шаблон…")
        self.extract_button.clicked.connect(self._extract_template)
        layout.addLayout(
            self._row("APK:", self.apk_edit, browse_apk, self.extract_button)
        )

        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("CSV с заполненной колонкой translation")
        self.template_edit.textChanged.connect(self._update_buttons)
        browse_template = QPushButton("Выбрать…")
        browse_template.clicked.connect(self._choose_template)
        self.check_button = QPushButton("Проверить")
        self.check_button.clicked.connect(self._check_template)
        layout.addLayout(
            self._row("Шаблон:", self.template_edit, browse_template, self.check_button)
        )

        actions = QHBoxLayout()
        self.build_apk_button = QPushButton("Собрать APK…")
        self.build_apk_button.clicked.connect(self._build_apk)
        self.build_rro_button = QPushButton("Собрать RRO…")
        self.build_rro_button.clicked.connect(self._build_rro)
        actions.addWidget(self.build_apk_button)
        actions.addWidget(self.build_rro_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Здесь появятся шаги и результаты.")
        layout.addWidget(self.log, 1)

        self.status = QLabel("Готов")
        layout.addWidget(self.status)

    def _row(
        self, title: str, edit: QLineEdit, *buttons: QPushButton
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        row.addWidget(edit, 1)
        for button in buttons:
            row.addWidget(button)
        return row

    # ---------- выбор файлов ----------

    def _choose_apk(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Выбрать APK", "", APK_FILTER)
        if name:
            self.apk_edit.setText(name)

    def _choose_template(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Выбрать шаблон перевода", "", CSV_FILTER
        )
        if name:
            self.template_edit.setText(name)

    # ---------- операции ----------

    def _extract_template(self) -> None:
        apk = self._apk_path()
        if apk is None:
            return
        default = apk.with_name(f"{apk.stem}-translation.csv")
        name, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить шаблон", str(default), CSV_FILTER
        )
        if not name:
            return
        template = Path(name)

        def task() -> tuple[int, int, int]:
            files = extract_resources(apk)
            rows = export_translation_csv(
                (entry for item in files for entry in item.entries), template
            )
            return len(files), rows, sum(len(item.entries) for item in files)

        def done(result: object) -> None:
            files, rows, total = cast(tuple[int, int, int], result)
            self._log(f"APK: {apk}")
            self._log(f"Файлов ресурсов: {files}, записей: {total}")
            self._log(f"Шаблон: {template} (уникальных строк: {rows})")
            self._log("Заполните колонку translation и нажмите «Проверить».")
            self.template_edit.setText(str(template))
            self.status.setText("Шаблон готов")

        self._run_task(task, done)

    def _check_template(self) -> None:
        template = self._template_path()
        if template is None:
            return

        def task() -> TranslationReport:
            return check_translations(read_translation_csv(template))

        def done(result: object) -> None:
            report = cast(TranslationReport, result)
            self._log(f"Шаблон: {template}")
            self._log(
                f"Строк: {report.total}, переведено: {report.translated} "
                f"({report.coverage:.1%})"
            )
            for issue in report.errors[:10]:
                self._log(f"  ! {_issue_label(issue)}: {issue.message}")
            for issue in report.warnings[:5]:
                self._log(f"  ~ {_issue_label(issue)}: {issue.message}")
            if report.missing:
                self._log(f"Без перевода: {len(report.missing)}")
            self.status.setText(
                "Ошибок нет" if not report.errors else "Есть ошибки"
            )

        self._run_task(task, done)

    def _build_apk(self) -> None:
        apk = self._apk_path()
        template = self._template_path()
        if apk is None or template is None:
            return
        default = apk.with_name(f"{apk.stem}-ru.apk")
        name, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить APK", str(default), APK_FILTER
        )
        if not name:
            return
        output = Path(name)

        def task() -> tuple[BuildResult, int]:
            rows = read_translation_csv(template)
            report = check_translations(rows)
            if report.errors:
                raise BuildError(
                    f"в шаблоне ошибок: {len(report.errors)} — сборка отменена"
                )
            result = build_apk(apk.read_bytes(), rows)
            if result.changed_entries == 0:
                raise BuildError(
                    "ни одна строка не совпала с таблицей APK — "
                    "шаблон снят с другого APK?"
                )
            output.write_bytes(result.apk)
            return result, len(result.apk)

        def done(result: object) -> None:
            build, size = cast(tuple[BuildResult, int], result)
            self._log(f"APK: {apk}")
            self._log(f"Строк в таблице: {build.entries}")
            self._log(f"Переводов в шаблоне: {build.replacements}")
            self._log(f"Изменено записей: {build.changed_entries}")
            if build.missing:
                self._log(f"Не найдено в APK: {len(build.missing)}")
            self._log(f"Результат: {output} ({human_size(size)})")
            self._log("APK не подписан: перед установкой нужны zipalign и apksigner.")
            self.status.setText("APK собран")

        self._run_task(task, done)

    def _build_rro(self) -> None:
        template = self._template_path()
        if template is None:
            return
        package, ok = QInputDialog.getText(
            self,
            "Пакет-цель",
            "Имя пакета из манифеста (например, com.mega.carsettings):",
        )
        if not ok or not package.strip():
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Папка для исходников оверлея"
        )
        if not directory:
            return
        target = Path(directory)

        def task() -> RroOverlay:
            rows = read_translation_csv(template)
            report = check_translations(rows)
            if report.errors:
                raise RroError(
                    f"в шаблоне ошибок: {len(report.errors)} — оверлей не собран"
                )
            overlay = build_overlay(package.strip(), rows)
            write_overlay(overlay, target)
            return overlay

        def done(result: object) -> None:
            overlay = cast(RroOverlay, result)
            self._log(f"Пакет-цель: {overlay.target_package}")
            self._log(f"Пакет оверлея: {overlay.package}")
            self._log(f"Строк в оверлее: {overlay.strings}")
            if overlay.skipped:
                self._log(f"Пропущено: {len(overlay.skipped)}")
            self._log(f"Исходники: {target}")
            self._log("Дальше: aapt2 compile/link, zipalign, apksigner.")
            self.status.setText("Оверлей готов")

        self._run_task(task, done)

    # ---------- фоновая задача ----------

    def _run_task(self, task: Callable[[], T], on_success: Callable[[T], None]) -> None:
        if self._thread is not None:
            self._log("Дождитесь завершения текущей операции.")
            return
        worker = FunctionWorker(task)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_success)
        worker.failed.connect(self._on_failed)
        worker.done.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        self._worker = worker
        self._thread = thread
        self._set_busy(True)
        thread.start()

    def _on_failed(self, message: str) -> None:
        self._log(f"Ошибка: {message}")
        self.status.setText("Ошибка")
        QMessageBox.warning(self, "Операция не выполнена", message)

    def _on_thread_finished(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.wait()
            thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_busy(False)
        if self.status.text() in {"Работаю…", ""}:
            self.status.setText("Готов")

    def is_busy(self) -> bool:
        """Идёт ли фоновая операция (нужно при закрытии окна)."""
        return self._thread is not None

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """Дожидается операции перед закрытием. ``False`` — не успела."""
        thread = self._thread
        if thread is None:
            return True
        thread.quit()
        return thread.wait(timeout_ms)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.status.setText("Работаю…" if busy else self.status.text())
        self._update_buttons()

    # ---------- состояние ----------

    def _path(self, edit: QLineEdit) -> Path | None:
        text = edit.text().strip()
        if not text:
            return None
        path = Path(text)
        return path if path.is_file() else None

    def _apk_path(self) -> Path | None:
        path = self._path(self.apk_edit)
        if path is None:
            self._log("Сначала выберите существующий APK.")
        return path

    def _template_path(self) -> Path | None:
        path = self._path(self.template_edit)
        if path is None:
            self._log("Сначала выберите существующий шаблон CSV.")
        return path

    def _update_buttons(self) -> None:
        has_apk = self._path(self.apk_edit) is not None
        has_template = self._path(self.template_edit) is not None
        idle = not self._busy
        self.extract_button.setEnabled(idle and has_apk)
        self.check_button.setEnabled(idle and has_template)
        self.build_apk_button.setEnabled(idle and has_apk and has_template)
        self.build_rro_button.setEnabled(idle and has_template)

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
        logger.info("Русификация: %s", text)
