"""Главное окно приложения."""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFontDatabase,
    QKeySequence,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QStyle,
    QTableView,
    QTabWidget,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from china_auto_rus import __version__
from china_auto_rus.config import APP_NAME, get_reports_dir
from china_auto_rus.core.models import (
    AnalysisReport,
    FileEntry,
    FileInsight,
    ProgressEvent,
    Stage,
)
from china_auto_rus.core.report import human_size, save_report
from china_auto_rus.profiles import default_profile
from china_auto_rus.ui.file_models import (
    FileTableModel,
    build_tree_model,
    empty_tree_model,
)
from china_auto_rus.ui.russification_tab import RussificationTab
from china_auto_rus.ui.workers import AnalysisWorker

logger = logging.getLogger(__name__)


class AnalysisState(StrEnum):
    """Явное состояние фонового анализа."""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    FINISHED = "finished"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._report: AnalysisReport | None = None
        self._insights: dict[str, FileInsight] = {}
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._state = AnalysisState.IDLE
        self._pending_report: AnalysisReport | None = None
        self._pending_error: str | None = None
        self._close_requested = False
        self._profile = default_profile()

        self.setWindowTitle(f"{APP_NAME} — {self._profile.display_name}")
        self.setMinimumSize(1000, 650)
        self.resize(1280, 820)
        self.setAcceptDrops(True)

        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

    @property
    def state(self) -> AnalysisState:
        """Текущее состояние анализа (для тестов и диагностики)."""
        return self._state

    # ---------- построение интерфейса ----------

    def _build_actions(self) -> None:
        style = self.style()

        self.action_open_file = QAction("Открыть файл…", self)
        self.action_open_file.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open_file.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        )
        self.action_open_file.triggered.connect(self._open_files)

        self.action_open_folder = QAction("Открыть папку…", self)
        self.action_open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.action_open_folder.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.action_open_folder.triggered.connect(self._open_folder)

        self.action_save = QAction("Сохранить отчёт", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.action_save.setEnabled(False)
        self.action_save.triggered.connect(self._save_current_report)

        self.action_cancel = QAction("Отмена", self)
        self.action_cancel.setShortcut(QKeySequence("Esc"))
        self.action_cancel.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        )
        self.action_cancel.setEnabled(False)
        self.action_cancel.triggered.connect(self._cancel_analysis)

        self.action_open_reports = QAction("Открыть папку отчётов", self)
        self.action_open_reports.triggered.connect(self._open_reports_folder)

        self.action_exit = QAction("Выход", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.triggered.connect(self.close)

        self.action_about = QAction("О программе", self)
        self.action_about.triggered.connect(self._show_about)

        self.hash_checkbox = QCheckBox("SHA-256")
        self.hash_checkbox.setChecked(True)
        self.hash_checkbox.setToolTip("Считать SHA-256 для каждого файла")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Файл")
        file_menu.addAction(self.action_open_file)
        file_menu.addAction(self.action_open_folder)
        file_menu.addSeparator()
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_open_reports)
        file_menu.addSeparator()
        file_menu.addAction(self.action_exit)

        help_menu = self.menuBar().addMenu("&Справка")
        help_menu.addAction(self.action_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Основное", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.action_open_file)
        toolbar.addAction(self.action_open_folder)
        toolbar.addSeparator()
        toolbar.addAction(self.action_save)
        toolbar.addSeparator()
        toolbar.addWidget(self.hash_checkbox)
        toolbar.addSeparator()
        toolbar.addAction(self.action_cancel)
        self.addToolBar(toolbar)

    def _build_central(self) -> None:
        self.table_model = FileTableModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(3, 190)

        self.table.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )

        self.tree = QTreeView()
        self._set_tree_model(empty_tree_model())
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)

        self.errors_list = QListWidget()

        self.russification = RussificationTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Файлы")
        self.tabs.addTab(self.tree, "Дерево")
        self.tabs.addTab(self.errors_list, "Ошибки")
        self.tabs.addTab(self.russification, "Русификация")

        self.preview_widget = QWidget()
        preview_layout = QVBoxLayout(self.preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(QLabel("Предпросмотр"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        preview_layout.addWidget(self.preview)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        splitter.addWidget(self.tabs)
        splitter.addWidget(self.preview_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 480])
        self.setCentralWidget(splitter)

    def _on_tab_changed(self, index: int) -> None:
        # У вкладки русификации своя область: предпросмотр ей не нужен.
        current = self.tabs.widget(index)
        self.preview_widget.setVisible(current is not self.russification)

    def _build_statusbar(self) -> None:
        self.status_label = QLabel("Готов")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(240)
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    # ---------- импорт и запуск анализа ----------

    def _open_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выбрать файлы")
        if files:
            self._start_analysis([Path(name) for name in files])

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбрать папку")
        if folder:
            self._start_analysis([Path(folder)])

    def _start_analysis(self, paths: list[Path]) -> None:
        # Новый анализ разрешён только после полной остановки предыдущего потока.
        if self._state not in (AnalysisState.IDLE, AnalysisState.FINISHED):
            return
        if self._thread is not None or not paths:
            return

        self._clear_results()
        self._state = AnalysisState.RUNNING
        self._update_actions()
        self.status_label.setText("Сканирование…")
        self.progress.setRange(0, 0)

        self._worker = AnalysisWorker(
            paths, compute_hashes=self.hash_checkbox.isChecked()
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        # Worker живёт в потоке: deleteLater должен выполниться в нём,
        # пока event loop ещё работает.
        self._worker.done.connect(self._worker.deleteLater)
        # QThread удаляем только внутри _on_thread_finished после wait():
        # сигнал finished приходит ещё до снятия флага running, и прямой
        # finished → deleteLater может дать qFatal «Destroyed while running».
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _cancel_analysis(self) -> None:
        if self._state is not AnalysisState.RUNNING or self._worker is None:
            return
        self._state = AnalysisState.CANCELLING
        self._worker.cancel()
        self._update_actions()
        self.status_label.setText("Останавливаю после текущего файла…")

    # ---------- сигналы worker ----------

    def _on_progress(self, event: ProgressEvent) -> None:
        if event.stage is Stage.SCAN:
            self.progress.setRange(0, 0)
            self.status_label.setText(
                f"Сканирование: {event.processed} файлов — {event.current}"
            )
            return

        total = event.total or 0
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(event.processed)
        self.status_label.setText(
            f"Анализ {event.processed}/{total}: {event.current}"
        )

    def _on_finished(self, report: AnalysisReport) -> None:
        # Показываем отчёт только после остановки потока и очистки ссылок,
        # чтобы кнопки не стали активными раньше времени.
        self._pending_report = report
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_failed(self, message: str) -> None:
        self._pending_error = message
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()

    def _on_thread_finished(self) -> None:
        thread = self._thread
        if thread is not None:
            # finished приходит до полного выхода из потока. Короткий wait()
            # здесь практически мгновенный и убирает гонку с удалением QThread.
            thread.wait()

        report = self._pending_report
        error = self._pending_error
        self._pending_report = None
        self._pending_error = None
        self._worker = None
        self._thread = None
        self._state = AnalysisState.FINISHED

        if report is not None:
            self._display_report(report)
        elif error is not None:
            self._update_actions()
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.status_label.setText("Ошибка анализа")
            QMessageBox.critical(self, "Ошибка анализа", error)

        if thread is not None:
            thread.deleteLater()

        if self._close_requested and self._thread is None:
            self._close_requested = False
            self.close()

    # ---------- отображение результата ----------

    def _display_report(self, report: AnalysisReport) -> None:
        self._report = report
        self._insights = {insight.relative_path: insight for insight in report.insights}

        self.table_model.set_report(report)
        self._set_tree_model(build_tree_model(report))
        self.tree.expandToDepth(0)
        self._fill_errors(report)
        self._update_actions()
        self.preview.clear()

        self.progress.setRange(0, 1)
        self.progress.setValue(1)

        if report.cancelled:
            self.status_label.setText(
                f"Анализ отменён: обработано {len(report.files)} файлов"
            )
        elif not report.files:
            self.status_label.setText("Файлы не найдены")
        else:
            self.status_label.setText(
                f"Готово: {len(report.files)} файлов, "
                f"{human_size(report.total_size)}, ошибок: {len(report.errors)}"
            )

        self.tabs.setCurrentWidget(self.table)

    def _fill_errors(self, report: AnalysisReport) -> None:
        self.errors_list.clear()
        for error in report.errors:
            item = QListWidgetItem(f"{error.path} — {error.message}")
            item.setToolTip(error.message)
            self.errors_list.addItem(item)
        index = self.tabs.indexOf(self.errors_list)
        self.tabs.setTabText(index, f"Ошибки ({len(report.errors)})")

    def _clear_results(self) -> None:
        self._report = None
        self._insights = {}
        self.table_model.clear()
        self._set_tree_model(empty_tree_model())
        self.errors_list.clear()
        self.tabs.setTabText(self.tabs.indexOf(self.errors_list), "Ошибки")
        self.preview.clear()
        self.action_save.setEnabled(False)

    def _set_tree_model(self, model: QStandardItemModel) -> None:
        previous = self.tree.model()
        self.tree.setModel(model)
        if previous is not None:
            previous.deleteLater()

    def _on_selection_changed(self, *_args: object) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.preview.clear()
            return
        entry = self.table_model.entry_at(rows[0].row())
        if entry is None:
            self.preview.clear()
            return
        self.preview.setPlainText(
            self._format_preview(entry, self._insights.get(entry.relative_path))
        )

    def _format_preview(self, entry: FileEntry, insight: FileInsight | None) -> str:
        lines = [
            f"Путь:    {entry.path}",
            f"Размер:  {human_size(entry.size)}",
            f"Формат:  {entry.kind.value}",
        ]
        if entry.sha256:
            lines.append(f"SHA-256: {entry.sha256}")
        if entry.error:
            lines.append(f"Ошибка:  {entry.error}")

        if insight is not None:
            if insight.encoding:
                lines.append(f"Кодировка: {insight.encoding}")
            if insight.encoding_confidence.value == "low":
                candidates = ", ".join(insight.encoding_candidates) or "нет вариантов"
                lines.append(f"Уверенность: низкая ({candidates})")
            for note in insight.notes:
                lines.append(f"Примечание: {note}")
            if insight.archive_entries:
                lines += ["", f"Содержимое архива ({len(insight.archive_entries)}):"]
                for item in insight.archive_entries[:300]:
                    marker = "/" if item.is_dir else ""
                    lines.append(f"  {item.name}{marker}  {human_size(item.size)}")
                if len(insight.archive_entries) > 300:
                    lines.append("  …")
            if insight.preview:
                lines += ["", "Предпросмотр:", insight.preview]

        return "\n".join(lines)

    # ---------- действия ----------

    def _save_current_report(self) -> None:
        if self._report is None:
            return
        try:
            json_path, md_path = save_report(self._report)
        except OSError as exc:
            logger.exception("Не удалось сохранить отчёт")
            QMessageBox.critical(self, "Не удалось сохранить отчёт", str(exc))
            return
        QMessageBox.information(
            self,
            "Отчёт сохранён",
            f"JSON:\n{json_path}\n\nMarkdown:\n{md_path}",
        )

    def _open_reports_folder(self) -> None:
        reports_dir = get_reports_dir()
        reports_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir)))

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "О программе",
            f"<b>{APP_NAME}</b> {__version__}<br>"
            f"Профиль: {self._profile.display_name}<br><br>"
            "Режим только для чтения. Без подключения к автомобилю.",
        )

    def _update_actions(self) -> None:
        busy = self._state in (AnalysisState.RUNNING, AnalysisState.CANCELLING)
        self.action_open_file.setEnabled(not busy)
        self.action_open_folder.setEnabled(not busy)
        self.hash_checkbox.setEnabled(not busy)
        self.action_cancel.setEnabled(self._state is AnalysisState.RUNNING)
        self.action_save.setEnabled(not busy and self._report is not None)

    # ---------- drag & drop ----------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            event.acceptProposedAction()
            self._start_analysis(paths)

    # ---------- закрытие ----------

    def closeEvent(self, event: QCloseEvent) -> None:
        # Операция русификации неделима: закрываемся только после её конца.
        if not self.russification.shutdown():
            self.status_label.setText("Операция ещё выполняется…")
            event.ignore()
            return

        busy = self._state in (AnalysisState.RUNNING, AnalysisState.CANCELLING)
        if not busy or self._thread is None:
            event.accept()
            return

        if not self._close_requested:
            answer = QMessageBox.question(
                self,
                "Анализ выполняется",
                "Прервать анализ и закрыть приложение?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_requested = True
            if self._state is AnalysisState.RUNNING:
                self._cancel_analysis()

        # Пока показывался диалог, анализ мог завершиться — проверяем ссылку снова.
        if self._thread is None:
            self._close_requested = False
            event.accept()
            return

        # Не блокируем GUI ожиданием потока: окно закроется само,
        # когда _on_thread_finished получит сигнал finished.
        if self._thread.isRunning():
            self._thread.quit()
        self.status_label.setText("Закрытие после остановки анализа…")
        event.ignore()
