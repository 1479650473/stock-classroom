# -*- coding: utf-8 -*-
"""DataCenter Companion Panel — right-side table details for datacenter tab."""

import sqlite3
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"

TYPE_CN = {
    "TEXT": "\u6587\u672c",
    "REAL": "\u6d6e\u70b9",
    "INTEGER": "\u6574\u6570",
    "BLOB": "\u4e8c\u8fdb\u5236",
    "": "\u672a\u77e5",
    "NUMERIC": "\u6570\u5b57",
}


class RangeWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, db_path, table_name):
        super().__init__()
        self.db_path = db_path
        self.table_name = table_name

    def run(self):
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                f"SELECT MIN(date), MAX(date) FROM [{self.table_name}]"
            ).fetchone()
            conn.close()
            if rows and rows[0]:
                self.done.emit({"min": rows[0], "max": rows[1]})
            else:
                self.done.emit(None)
        except Exception:
            self.done.emit(None)


class DCCompanion(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG}")
        self._range_worker = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(10)

        title = QLabel("\U0001f4cb \u9009\u4e2d\u8868\u8be6\u60c5")
        title.setStyleSheet(f"color:{C_ACCENT};font-size:13px;font-weight:600;background:transparent")
        lo.addWidget(title)

        self._info_label = QLabel("\u8bf7\u5728\u5de6\u4fa7\u9009\u62e9\u4e00\u4e2a\u6570\u636e\u8868")
        self._info_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;padding:6px 0;background:transparent")
        self._info_label.setWordWrap(True)
        lo.addWidget(self._info_label)

        # ── Column table ──
        self._col_table = QTableWidget()
        self._col_table.setColumnCount(2)
        self._col_table.setHorizontalHeaderLabels(["\u5217\u540d", "\u7c7b\u578b"])
        self._col_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._col_table.verticalHeader().setVisible(False)
        self._col_table.setShowGrid(False)
        self._col_table.horizontalHeader().setStretchLastSection(True)
        self._col_table.setStyleSheet(
            "QTableWidget{background:#0D1117;color:#E6EDF3;gridline-color:#1A1F28}"
            "QHeaderView::section{background:#161B22;color:#8B949E;border:1px solid #21262D;padding:3px;font-size:11px}")
        self._col_table.setColumnWidth(0, 140)
        lo.addWidget(self._col_table)

        # ── Range ──
        range_section = QLabel("\U0001f4c5 \u6570\u636e\u8303\u56f4")
        range_section.setStyleSheet(f"color:{C_ACCENT};font-size:12px;font-weight:600;background:transparent")
        lo.addWidget(range_section)

        self._range_label = QLabel("--")
        self._range_label.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;padding:6px 12px;background:transparent")
        self._range_label.setWordWrap(True)
        lo.addWidget(self._range_label)

        lo.addStretch()

    def show_table(self, t):
        name = t.get("name", "?")
        count = t.get("count", 0)
        cols = t.get("cols", [])
        db_path = t.get("db_path", "")

        self._info_label.setText(
            f"\u8868: {name}\n"
            f"\u603b\u884c\u6570: {count:,}\n"
            f"\u5217\u6570: {len(cols)}"
        )

        self._col_table.setRowCount(len(cols))
        for i, (col_name, col_type) in enumerate(cols):
            bg = QColor(C_PANEL) if i % 2 == 0 else QColor(C_BG)

            nm = QTableWidgetItem(col_name)
            nm.setForeground(QColor(C_TEXT))
            nm.setBackground(bg)
            nm.setFlags(Qt.ItemIsEnabled)
            self._col_table.setItem(i, 0, nm)

            tp = TYPE_CN.get(col_type.upper(), col_type) if col_type else "\u672a\u77e5"
            tp_item = QTableWidgetItem(tp)
            tp_item.setForeground(QColor(C_SUBTEXT))
            tp_item.setBackground(bg)
            tp_item.setFlags(Qt.ItemIsEnabled)
            tp_item.setTextAlignment(Qt.AlignCenter)
            self._col_table.setItem(i, 1, tp_item)

        self._range_label.setText("\u67e5\u8be2\u4e2d...")
        if self._range_worker:
            self._range_worker.terminate()
        self._range_worker = RangeWorker(db_path, name)
        self._range_worker.done.connect(self._on_range)
        self._range_worker.start()

    def _on_range(self, data):
        if data:
            self._range_label.setText(
                f"  {data['min']}  ~  {data['max']}"
            )
        else:
            self._range_label.setText("  \u65e0\u65e5\u671f\u5217\u6216\u65e0\u6570\u636e")
