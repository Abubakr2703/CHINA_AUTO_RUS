"""Тесты Qt-моделей таблицы и дерева."""

from __future__ import annotations

from pathlib import Path

from china_auto_rus.core.analyzer import analyze_paths
from china_auto_rus.ui.file_models import FileTableModel, build_tree_model


def test_file_table_model(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    report = analyze_paths([tmp_path])

    model = FileTableModel()
    model.set_report(report)

    assert model.rowCount() == 1
    assert model.columnCount() == 4
    assert model.data(model.index(0, 0)) == "a.txt"
    assert model.data(model.index(0, 1)) == "5 Б"
    assert model.data(model.index(0, 2)) == "text"
    assert str(model.data(model.index(0, 3))).endswith("…")


def test_file_table_model_clear(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    report = analyze_paths([tmp_path])
    model = FileTableModel()
    model.set_report(report)

    model.clear()

    assert model.rowCount() == 0
    assert model.entry_at(0) is None


def test_tree_model_nests_directories(qapp: object, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    report = analyze_paths([tmp_path])

    model = build_tree_model(report)

    assert model.rowCount() == 2
    names = {model.item(row).text() for row in range(model.rowCount())}
    assert names == {"a.txt", "sub"}

    sub_item = next(
        model.item(row)
        for row in range(model.rowCount())
        if model.item(row).text() == "sub"
    )
    assert sub_item.rowCount() == 1
    assert sub_item.child(0).text() == "b.txt"
