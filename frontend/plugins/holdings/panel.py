"""Holdings Panel -- 持仓概览面板"""
import sqlite3, traceback
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
    QAbstractItemView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker


C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"
C_RISE = "#EF5350"
C_FALL = "#4CAF50"

DUMMY_HOLDS = [
    {"code": "600519", "name": "贵州茅台", "cost": 1680.0, "shares": 100},
    {"code": "000858", "name": "五粮液",   "cost": 145.0,  "shares": 1000},
    {"code": "300750", "name": "宁德时代",  "cost": 220.0,  "shares": 200},
    {"code": "601318", "name": "中国平安",  "cost": 48.0,   "shares": 500},
    {"code": "000333", "name": "美的集团",  "cost": 65.0,   "shares": 800},
]


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(8)

        self.card_row = QHBoxLayout()
        self.card_row.setSpacing(8)
        lo.addLayout(self.card_row)

        self._hint = QLabel("点击「持仓」标签加载数据")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;")
        lo.addWidget(self._hint)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        lo.addWidget(self.table, 1)

    def load(self):
        if not self.db_path:
            if self.on_status:
                self.on_status("数据库未配置")
            return
        if self.on_status:
            self.on_status("加载持仓...")
        self._hint.hide()
        self._worker = LocalWorker(self._work_load, "holdings")
        self._worker.result.connect(self._on_loaded)
        self._worker.start()

    def _work_load(self):
        conn = sqlite3.connect(self.db_path)
        try:
            holds = []
            for h in DUMMY_HOLDS:
                row = conn.execute(
                    "SELECT close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1",
                    (h["code"],)
                ).fetchone()
                current = float(row[0]) if row else h["cost"]
                pnl = (current - h["cost"]) * h["shares"]
                holds.append({
                    "code": h["code"], "name": h["name"], "cost": h["cost"],
                    "shares": h["shares"], "current": current, "pnl": pnl,
                })
            total_val = sum(h["current"] * h["shares"] for h in holds)
            total_pnl = sum(h["pnl"] for h in holds)
            return {"code": 0, "data": holds, "total_val": total_val, "total_pnl": total_pnl}
        except Exception as e:
            traceback.print_exc()
            return {"code": -1, "error": str(e)}
        finally:
            conn.close()

    def _on_loaded(self, tag, data):
        if data.get("code") != 0:
            if self.on_status:
                self.on_status(f"持仓加载失败: {data.get('error','')}")
            self._hint.setText("数据加载失败")
            self._hint.show()
            return

        holds = data.get("data", [])
        total_val = data.get("total_val", 0)
        total_pnl = data.get("total_pnl", 0)

        while self.card_row.count():
            w = self.card_row.takeAt(0).widget()
            if w: w.deleteLater()

        pnl_color = C_RISE if total_pnl >= 0 else C_FALL
        pnl_sign = "+" if total_pnl >= 0 else ""
        card_specs = [
            ("持仓市值", f"{total_val:,.0f}", C_TEXT),
            ("总盈亏",   f"{pnl_sign}{total_pnl:,.0f}", pnl_color),
            ("持仓数",   f"{len(holds)} 只", C_TEXT),
        ]
        for label, value, color in card_specs:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(172, 70)
            card.setStyleSheet(
                "QFrame#card{background:#161B22;border:1px solid #21262D;border-radius:8px}"
                "QFrame#card:hover{border-color:#30363D}"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 8, 14, 8)
            cl.setSpacing(4)
            l = QLabel(label)
            l.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent;")
            cl.addWidget(l)
            v = QLabel(value)
            v.setStyleSheet(f"color:{color};font-size:20px;font-weight:700;background:transparent;")
            cl.addWidget(v)
            self.card_row.addWidget(card)

        headers = ["代码", "名称", "成本", "现价", "持仓量", "盈亏"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(holds))

        for i, h in enumerate(holds):
            pnl = h["pnl"]
            pnl_str = f"{'+' if pnl >= 0 else ''}{pnl:,.0f}"
            pnl_color_row = C_RISE if pnl >= 0 else C_FALL
            items = [
                QTableWidgetItem(h["code"]),
                QTableWidgetItem(h["name"]),
                QTableWidgetItem(f"{h['cost']:.2f}"),
                QTableWidgetItem(f"{h['current']:.2f}"),
                QTableWidgetItem(f"{h['shares']}"),
                QTableWidgetItem(pnl_str),
            ]
            items[5].setForeground(QColor(pnl_color_row))
            for j, item in enumerate(items):
                if j >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setFont(QFont("Consolas", 11))
                self.table.setItem(i, j, item)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 100)

        if self.on_status:
            pnl_status = f"{pnl_sign}{total_pnl:,.0f}"
            self.on_status(f"持仓: {len(holds)} 只, 市值 {total_val:,.0f}, 盈亏 {pnl_status}")

    def _on_click(self, row, col):
        code_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        if code_item and self.on_open_kline:
            self.on_open_kline(code_item.text(), name_item.text() if name_item else "")
