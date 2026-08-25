# -*- coding: utf-8 -*-
"""DataCenter Companion Panel — right-side table details + data panorama (premium)."""

import sqlite3
from datetime import datetime
from frontend.platform.theme import (
    dp, dps, fs, C_TEXT, C_SUBTEXT, C_FAINT, C_PANEL, qss_table,
)
from frontend.platform.premium import (
    PAL, card_qss, value_ss, label_ss, SectionTitle,
)
from .panorama import DataPanorama
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

TYPE_CN = {
    "TEXT": "文本", "REAL": "浮点", "INTEGER": "整数", "BLOB": "二进制",
    "": "未知", "NUMERIC": "数字",
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
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._range_worker = None
        self._panorama = None
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea{{background:{PAL['bg']};border:none;}}")
        outer.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet(f"background:{PAL['bg']}")
        lo = QVBoxLayout(container)
        lo.setContentsMargins(dp(12), dp(12), dp(12), dp(12))
        lo.setSpacing(dp(10))

        # ── Data panorama (database coverage across time) ──
        lo.addWidget(SectionTitle("数据全景"))
        pano_card = QFrame()
        pano_card.setObjectName("pano_card")
        pano_card.setStyleSheet(card_qss("pano_card"))
        pcl = QVBoxLayout(pano_card)
        pcl.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._panorama = DataPanorama()
        self._panorama.setMinimumHeight(220)
        pcl.addWidget(self._panorama)
        lo.addWidget(pano_card)

        # ── Selected table details ──
        lo.addWidget(SectionTitle("选中表详情"))
        self._info_label = QLabel("请在左侧选择一个数据表")
        self._info_label.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:{fs(13)};padding:{dps(6)} 0;background:transparent")
        self._info_label.setWordWrap(True)
        lo.addWidget(self._info_label)

        self._col_table = QTableWidget()
        self._col_table.setColumnCount(2)
        self._col_table.setHorizontalHeaderLabels(["列名", "类型"])
        self._col_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._col_table.verticalHeader().setVisible(False)
        self._col_table.setShowGrid(False)
        self._col_table.horizontalHeader().setStretchLastSection(True)
        self._col_table.setStyleSheet(qss_table())
        self._col_table.setColumnWidth(0, dp(150))
        self._col_table.setColumnWidth(1, dp(64))
        self._col_table.verticalHeader().setDefaultSectionSize(dp(26))
        self._col_table.horizontalHeader().setFixedHeight(dp(28))
        lo.addWidget(self._col_table)

        # ── Range ──
        lo.addWidget(SectionTitle("数据范围"))
        self._range_label = QLabel("--")
        self._range_label.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:{fs(13)};padding:{dps(6)} {dps(12)};background:transparent")
        self._range_label.setWordWrap(True)
        lo.addWidget(self._range_label)

        lo.addStretch()
        scroll.setWidget(container)

    def set_databases(self, kline_db, cache_db):
        """Point the data-panorama at the kline + cache databases."""
        if self._panorama is not None:
            self._panorama.load(kline_db, cache_db)

    def show_table(self, t):
        name = t.get("name", "?")
        count = t.get("count", 0)
        cols = t.get("cols", [])
        db_path = t.get("db_path", "")

        self._info_label.setText(
            f"表: {name}\n"
            f"总行数: {count:,}\n"
            f"列数: {len(cols)}")

        self._col_table.setRowCount(len(cols))
        for i, (col_name, col_type) in enumerate(cols):
            bg = QColor(C_PANEL) if i % 2 == 0 else QColor(PAL["bg"])
            nm = QTableWidgetItem(col_name)
            nm.setForeground(QColor(C_TEXT))
            nm.setBackground(bg)
            nm.setFlags(Qt.ItemIsEnabled)
            self._col_table.setItem(i, 0, nm)
            tp = TYPE_CN.get(col_type.upper(), col_type) if col_type else "未知"
            tp_item = QTableWidgetItem(tp)
            tp_item.setForeground(QColor(C_SUBTEXT))
            tp_item.setBackground(bg)
            tp_item.setFlags(Qt.ItemIsEnabled)
            tp_item.setTextAlignment(Qt.AlignCenter)
            self._col_table.setItem(i, 1, tp_item)

        self._range_label.setText("查询中...")
        if self._range_worker:
            self._range_worker.terminate()
        self._range_worker = RangeWorker(db_path, name)
        self._range_worker.done.connect(self._on_range)
        self._range_worker.start()

    def _on_range(self, data):
        if data:
            self._range_label.setText(f"  {data['min']}  ~  {data['max']}")
        else:
            self._range_label.setText("  无日期列或无数据")
