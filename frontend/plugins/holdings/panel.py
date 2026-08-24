# -*- coding: utf-8 -*-
"""Holdings Panel — real simulated-account portfolio overview.

Reads from the TradeEngine (sim_trade.db), the same source of truth as the
trade panel, so what you see here always matches your simulated book.
"""

import sys, os

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QFrame, QAbstractItemView, QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from trade_engine.engine import TradeEngine
from frontend.platform.local_worker import LocalWorker
from frontend.platform.theme import (
    dp, dps, fs,
    C_BG, C_PANEL, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_ACCENT, C_UP, C_DOWN,
    qss_combo, qss_table, style_h1, style_label, style_caption,
)


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self._engine = TradeEngine()
        self._worker = None
        self.setStyleSheet(f"background:{C_BG}")
        self._build_ui()

    # ── UI ──

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        lo.setSpacing(dp(8))

        hdr = QHBoxLayout()
        hdr.setSpacing(dp(8))
        title = QLabel("模拟持仓")
        title.setStyleSheet(style_h1())
        hdr.addWidget(title)
        hdr.addStretch()

        acc_lbl = QLabel("账户")
        acc_lbl.setStyleSheet(style_label())
        hdr.addWidget(acc_lbl)
        self._acc_combo = QComboBox()
        self._acc_combo.setMinimumWidth(dp(130))
        self._acc_combo.setFixedHeight(dp(28))
        self._acc_combo.setStyleSheet(qss_combo())
        self._acc_combo.currentIndexChanged.connect(lambda _: self.load())
        hdr.addWidget(self._acc_combo)
        lo.addLayout(hdr)

        self.card_row = QHBoxLayout()
        self.card_row.setSpacing(dp(8))
        lo.addLayout(self.card_row)

        self._hint = QLabel("暂无持仓 — 到「交易」面板下第一单吧")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setStyleSheet(style_caption())
        lo.addWidget(self._hint)

        self.table = QTableWidget()
        self.table.setStyleSheet(qss_table())
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellClicked.connect(self._on_click)
        lo.addWidget(self.table, 1)

        self._reload_accounts()

    def _reload_accounts(self):
        self._acc_combo.blockSignals(True)
        self._acc_combo.clear()
        accs = self._engine.list_accounts()
        if not accs:
            self._engine.create_account("主账户", 100000)
            accs = self._engine.list_accounts()
        for acc in accs:
            self._acc_combo.addItem("[%d] %s" % (acc['id'], acc['name']), acc['id'])
        self._acc_combo.blockSignals(False)

    # ── Data ──

    def load(self):
        aid = self._acc_combo.currentData()
        if not aid:
            return
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        if self.on_status:
            self.on_status("加载持仓...")
        self._worker = LocalWorker(self._work_load, "holdings", args=[aid])
        self._worker.result.connect(self._on_loaded)
        self._worker.start()

    def _work_load(self, account_id):
        """Read positions, then refresh prices off the UI thread."""
        try:
            from data_manager import fetch_realtime_prices

            positions = self._engine.get_positions(account_id)
            codes = [p['code'] for p in positions]
            if codes:
                try:
                    quotes = fetch_realtime_prices(codes) or []
                    for q in quotes:
                        self._engine.update_position_price(account_id, q['code'], q['price'])
                except Exception:
                    pass  # fall back to last known prices
                positions = self._engine.get_positions(account_id)
            summary = self._engine.get_summary(account_id)
            return {"code": 0, "positions": positions, "summary": summary}
        except Exception as e:
            return {"code": -1, "error": str(e)}

    def _on_loaded(self, tag, data):
        if data.get("code") != 0:
            if self.on_status:
                self.on_status("持仓加载失败: %s" % data.get('error', ''))
            return

        positions = data.get("positions", [])
        summary = data.get("summary") or {}

        while self.card_row.count():
            w = self.card_row.takeAt(0).widget()
            if w:
                w.deleteLater()

        total_pnl = summary.get("total_profit", 0)
        pnl_color = C_UP if total_pnl > 0 else (C_DOWN if total_pnl < 0 else C_TEXT)
        card_specs = [
            ("总资产", "{:,.0f}".format(summary.get("total_assets", 0)), C_TEXT),
            ("持仓市值", "{:,.0f}".format(summary.get("market_value", 0)), C_TEXT),
            ("累计盈亏", "{:+,.0f}".format(total_pnl), pnl_color),
            ("持仓数", "%d 只" % len(positions), C_ACCENT),
        ]
        for label, value, color in card_specs:
            self.card_row.addWidget(self._make_card(label, value, color))

        self._hint.setVisible(len(positions) == 0)

        headers = ["代码", "名称", "持仓量", "成本", "现价", "浮动盈亏", "市值"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(positions))

        for i, p in enumerate(positions):
            fp = p.get("float_pnl", 0)
            fp_color = C_UP if fp > 0 else (C_DOWN if fp < 0 else C_TEXT)
            cells = [
                (p["code"], C_TEXT, Qt.AlignLeft),
                (p["name"], C_TEXT, Qt.AlignLeft),
                (str(p["qty"]), C_TEXT, Qt.AlignRight),
                ("%.2f" % p["cost_price"], C_SUBTEXT, Qt.AlignRight),
                ("%.2f" % p["current_price"], C_TEXT, Qt.AlignRight),
                ("{:+,.2f}".format(fp), fp_color, Qt.AlignRight),
                ("{:,.0f}".format(p.get("market_value", 0)), C_TEXT, Qt.AlignRight),
            ]
            for j, (text, color, align) in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setForeground(QColor(color))
                it.setTextAlignment(align | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, dp(70))
        self.table.setColumnWidth(1, dp(90))

        if self.on_status:
            self.on_status("持仓: %d 只, 市值 %s, 累计盈亏 %+,.0f"
                           % (len(positions),
                              "{:,.0f}".format(summary.get("market_value", 0)),
                              total_pnl))

    def _make_card(self, label, value, color):
        card = QFrame()
        card.setObjectName("card")
        card.setFixedHeight(dp(64))
        card.setStyleSheet(
            f"QFrame#card{{background:{C_PANEL};border:1px solid {C_BORDER_SOFT};"
            f"border-radius:{dps(8)};}}"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(dp(12), dp(8), dp(12), dp(8))
        cl.setSpacing(dp(2))
        l = QLabel(label)
        l.setStyleSheet(style_caption())
        cl.addWidget(l)
        v = QLabel(value)
        v.setStyleSheet(
            f"color:{color};font-size:{fs(14)};font-weight:700;background:transparent;"
            f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
        cl.addWidget(v)
        return card

    def _on_click(self, row, col):
        code_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        if code_item and self.on_open_kline:
            self.on_open_kline(code_item.text(), name_item.text() if name_item else "")
