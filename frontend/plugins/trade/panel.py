# -*- coding: utf-8 -*-
"""Trade panel — order entry, positions, trade history."""

import sys, os, sqlite3

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from trade_engine.engine import TradeEngine
from frontend.platform.theme import (
    dp, dps, fs, tr, style_title,
    C_BG, C_PANEL, C_RAISED, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_ACCENT_HOVER, C_ACCENT_DIM, C_ON_ACCENT, C_UP, C_DOWN,
    C_GOLD,
    qss_btn, qss_btn_accent, qss_combo, qss_input, qss_list, qss_spinbox,
    qss_table, style_h1, style_h2, style_label, style_caption,
)
from frontend.platform.local_worker import LocalWorker
from frontend.platform.premium import PAL as _PAL, card_qss as _card_qss, label_ss as _label_ss, value_ss as _value_ss, hero_ss as _hero_ss

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QListWidget, QListWidgetItem,
    QAbstractItemView, QSizePolicy, QTabWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor


def _seg_style(active_color: str) -> str:
    """Segmented-toggle style: tinted text at rest, solid fill when checked."""
    return (
        f"QPushButton{{background:{C_PANEL};color:{active_color};border:1px solid {C_BORDER};"
        f"font-size:{fs(12)};font-weight:700;padding:{dps(4)} 0;}}"
        f"QPushButton:hover{{border-color:{active_color};}}"
        f"QPushButton:checked{{background:{active_color};color:#FFFFFF;border-color:{active_color};}}"
    )


# ──────────────────────────────────────────────────────────────
#  AccountBar
# ──────────────────────────────────────────────────────────────

class _AccountBar(QWidget):
    account_changed = pyqtSignal(int)

    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(dp(6))

        lbl = QLabel("账户")
        lbl.setStyleSheet(style_label())
        lo.addWidget(lbl)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(dp(130))
        self._combo.setFixedHeight(dp(28))
        self._combo.setStyleSheet(qss_combo())
        self._combo.currentIndexChanged.connect(self._emit)
        lo.addWidget(self._combo)

        btn_new = QPushButton("+ 新建")
        btn_new.setFixedHeight(dp(28))
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.setStyleSheet(qss_btn())
        btn_new.setToolTip("新建模拟账户（初始资金 10 万）")
        btn_new.clicked.connect(self._create)
        lo.addWidget(btn_new)

        btn_reset = QPushButton("重置")
        btn_reset.setFixedHeight(dp(28))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(qss_btn())
        btn_reset.setToolTip("清空当前账户的持仓与订单，恢复初始资金")
        btn_reset.clicked.connect(self._reset)
        lo.addWidget(btn_reset)

        lo.addStretch()
        self._load()

    def _load(self):
        self._combo.blockSignals(True)
        self._combo.clear()
        for acc in self._engine.list_accounts():
            self._combo.addItem("[%d] %s" % (acc['id'], acc['name']), acc['id'])
        self._combo.blockSignals(False)

    def _emit(self):
        aid = self._combo.currentData()
        if aid:
            self.account_changed.emit(aid)

    def _create(self):
        aid = self._engine.create_account("主账户", 100000)
        self._load()
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == aid:
                self._combo.setCurrentIndex(i)
                break

    def _reset(self):
        aid = self._combo.currentData()
        if aid:
            self._engine.reset_account(aid)
            self.account_changed.emit(aid)

    def current_id(self):
        return self._combo.currentData()


# ──────────────────────────────────────────────────────────────
#  SummaryCards
# ──────────────────────────────────────────────────────────────

class _SummaryCards(QWidget):
    def __init__(self):
        super().__init__()
        self._labels = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(dp(6))

        items = [
            ("总资产", "total_assets", 0, 0),
            ("可用资金", "balance", 0, 1),
            ("持仓市值", "market_value", 0, 2),
            ("冻结资金", "frozen", 1, 0),
            ("浮动盈亏", "float_pnl", 1, 1),
            ("累计盈亏", "total_profit", 1, 2),
        ]
        for label, key, row, col in items:
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(_card_qss("card"))
            cl = QVBoxLayout(card)
            cl.setContentsMargins(dp(11), dp(8), dp(11), dp(8))
            cl.setSpacing(dp(3))

            lb = QLabel(label)
            lb.setStyleSheet(_label_ss(size=9, gold=True))
            cl.addWidget(lb)

            val = QLabel("--")
            val.setStyleSheet(_hero_ss(size=15))
            cl.addWidget(val)
            self._labels[key] = val
            grid.addWidget(card, row, col)

    def _set_num(self, key, text, color=None):
        lb = self._labels[key]
        lb.setText(text)
        if color:
            lb.setStyleSheet(_hero_ss(size=15) + f"color:{color};")
        else:
            lb.setStyleSheet(_hero_ss(size=15))

    def update_summary(self, summary):
        if summary is None:
            return
        self._set_num("total_assets", "{:,.2f}".format(summary.get("total_assets", 0)))
        self._set_num("balance", "{:,.2f}".format(summary.get("balance", 0)))
        self._set_num("frozen", "{:,.2f}".format(summary.get("frozen", 0)))
        self._set_num("market_value", "{:,.2f}".format(summary.get("market_value", 0)))

        fp = summary.get("float_pnl", 0)
        self._set_num("float_pnl", "{:+,.2f}".format(fp),
                      C_UP if fp > 0 else (C_DOWN if fp < 0 else C_TEXT))

        tp = summary.get("total_profit", 0)
        pct = summary.get("total_profit_pct", 0)
        self._set_num("total_profit", "{:+,.2f} ({:+.2f}%)".format(tp, pct),
                      C_UP if tp > 0 else (C_DOWN if tp < 0 else C_TEXT))


# ──────────────────────────────────────────────────────────────
#  StockSearch
# ──────────────────────────────────────────────────────────────

class _StockSearch(QWidget):
    stock_selected = pyqtSignal(str, str)  # code, name

    def __init__(self):
        super().__init__()
        self._kline_db = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_search)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入代码或名称，如 600519 / 茅台")
        self._input.setFixedHeight(dp(30))
        self._input.setStyleSheet(qss_input())
        self._input.textChanged.connect(self._on_text)
        lo.addWidget(self._input)

        self._list = QListWidget()
        self._list.setMaximumHeight(dp(150))
        self._list.setStyleSheet(qss_list())
        self._list.itemClicked.connect(self._on_select)
        self._list.hide()
        lo.addWidget(self._list)

    def set_db(self, path):
        self._kline_db = path

    def _on_text(self, text):
        if len(text.strip()) < 1:
            self._list.hide()
            return
        self._timer.start(250)

    def _do_search(self):
        text = self._input.text().strip()
        if len(text) < 1 or not self._kline_db:
            self._list.hide()
            return
        try:
            conn = sqlite3.connect(self._kline_db)
            rows = conn.execute(
                "SELECT code, name FROM stock_list WHERE code LIKE ? OR name LIKE ? "
                "ORDER BY CASE WHEN code=? THEN 0 WHEN code LIKE ? THEN 1 ELSE 2 END "
                "LIMIT 20",
                ("%%%s%%" % text, "%%%s%%" % text, text, text + "%"),
            ).fetchall()
            conn.close()

            self._list.clear()
            for code, name in rows:
                item = QListWidgetItem("%s  %s" % (code, name))
                item.setData(Qt.UserRole, (code, name))
                self._list.addItem(item)

            self._list.setVisible(self._list.count() > 0)
        except Exception:
            self._list.hide()

    def _on_select(self, item):
        code, name = item.data(Qt.UserRole)
        self._input.setText(code)
        self._list.hide()
        self.stock_selected.emit(code, name)

    def set_code(self, code):
        self._input.setText(code)


# ──────────────────────────────────────────────────────────────
#  OrderPanel
# ──────────────────────────────────────────────────────────────

class _OrderPanel(QWidget):
    order_placed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._side = 'buy'
        self._order_type = 'market'
        self._code = ''
        self._name = ''
        self._current_price = 0.0

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(dp(6))

        # ── Side toggle ──
        sr = QHBoxLayout()
        sr.setSpacing(0)
        self._buy_btn = QPushButton("买入")
        self._buy_btn.setCheckable(True)
        self._buy_btn.setChecked(True)
        self._buy_btn.setFixedHeight(dp(32))
        self._buy_btn.setCursor(Qt.PointingHandCursor)
        self._buy_btn.setStyleSheet(
            _seg_style(C_UP).replace("border:1px solid %s;" % C_BORDER,
                                     "border:1px solid %s;border-radius:%s 0 0 %s;"
                                     % (C_BORDER, dps(6), dps(6)))
            + f"QPushButton{{border-radius:{dps(6)} 0 0 {dps(6)};}}"
        )
        self._buy_btn.clicked.connect(lambda: self._set_side('buy'))
        sr.addWidget(self._buy_btn, 1)

        self._sell_btn = QPushButton("卖出")
        self._sell_btn.setCheckable(True)
        self._sell_btn.setFixedHeight(dp(32))
        self._sell_btn.setCursor(Qt.PointingHandCursor)
        self._sell_btn.setStyleSheet(
            _seg_style(C_DOWN)
            + f"QPushButton{{border-radius:0 {dps(6)} {dps(6)} 0;border-left:none;}}"
        )
        self._sell_btn.clicked.connect(lambda: self._set_side('sell'))
        sr.addWidget(self._sell_btn, 1)
        lo.addLayout(sr)

        # ── Current stock / price ──
        self._price_label = QLabel("未选择股票")
        self._price_label.setStyleSheet(
            f"color:{C_SUBTEXT};font-size:{fs(12)};font-weight:600;background:transparent;")
        lo.addWidget(self._price_label)

        # ── Order type toggle ──
        tr_lo = QHBoxLayout()
        tr_lo.setSpacing(0)
        seg_market = (
            f"QPushButton{{background:{C_PANEL};color:{C_SUBTEXT};border:1px solid {C_BORDER};"
            f"border-radius:{dps(6)} 0 0 {dps(6)};font-size:{fs(tr(11))};padding:{dps(3)} 0;}}"
            f"QPushButton:checked{{background:{_PAL['gold']};color:#1A1410;border-color:{_PAL['gold']};}}"
        )
        seg_limit = (
            f"QPushButton{{background:{C_PANEL};color:{C_SUBTEXT};border:1px solid {C_BORDER};"
            f"border-radius:0 {dps(6)} {dps(6)} 0;border-left:none;font-size:{fs(tr(11))};padding:{dps(3)} 0;}}"
            f"QPushButton:checked{{background:{_PAL['gold']};color:#1A1410;border-color:{_PAL['gold']};}}"
        )
        self._market_btn = QPushButton("市价单")
        self._market_btn.setCheckable(True)
        self._market_btn.setChecked(True)
        self._market_btn.setFixedHeight(dp(26))
        self._market_btn.setCursor(Qt.PointingHandCursor)
        self._market_btn.setStyleSheet(seg_market)
        self._market_btn.setToolTip("以当前市场价格立即成交")
        self._market_btn.clicked.connect(lambda: self._set_order_type('market'))
        tr_lo.addWidget(self._market_btn, 1)

        self._limit_btn = QPushButton("限价单")
        self._limit_btn.setCheckable(True)
        self._limit_btn.setFixedHeight(dp(26))
        self._limit_btn.setCursor(Qt.PointingHandCursor)
        self._limit_btn.setStyleSheet(seg_limit)
        self._limit_btn.setToolTip("挂出限价委托，价格到达后自动成交")
        self._limit_btn.clicked.connect(lambda: self._set_order_type('limit'))
        tr_lo.addWidget(self._limit_btn, 1)
        lo.addLayout(tr_lo)

        # ── Qty ──
        qr = QHBoxLayout()
        qr.setSpacing(dp(6))
        ql = QLabel("数量")
        ql.setStyleSheet(style_label())
        qr.addWidget(ql)
        self._qty = QSpinBox()
        self._qty.setRange(100, 1000000)
        self._qty.setSingleStep(100)
        self._qty.setValue(100)
        self._qty.setFixedHeight(dp(28))
        self._qty.setStyleSheet(qss_spinbox())
        self._qty.valueChanged.connect(self._refresh_estimate)
        qr.addWidget(self._qty, 1)
        lo.addLayout(qr)

        # ── Limit price (whole row hidden in market mode) ──
        self._price_row_widget = QWidget()
        pr = QHBoxLayout(self._price_row_widget)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(dp(6))
        pl = QLabel("价格")
        pl.setStyleSheet(style_label())
        pr.addWidget(pl)
        self._price_box = QDoubleSpinBox()
        self._price_box.setRange(0.01, 99999)
        self._price_box.setDecimals(2)
        self._price_box.setValue(0.01)
        self._price_box.setFixedHeight(dp(28))
        self._price_box.setStyleSheet(qss_spinbox())
        self._price_box.valueChanged.connect(self._refresh_estimate)
        pr.addWidget(self._price_box, 1)
        self._price_row_widget.hide()
        lo.addWidget(self._price_row_widget)

        # ── Estimate ──
        self._est = QLabel("")
        self._est.setStyleSheet(style_caption())
        lo.addWidget(self._est)

        # ── Place button ──
        self._place_btn = QPushButton("确认下单")
        self._place_btn.setFixedHeight(dp(34))
        self._place_btn.setCursor(Qt.PointingHandCursor)
        self._place_btn.setStyleSheet(qss_btn_accent())
        self._place_btn.clicked.connect(self._emit_place)
        lo.addWidget(self._place_btn)

    def _set_side(self, side):
        self._side = side
        self._buy_btn.setChecked(side == 'buy')
        self._sell_btn.setChecked(side == 'sell')
        self._refresh_estimate()

    def _set_order_type(self, ot):
        self._order_type = ot
        self._market_btn.setChecked(ot == 'market')
        self._limit_btn.setChecked(ot == 'limit')
        self._price_row_widget.setVisible(ot == 'limit')
        self._refresh_estimate()

    def set_stock(self, code, name):
        self._code = code
        self._name = name
        self._price_label.setText("%s  %s  现价: --" % (code, name))

    def set_current_price(self, price):
        self._current_price = price
        self._price_label.setText("%s  %s  现价: %.2f" % (self._code, self._name, price))
        self._price_label.setStyleSheet(
            f"color:{C_TEXT};font-size:{fs(12)};font-weight:600;background:transparent;")
        if self._order_type == 'limit' and self._price_box.value() < 0.01:
            self._price_box.setValue(price)
        self._refresh_estimate()

    def _refresh_estimate(self):
        exec_price = (self._current_price if self._order_type == 'market'
                      else self._price_box.value())
        qty = self._qty.value()
        if exec_price <= 0 or qty <= 0:
            self._est.setText("")
            return

        commission = exec_price * qty * 0.0003
        stamp = exec_price * qty * 0.0005 if self._side == 'sell' else 0

        if self._side == 'buy':
            cost = exec_price * qty + commission
            self._est.setText("预估成本: {:,.2f}  (佣金 {:.2f})".format(cost, commission))
            self._est.setStyleSheet(
                f"color:{C_UP};font-size:{fs(10)};background:transparent;")
        else:
            proceeds = exec_price * qty - commission - stamp
            self._est.setText("预计收入: {:,.2f}  (佣金 {:.2f} + 印花 {:.2f})"
                              .format(proceeds, commission, stamp))
            self._est.setStyleSheet(
                f"color:{C_DOWN};font-size:{fs(10)};background:transparent;")

    def _emit_place(self):
        self.order_placed.emit()

    def get_params(self):
        exec_price = (self._current_price if self._order_type == 'market'
                      else self._price_box.value())
        return {
            'code': self._code,
            'name': self._name,
            'side': self._side,
            'order_type': self._order_type,
            'price': exec_price,
            'qty': self._qty.value(),
            'current_price': self._current_price,
        }


# ──────────────────────────────────────────────────────────────
#  PositionTable
# ──────────────────────────────────────────────────────────────

class _PositionTable(QTableWidget):
    row_clicked = pyqtSignal(str, str)  # code, name

    def __init__(self):
        super().__init__(0, 7)
        self.setHorizontalHeaderLabels([
            "代码", "名称", "数量", "成本", "现价", "盈亏 / 市值", "卖出条件",
        ])
        self.setStyleSheet(qss_table())
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setColumnWidth(0, dp(62))
        self.setColumnWidth(1, dp(72))
        self.setColumnWidth(2, dp(52))
        self.setColumnWidth(3, dp(62))
        self.setColumnWidth(4, dp(62))
        self.cellClicked.connect(self._on_click)
        self._guard = {}   # code -> {reason_cn, exec_price} (来自 day_guard_log)

    def set_guard(self, guard_map):
        """注入每日守护结果: {code: {reason_cn, exec_price, action}}."""
        self._guard = guard_map or {}

    def _on_click(self, row, col):
        code = self.item(row, 0).text() if self.item(row, 0) else ""
        name = self.item(row, 1).text() if self.item(row, 1) else ""
        if code:
            self.row_clicked.emit(code, name)

    def load(self, positions):
        self.setRowCount(len(positions))
        for i, p in enumerate(positions):
            fp = p.get('float_pnl', 0)
            code = p['code']
            g = self._guard.get(code)
            if g and g.get('reason_cn'):
                sell_txt = g.get('reason_cn', '')
                sell_clr = C_DOWN if g.get('reason_cn') in ('止损',) else (C_UP if g.get('reason_cn') in ('止盈',) else "#D29922")
                sell_tip = f"触发{g.get('reason_cn')} @{g.get('exec_price') or p['current_price']}"
            else:
                sell_txt = "保护中"
                sell_clr = C_SUBTEXT
                sell_tip = "止损5%/止盈12%/时间止损=持有期 · 未触发, 继续持有"
            items = [
                (code, C_TEXT, Qt.AlignLeft),
                (p['name'], C_TEXT, Qt.AlignLeft),
                (str(p['qty']), C_TEXT, Qt.AlignRight),
                ("%.2f" % p['cost_price'], C_SUBTEXT, Qt.AlignRight),
                ("%.2f" % p['current_price'], C_TEXT, Qt.AlignRight),
                ("{:+,.2f} / {:.0f}".format(fp, p.get('market_value', 0)),
                 C_UP if fp > 0 else (C_DOWN if fp < 0 else C_TEXT), Qt.AlignRight),
                (sell_txt, sell_clr, Qt.AlignLeft),
            ]
            for j, (val, clr, align) in enumerate(items):
                it = QTableWidgetItem(str(val))
                it.setForeground(QColor(clr))
                it.setTextAlignment(align | Qt.AlignVCenter)
                if j == 6:
                    it.setToolTip(sell_tip)
                self.setItem(i, j, it)


# ──────────────────────────────────────────────────────────────
#  PendingOrders
# ──────────────────────────────────────────────────────────────

class _PendingOrders(QWidget):
    cancel_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(dp(4))

        self._header = QPushButton("▸ 待成交委托 (0)")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_SUBTEXT};border:none;"
            f"font-size:{fs(12)};font-weight:600;text-align:left;padding:{dps(4)} 0;}}"
            f"QPushButton:hover{{color:{C_TEXT};}}"
        )
        self._header.clicked.connect(self._toggle)
        lo.addWidget(self._header)

        self._content = QWidget()
        self._content_lo = QVBoxLayout(self._content)
        self._content_lo.setContentsMargins(0, 0, 0, 0)
        self._content_lo.setSpacing(dp(2))
        lo.addWidget(self._content)

    def _toggle(self):
        self._content.setVisible(not self._content.isVisible())

    def load(self, orders, on_cancel):
        arrow = "▾" if self._content.isVisible() else "▸"
        self._header.setText("%s 待成交委托 (%d)" % (arrow, len(orders)))

        while self._content_lo.count():
            w = self._content_lo.takeAt(0).widget()
            if w:
                w.deleteLater()

        for o in orders:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(dp(4), dp(2), dp(4), dp(2))
            rl.setSpacing(dp(6))

            side_color = C_UP if o['side'] == 'buy' else C_DOWN
            side_text = "买入" if o['side'] == 'buy' else "卖出"
            info = QLabel("%s  %s  限价 %.2f  %d 股"
                          % (o['code'], side_text, o['price'], o['qty']))
            info.setStyleSheet(f"color:{C_TEXT};font-size:{fs(11)};background:transparent;")
            rl.addWidget(info, 1)

            cancel_btn = QPushButton("撤单")
            cancel_btn.setFixedSize(dp(44), dp(22))
            cancel_btn.setCursor(Qt.PointingHandCursor)
            cancel_btn.setStyleSheet(
                f"QPushButton{{background:{C_PANEL};color:{C_SUBTEXT};border:1px solid {C_BORDER};"
                f"border-radius:{dps(4)};font-size:{fs(10)};}}"
                f"QPushButton:hover{{color:{C_UP};border-color:{C_UP};}}"
            )
            cancel_btn.clicked.connect(lambda checked, oid=o['id']: on_cancel(oid))
            rl.addWidget(cancel_btn)

            self._content_lo.addWidget(row)


# ──────────────────────────────────────────────────────────────
#  TradeHistory
# ──────────────────────────────────────────────────────────────

class _TradeHistory(QTableWidget):
    def __init__(self):
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels(["时间", "代码", "方向", "价格", "数量"])
        self.setStyleSheet(qss_table())
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setColumnWidth(0, dp(128))
        self.setColumnWidth(1, dp(56))
        self.setColumnWidth(2, dp(42))
        self.setColumnWidth(3, dp(60))

    def load(self, trades):
        self.setRowCount(len(trades))
        for i, t in enumerate(trades):
            side_text = "买入" if t['side'] == 'buy' else "卖出"
            side_color = C_UP if t['side'] == 'buy' else C_DOWN
            traded_at = t.get('traded_at', '')[:16]
            items = [
                (traded_at, C_SUBTEXT),
                (t['code'], C_TEXT),
                (side_text, side_color),
                ("%.2f" % t['price'], C_TEXT),
                (str(t['qty']), C_TEXT),
            ]
            for j, (val, clr) in enumerate(items):
                it = QTableWidgetItem(str(val))
                it.setForeground(QColor(clr))
                self.setItem(i, j, it)


# ──────────────────────────────────────────────────────────────
#  TradePanel
# ──────────────────────────────────────────────────────────────

class TradePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._kline_db = None
        self._engine = TradeEngine()
        self._cur_account = None
        self._poll_worker = None
        self._price_worker = None
        self.on_open_kline = None
        self.on_status = None
        self.on_account_changed = None

        self._timer = QTimer(self)
        self._timer.setInterval(8000)
        self._timer.timeout.connect(self._poll_prices)

        self._build_ui()

        if not self._engine.list_accounts():
            self._engine.create_account("主账户", 100000)
        # Pick up the initial account selection (combo signals are blocked
        # while loading, so the first account never fires account_changed).
        self._account_bar._load()
        first_id = self._account_bar.current_id()
        if first_id:
            self._cur_account = first_id
            QTimer.singleShot(0, self.refresh)

    def set_kline_db(self, path):
        self._kline_db = path
        self._search.set_db(path)

    def current_account_id(self):
        return self._cur_account

    def reload_accounts(self, select_id=None):
        """Reload the account combo (e.g. after the companion created/deleted an
        account). Optionally select `select_id`, else restore the current
        selection, then re-emit + refresh so the right-side companion stays in
        sync."""
        combo = self._account_bar._combo
        self._account_bar._load()
        target = select_id if select_id is not None else self._cur_account
        found = False
        for i in range(combo.count()):
            if combo.itemData(i) == target:
                combo.setCurrentIndex(i)
                found = True
                break
        if not found and combo.count() > 0:
            combo.setCurrentIndex(0)
        self.refresh()

    def _status(self, msg):
        if self.on_status:
            self.on_status(msg)

    def _build_ui(self):
        self.setStyleSheet(f"background:{C_BG}")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{background:{C_BG};border:none}}")

        container = QWidget()
        container.setStyleSheet(f"background:{C_BG}")
        lo = QVBoxLayout(container)
        lo.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        lo.setSpacing(dp(10))

        # 页头
        title = QLabel("交易")
        title.setStyleSheet(style_title() + f"color:{C_TEXT};")
        lo.addWidget(title)

        # 顶部固定: 账户切换 + 总览摘要卡
        self._account_bar = _AccountBar(self._engine)
        self._account_bar.account_changed.connect(self._on_account_changed)
        lo.addWidget(self._account_bar)
        self._cards = _SummaryCards()
        lo.addWidget(self._cards)

        # ── 核心 3 个页签: 下单 / 持仓 / 成交记录 (一次只见一块) ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {C_BORDER_SOFT};border-radius:{dps(6)};margin-top:{dps(4)};}}"
            f"QTabBar::tab{{background:transparent;color:{C_SUBTEXT};padding:{dps(6)} {dps(18)};"
            f"border:none;border-bottom:2px solid transparent;font-size:{fs(tr(12))};font-weight:600;}}"
            f"QTabBar::tab:hover{{color:{C_TEXT};}}"
            f"QTabBar::tab:selected{{color:{C_GOLD};border-bottom:2px solid {C_GOLD};}}")

        # Tab1 下单: 搜索 + 下单面板 + 挂单
        tab_order = QWidget(); tab_order.setStyleSheet(f"background:{C_BG}")
        olo = QVBoxLayout(tab_order)
        olo.setContentsMargins(dp(12), dp(10), dp(12), dp(10)); olo.setSpacing(dp(10))
        olo.addWidget(QLabel("买卖下单"))
        self._search = _StockSearch()
        self._search.stock_selected.connect(self._on_stock_selected)
        olo.addWidget(self._search)
        self._order = _OrderPanel()
        self._order.order_placed.connect(self._on_place_order)
        olo.addWidget(self._order)
        self._pending = _PendingOrders()
        olo.addWidget(self._pending)
        olo.addStretch()
        self._tabs.addTab(tab_order, "下单")

        # Tab2 持仓: 持仓表
        tab_pos = QWidget(); tab_pos.setStyleSheet(f"background:{C_BG}")
        plo = QVBoxLayout(tab_pos)
        plo.setContentsMargins(dp(12), dp(10), dp(12), dp(10)); plo.setSpacing(dp(10))
        self._pos_table = _PositionTable()
        self._pos_table.row_clicked.connect(self._on_position_clicked)
        plo.addWidget(self._pos_table)
        plo.addStretch()
        self._tabs.addTab(tab_pos, "持仓")

        # Tab3 成交记录
        tab_hist = QWidget(); tab_hist.setStyleSheet(f"background:{C_BG}")
        hlo = QVBoxLayout(tab_hist)
        hlo.setContentsMargins(dp(12), dp(10), dp(12), dp(10)); hlo.setSpacing(dp(10))
        self._trade_hist = _TradeHistory()
        hlo.addWidget(self._trade_hist)
        hlo.addStretch()
        self._tabs.addTab(tab_hist, "成交记录")

        lo.addWidget(self._tabs)
        lo.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Account ──

    def _on_account_changed(self, aid):
        self._cur_account = aid
        self._poll_prices()
        self._timer.start()
        if self.on_account_changed:
            self.on_account_changed(aid)

    # ── Stock selection ──

    def _on_stock_selected(self, code, name):
        self._order.set_stock(code, name)
        self._fetch_and_set_price(code)
        if self.on_open_kline:
            self.on_open_kline(code, name)

    def _on_position_clicked(self, code, name):
        self._search.set_code(code)
        self._order.set_stock(code, name)
        self._order._set_side('sell')
        self._fetch_and_set_price(code)

    def _fetch_and_set_price(self, code):
        """Fetch one quote off the UI thread."""
        if self._price_worker is not None and self._price_worker.isRunning():
            return

        def _fetch(c):
            from data_manager import fetch_realtime_prices
            return {"code": 0, "data": fetch_realtime_prices([c]) or []}

        self._price_worker = LocalWorker(_fetch, "quote", args=[code])
        self._price_worker.result.connect(self._on_quote)
        self._price_worker.start()

    def _on_quote(self, tag, data):
        if data.get("code") != 0 or not data.get("data"):
            self._status("获取现价失败")
            return
        self._order.set_current_price(data["data"][0]['price'])

    # ── Order placement ──

    def _on_place_order(self):
        if self._cur_account is None:
            self._status("请先选择账户")
            return
        p = self._order.get_params()
        if not p['code']:
            self._status("请先选择股票")
            return

        order, result = self._engine.place_order(
            self._cur_account, p['code'], p['name'], p['side'],
            p['order_type'], p['price'], p['qty'],
            current_price=p['current_price'],
        )

        if order is None:
            self._status("下单失败: %s" % result)
            return

        side_text = "买入" if p['side'] == 'buy' else "卖出"
        if result is not None:
            self._status("已成交: %s %s %d股 @ %.2f"
                         % (side_text, p['code'], p['qty'], result['price']))
        else:
            self._status("已挂单: %s %s %d股 @ %.2f"
                         % (side_text, p['code'], p['qty'], order['price']))
        self.refresh()

    # ── Price polling (background) ──

    def _poll_prices(self):
        if self._cur_account is None:
            return
        if self._poll_worker is not None and self._poll_worker.isRunning():
            return

        positions = self._engine.get_positions(self._cur_account)
        pending = self._engine.get_orders(self._cur_account, status='pending')
        codes = set(p['code'] for p in positions)
        codes.update(o['code'] for o in pending)

        if not codes:
            self.refresh()
            return

        def _fetch(code_list):
            from data_manager import fetch_realtime_prices
            return {"code": 0, "data": fetch_realtime_prices(code_list) or []}

        self._poll_worker = LocalWorker(_fetch, "poll", args=[list(codes)])
        self._poll_worker.result.connect(self._on_poll)
        self._poll_worker.start()

    def _on_poll(self, tag, data):
        if data.get("code") != 0:
            self._status("价格轮询失败: %s" % data.get("error", ""))
            return
        try:
            for r in data.get("data", []):
                code = r['code']
                price = r['price']
                self._engine.update_position_price(self._cur_account, code, price)
                self._engine.check_orders(self._cur_account, code, price)
            self.refresh()
        except Exception as e:
            self._status("价格更新失败: %s" % e)

    def _on_cancel_order(self, order_id):
        ok, err = self._engine.cancel_order(order_id)
        if ok:
            self._status("已撤单")
        else:
            self._status("撤单失败: %s" % (err or ""))
        self.refresh()

    # ── Refresh ──

    def refresh(self):
        if self._cur_account is None:
            return

        summary = self._engine.get_summary(self._cur_account)
        self._cards.update_summary(summary)

        positions = self._engine.get_positions(self._cur_account)
        self._pos_table.set_guard(self._load_guard_map())
        self._pos_table.load(positions)

        pending = self._engine.get_orders(self._cur_account, status='pending')
        self._pending.load(pending, self._on_cancel_order)

        trades = self._engine.get_trades(self._cur_account, limit=30)
        self._trade_hist.load(trades)

    def _load_guard_map(self):
        """读 data/day_guard_log.json 返回 {code: {reason_cn, exec_price}} 供持仓表展示卖出条件."""
        import os, json
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), 'data', 'day_guard_log.json')
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return {}
        out = {}
        for c in (d.get('checked') or []):
            code = c.get('code')
            if code and c.get('reason_cn'):
                out[code] = {"reason_cn": c.get('reason_cn'), "exec_price": c.get('exec_price')}
        return out
