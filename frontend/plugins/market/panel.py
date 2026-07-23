"""Market Panel -- 大盘指数 + 板块表现"""
import sqlite3, traceback
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QAbstractItemView,
    QPushButton)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from frontend.platform.local_worker import LocalWorker


INDEX_MAP = {
    "000001": "上证指数", "399001": "深证成指",
    "399006": "创业板指", "000688": "科创50",
    "000300": "沪深300",
}

C_BG = "#0D1117"
C_PANEL = "#161B22"
C_BORDER = "#21262D"
C_TEXT = "#E6EDF3"
C_SUBTEXT = "#8B949E"
C_ACCENT = "#D4A574"
C_RISE = "#EF5350"
C_FALL = "#4CAF50"
C_HOVER = "#1C2128"


class MarketPanel(QWidget):
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

        self.bar_widgets = {}
        bar = QFrame()
        bar.setObjectName("card")
        bar.setStyleSheet(f"QFrame#card{{background:{C_PANEL};border:1px solid {C_BORDER};border-radius:8px;padding:4px}}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 6, 16, 6)
        for key, text in [("date", "日期"), ("up", "上涨"), ("dn", "下跌"),
                          ("cnt", "总数"), ("vol", "成交额")]:
            w = QLabel("--")
            w.setStyleSheet(f"color:{C_SUBTEXT};font-size:12px;font-weight:500;background:transparent")
            w._key = key
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color:#484F58;font-size:11px;background:transparent")
            bl.addWidget(lbl)
            bl.addWidget(w)
            bl.addSpacing(16)
            self.bar_widgets[key] = w
        bl.addStretch()
        lo.addWidget(bar)

        self._sector_type = "industry"
        self._sector_tabs = QHBoxLayout()
        self._sector_tabs.setSpacing(4)
        self._btn_ind = QPushButton("行业板块")
        self._btn_ind.setCheckable(True)
        self._btn_ind.setChecked(True)
        self._btn_ind.clicked.connect(lambda: (setattr(self, "_sector_type", "industry"),
            self._btn_ind.setChecked(True), self._btn_cpt.setChecked(False), self._load_sectors()))
        self._btn_cpt = QPushButton("概念板块")
        self._btn_cpt.setCheckable(True)
        self._btn_cpt.clicked.connect(lambda: (setattr(self, "_sector_type", "concept"),
            self._btn_cpt.setChecked(True), self._btn_ind.setChecked(False), self._load_sectors()))
        for btn in [self._btn_ind, self._btn_cpt]:
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:#161B22;color:#8B949E;border:1px solid #21262D;"
                "border-radius:6px;padding:3px 14px;font-size:12px;}"
                "QPushButton:checked{background:rgba(212,165,116,0.10);color:#D4A574;border-color:#D4A574}")
            self._sector_tabs.addWidget(btn)
        self._sector_tabs.addStretch()
        lo.addLayout(self._sector_tabs)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        lo.addWidget(self.table, 1)

    def _load_sectors(self):
        self._sector_worker = LocalWorker(self._work_sectors, "sectors", args=[self._sector_type])
        self._sector_worker.result.connect(self._on_sectors)
        self._sector_worker.start()

    def _work_sectors(self, stype):
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                'SELECT name, rank, latest_price, change_pct, up_count, dn_count, leader, leader_chg '
                'FROM sector_board WHERE type = ? ORDER BY rank LIMIT 30', (stype,)
            ).fetchall()
            return {"code": 0, "sectors": [
                {"name": r[0], "rank": r[1], "price": r[2], "change_pct": r[3],
                 "up": r[4], "dn": r[5], "leader": r[6], "leader_chg": r[7]} for r in rows
            ]}
        finally:
            conn.close()

    def _on_sectors(self, tag, data):
        if data.get("code") != 0: return
        sectors = data.get("sectors", [])
        self._build_sector_table(sectors)
        label = "行业板块" if self._sector_type == "industry" else "概念板块"
        if self.on_status: self.on_status(f"{label}已加载 - {len(sectors)}条")

    def load(self):
        if not self.db_path:
            return
        if self.on_status:
            self.on_status("加载市场数据...")
        self._worker = LocalWorker(self._work_market, "market")
        self._worker.result.connect(self._on_market)
        self._worker.start()

    def _work_market(self):
        conn = sqlite3.connect(self.db_path)
        try:
            dates = conn.execute(
                "SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 2"
            ).fetchall()
            if len(dates) < 2:
                return {"code": -1, "error": "数据不足"}
            d_latest, d_prev = dates[0][0], dates[1][0]

            idx_codes = list(INDEX_MAP.keys())

            idx_rows = conn.execute(
                "SELECT code, close FROM kline_daily "
                "WHERE code IN (%s) AND date = ?" % ",".join("?" for _ in idx_codes),
                idx_codes + [d_latest]
            ).fetchall()
            idx_prev = conn.execute(
                "SELECT code, close FROM kline_daily "
                "WHERE code IN (%s) AND date = ?" % ",".join("?" for _ in idx_codes),
                idx_codes + [d_prev]
            ).fetchall()
            idx_map = dict(idx_rows)
            idx_prev_map = dict(idx_prev)

            indices = []
            for code in idx_codes:
                cur = idx_map.get(code)
                prv = idx_prev_map.get(code)
                cp = (cur - prv) / prv * 100 if cur and prv else 0
                indices.append({
                    "code": code, "name": INDEX_MAP[code],
                    "price": cur or 0, "change_pct": round(cp, 2),
                })

            today_rows = conn.execute(
                "SELECT code, close, volume FROM kline_daily WHERE date = ?", (d_latest,)
            ).fetchall()
            prev_rows = conn.execute(
                "SELECT code, close FROM kline_daily WHERE date = ?", (d_prev,)
            ).fetchall()
            prev_map = dict(prev_rows)
            total_up = total_dn = total_flat = 0
            total_vol = 0.0
            for code, close, volume in today_rows:
                total_vol += float(volume or 0)
                prv = prev_map.get(code)
                cp = (float(close) - float(prv)) / float(prv) * 100 if prv and prv > 0 else 0
                if cp > 0: total_up += 1
                elif cp < 0: total_dn += 1
                else: total_flat += 1
            return {"code": 0, "indices": indices, "stats": {
                "date": d_latest,
                "up": total_up, "dn": total_dn, "flat": total_flat,
                "count": total_up + total_dn + total_flat, "volume": total_vol,
            }}
        finally:
            conn.close()

    def _on_market(self, tag, data):
        if data.get("code") != 0:
            if self.on_status:
                self.on_status("市场数据加载失败")
            return

        indices = data.get("indices", [])
        stats = data.get("stats", {})

        while self.card_row.count():
            w = self.card_row.takeAt(0).widget()
            if w:
                w.deleteLater()

        for d in indices:
            card = QFrame()
            card.setObjectName("card")
            card.setFixedSize(172, 72)
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(
                "QFrame#card{background:#161B22;border:1px solid #21262D;border-radius:8px}"
                "QFrame#card:hover{border-color:#30363D}"
            )
            card._code = d.get("code", "")
            card._name = d.get("name", "")
            orig_mpe = card.mousePressEvent
            def _make_click(c, n):
                def handler(e, cc=c, nn=n):
                    if orig_mpe:
                        orig_mpe(e)
                    if e.button() == Qt.LeftButton and self.on_open_kline:
                        self.on_open_kline(cc, nn)
                return handler
            card.mousePressEvent = _make_click(card._code, card._name)

            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 6, 12, 6)
            cl.setSpacing(2)

            nm = QLabel(d.get("name", ""))
            nm.setStyleSheet(f"color:{C_SUBTEXT};font-size:11px;background:transparent")
            cl.addWidget(nm)

            p = QLabel("{:.2f}".format(d.get("price", 0)))
            p.setStyleSheet(f"color:{C_TEXT};font-size:18px;font-weight:700;background:transparent")
            cl.addWidget(p)

            chg = d.get("change_pct", 0)
            color = C_RISE if chg >= 0 else C_FALL
            c = QLabel("{}{:.2f}%".format("+" if chg >= 0 else "", chg))
            c.setStyleSheet(f"color:{color};font-size:12px;font-weight:600;background:transparent")
            cl.addWidget(c)

            self.card_row.addWidget(card)

        fmt_vol = lambda v: "{:.0f}亿".format(v / 1e8) if v else "--"
        self.bar_widgets["date"].setText(stats.get("date", "--"))
        self.bar_widgets["up"].setText(str(stats.get("up", 0)))
        self.bar_widgets["up"].setStyleSheet(f"color:{C_RISE};font-size:11px;font-weight:600;background:transparent")
        self.bar_widgets["dn"].setText(str(stats.get("dn", 0)))
        self.bar_widgets["dn"].setStyleSheet(f"color:{C_FALL};font-size:11px;font-weight:600;background:transparent")
        self.bar_widgets["cnt"].setText(str(stats.get("count", 0)))
        self.bar_widgets["cnt"].setStyleSheet(f"color:{C_TEXT};font-size:11px;font-weight:500;background:transparent")
        self.bar_widgets["vol"].setText(fmt_vol(stats.get("volume", 0)))

        if self.on_status:
            self.on_status(f"市场数据已加载 - {stats.get('date', '')}")
        self._load_sectors()

    def _build_sector_table(self, sectors):
        cols = ["板块", "排名", "价格", "涨跌幅", "领涨股", "领涨涨幅"]
        self.table.setRowCount(len(sectors))
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)

        for i, b in enumerate(sectors):
            bg = QColor("#161B22") if i % 2 else QColor("#0D1117")
            change = b.get("change_pct", 0)
            chg_color = C_RISE if change >= 0 else C_FALL
            ldr_chg = b.get("leader_chg", 0)
            ldr_color = C_RISE if ldr_chg >= 0 else C_FALL

            items = [
                (b.get("name", ""), C_TEXT),
                (str(b.get("rank", "")), C_SUBTEXT),
                ("{:.2f}".format(b.get("price", 0) or 0), C_TEXT),
                ("{}{:.2f}%".format("+" if change >= 0 else "", change), chg_color),
                (b.get("leader", "--"), C_SUBTEXT),
                ("{}{:.2f}%".format("+" if ldr_chg >= 0 else "", ldr_chg), ldr_color),
            ]
            for j, (text, color) in enumerate(items):
                it = QTableWidgetItem(text)
                it.setForeground(QColor(color))
                it.setBackground(bg)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if j > 0 else Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 100)
        for j in range(1, len(cols)):
            if self.table.columnWidth(j) < 55:
                self.table.setColumnWidth(j, 55)

    def _on_click(self, row, col):
        pass
