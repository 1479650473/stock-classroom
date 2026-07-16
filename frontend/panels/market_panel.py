"""Market Panel — Dashboard + Stock Picks"""
import sqlite3, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from .local_worker import LocalWorker


class MarketPanel(QWidget):
    """Market overview: index cards + picks table"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None  # func(msg)
        self.setStyleSheet("background:#111111")
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(6, 4, 6, 4)
        lo.setSpacing(6)
        self.card_row = QHBoxLayout()
        self.card_row.setSpacing(8)
        lo.addLayout(self.card_row)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        lo.addWidget(self.table, 1)

    def load(self):
        if not self.db_path:
            if self.on_status: self.on_status("数据库未配置")
            return
        if self.on_status: self.on_status("加载市场数据...")
        self._worker = LocalWorker(self._work_market, "market")
        self._worker.result.connect(self._on_market)
        self._worker.start()

    def _work_market(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            idx_map = {"000001":"上证指数","399001":"深证成指","399006":"创业板指"}
            rows = conn.execute(
                "SELECT code, close FROM kline_daily "
                "WHERE code IN ('000001','399001','399006') "
                "AND date = (SELECT MAX(date) FROM kline_daily)"
            ).fetchall()
            indices = [{"code":r["code"],"name":idx_map.get(r["code"],r["code"]),
                        "price":r["close"],"change_pct":0,"volume":0} for r in rows]
            stats = {
                "date": conn.execute("SELECT MAX(date) as d FROM kline_daily").fetchone()["d"],
                "total": conn.execute("SELECT COUNT(*) as c FROM stock_list WHERE status='active'").fetchone()["c"],
            }
        finally:
            conn.close()
        return {"code":0, "data":indices, "stats":stats}

    def _on_market(self, tag, data):
        if data.get("code") != 0:
            if self.on_status: self.on_status("市场数据加载失败")
            return
        indices = data.get("data", [])
        while self.card_row.count():
            w = self.card_row.itemAt(0).widget()
            if w:
                w.deleteLater()
                self.card_row.removeWidget(w)
        for d in indices[:6]:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(170, 70)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 4, 10, 4)
            cl.setSpacing(1)
            nm = QLabel(d.get("name", ""))
            nm.setStyleSheet("color:#B4B4B4;font-size:10px;background:transparent")
            cl.addWidget(nm)
            p = QLabel("{:.2f}".format(d.get("price", d.get("close", 0))))
            p.setStyleSheet("color:#EEEEEE;font-size:17px;font-weight:bold;background:transparent")
            cl.addWidget(p)
            chg = d.get("change_pct", 0)
            color = "#E54D2E" if chg >= 0 else "#3fb950"
            c = QLabel("{}{:.2f}%".format("+" if chg >= 0 else "", chg))
            c.setStyleSheet("color:{};font-size:11px;background:transparent".format(color))
            cl.addWidget(c)
            self.card_row.addWidget(card)
        if self.on_status: self.on_status("市场数据已加载")
        self._load_picks()

    def _on_click(self, row, col):
        code = self.table.item(row, 1)
        name = self.table.item(row, 2)
        if code and self.on_open_kline:
            self.on_open_kline(code.text(), name.text() if name else "")

    def _load_picks(self):
        self._worker = LocalWorker(self._work_picks, "picks")
        self._worker.result.connect(self._on_picks)
        self._worker.start()

    def _work_picks(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT code, name FROM stock_list WHERE status='active' ORDER BY code").fetchall()
            cand = [(str(r["code"]), str(r["name"])) for r in rows
                    if str(r["code"])[:2] in ("60","00","30","68") and "ST" not in str(r["name"])]
            results = []
            for code, name in cand:
                try:
                    kd = conn.execute(
                        "SELECT close, volume FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 10",
                        (code,)
                    ).fetchall()
                    if len(kd) < 10: continue
                    close = float(kd[0]["close"])
                    prev = float(kd[1]["close"]) if len(kd) > 1 else close
                    vol = float(kd[0]["volume"])
                    avg_v = sum(float(r["volume"]) for r in kd) / 10
                    if vol <= 0: continue
                    cp = round((close - prev) / prev * 100, 2) if prev else 0
                    score = 50
                    if close > prev: score += 20
                    if vol > avg_v * 1.5: score += 20
                    elif vol > avg_v: score += 10
                    if cp > 3: score += 15
                    elif cp > 0: score += 5
                    results.append({"code":code,"name":name,"price":close,
                                    "change_pct":cp,"volume":int(vol),"score":score})
                except:
                    continue
        finally:
            conn.close()
        results.sort(key=lambda x: x["score"], reverse=True)
        return {"code":0, "data":results[:20]}

    def _on_picks(self, tag, data):
        if data.get("code") != 0: return
        picks = data.get("data", [])
        cols = ["#","代码","名称","价格","涨跌幅","评分"]
        self.table.setRowCount(len(picks))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        for i, s in enumerate(picks):
            items = [
                QTableWidgetItem(str(i+1)),
                QTableWidgetItem(s.get("code","")),
                QTableWidgetItem(s.get("name","")),
                QTableWidgetItem("{:.2f}".format(s.get("price",0))),
                QTableWidgetItem("{}{:.2f}%".format("+" if s.get("change_pct",0)>=0 else "", s.get("change_pct",0))),
                QTableWidgetItem(str(s.get("score",0))),
            ]
            for j, it in enumerate(items):
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j == 4:
                    it.setForeground(QColor("#E54D2E" if s.get("change_pct",0)>=0 else "#3fb950"))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 30)
