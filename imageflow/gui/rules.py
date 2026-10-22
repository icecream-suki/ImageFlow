from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QHeaderView,
                               QPushButton, QComboBox, QCheckBox, QAbstractItemView)

from ..routing import clean_rules


class RulesEditor(QWidget):
    changed = Signal()

    def __init__(self, rules):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["启用", "输入", "类型", "输出"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setFixedHeight(144)
        row = QHBoxLayout()
        for label, callback in [("添加", self.add_rule), ("删除", self.remove_rule),
                                ("↑", lambda: self.move_rule(-1)), ("↓", lambda: self.move_rule(1))]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(self.table)
        self.set_rules(rules)

    def _append(self, rule):
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QCheckBox()
        enabled.setChecked(rule["enabled"])
        enabled.toggled.connect(self.changed)
        self.table.setCellWidget(row, 0, enabled)
        groups = [[("任意", "any")] + [(x.upper(), x) for x in ["png", "jpeg", "webp", "bmp", "tiff", "gif", "apng", "webm"]],
                  [("任意", "any"), ("静态", "static"), ("动画", "animated")],
                  [(x.upper(), x) for x in ["png", "jpeg", "webp", "bmp", "tiff", "gif", "apng"]]]
        for column, key, choices in zip((1, 2, 3), ("source", "kind", "target"), groups):
            control = QComboBox()
            for label, data in choices:
                control.addItem(label, data)
            control.setCurrentIndex(control.findData(rule[key]))
            control.currentIndexChanged.connect(self.changed)
            self.table.setCellWidget(row, column, control)

    def rules(self):
        return [{"enabled": self.table.cellWidget(row, 0).isChecked(),
                 **{key: self.table.cellWidget(row, column).currentData()
                    for column, key in [(1, "source"), (2, "kind"), (3, "target")]}}
                for row in range(self.table.rowCount())]

    def set_rules(self, rules):
        self.table.setRowCount(0)
        for rule in clean_rules(rules):
            self._append(rule)

    def add_rule(self):
        if self.table.rowCount() >= 100:
            return
        self._append({"enabled": True, "source": "webp", "kind": "animated", "target": "gif"})
        self.table.setCurrentCell(self.table.rowCount()-1, 1)
        self.changed.emit()

    def remove_rule(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.changed.emit()

    def move_rule(self, offset):
        row = self.table.currentRow()
        if 0 <= row + offset < self.table.rowCount() and row >= 0:
            rules = self.rules()
            rules[row], rules[row+offset] = rules[row+offset], rules[row]
            self.set_rules(rules)
            self.table.setCurrentCell(row+offset, 1)
            self.changed.emit()
