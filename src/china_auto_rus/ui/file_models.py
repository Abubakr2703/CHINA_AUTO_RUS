"""Qt-модели для таблицы и дерева файлов."""

from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel

from china_auto_rus.core.models import AnalysisReport, FileEntry
from china_auto_rus.core.report import human_size

TABLE_HEADERS = ("Путь", "Размер", "Формат", "SHA-256")
TREE_HEADERS = ("Файл", "Формат", "Размер")


class FileTableModel(QAbstractTableModel):
    """Плоская таблица файлов отчёта."""

    def __init__(self) -> None:
        super().__init__()
        self._files: list[FileEntry] = []

    def set_report(self, report: AnalysisReport) -> None:
        self.beginResetModel()
        self._files = list(report.files)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._files = []
        self.endResetModel()

    def entry_at(self, row: int) -> FileEntry | None:
        if 0 <= row < len(self._files):
            return self._files[row]
        return None

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex | None = None
    ) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._files)

    def columnCount(
        self, parent: QModelIndex | QPersistentModelIndex | None = None
    ) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(TABLE_HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid():
            return None
        entry = self.entry_at(index.row())
        if entry is None:
            return None

        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return entry.relative_path
            if column == 1:
                return human_size(entry.size)
            if column == 2:
                return entry.kind.value
            if column == 3:
                return f"{entry.sha256[:16]}…" if entry.sha256 else "—"
        elif role == Qt.ItemDataRole.ToolTipRole:
            if column == 0:
                return str(entry.path)
            if column == 3 and entry.sha256:
                return entry.sha256
        elif role == Qt.ItemDataRole.TextAlignmentRole and column == 1:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return TABLE_HEADERS[section]
        return section + 1


def empty_tree_model() -> QStandardItemModel:
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(list(TREE_HEADERS))
    return model


def build_tree_model(report: AnalysisReport) -> QStandardItemModel:
    """Строит дерево каталогов из плоского списка относительных путей."""
    model = empty_tree_model()
    nodes: dict[tuple[str, ...], QStandardItem] = {}

    def ensure_dir(parts: tuple[str, ...]) -> QStandardItem:
        if parts in nodes:
            return nodes[parts]

        item = QStandardItem(parts[-1])
        item.setEditable(False)
        row = [item, QStandardItem(""), QStandardItem("")]
        if len(parts) > 1:
            ensure_dir(parts[:-1]).appendRow(row)
        else:
            model.appendRow(row)
        nodes[parts] = item
        return item

    for entry in report.files:
        normalized = entry.relative_path.replace("\\", "/")
        parts = tuple(
            part for part in PurePosixPath(normalized).parts if part not in ("", ".")
        )
        if not parts:
            continue

        name_item = QStandardItem(parts[-1])
        name_item.setEditable(False)
        name_item.setToolTip(str(entry.path))

        kind_item = QStandardItem(entry.kind.value)
        kind_item.setEditable(False)

        size_item = QStandardItem(human_size(entry.size))
        size_item.setEditable(False)
        size_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        row = [name_item, kind_item, size_item]
        if len(parts) > 1:
            ensure_dir(parts[:-1]).appendRow(row)
        else:
            model.appendRow(row)

    return model
