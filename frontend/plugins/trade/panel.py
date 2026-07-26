# -*- coding: utf-8 -*-
"""Trade panel — order entry, positions, trade history."""

import sys, os, sqlite3

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from trade_engine.engine import TradeEngine
from frontend.platform.theme import dp, dps

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QDoubleSpinBox, QFrame, QScrollArea, QListWidget, QListWidgetItem,
    QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor

from .styles import (
    C_BG, C_PANEL, C_BORDER, C_TEXT, C_SUBTEXT, C_ACCENT,
    C_GREEN, C_RED, C_UP, C_DOWN,
)

# ── Shared shorthand style fragments ──
_CARD = ("QFrame#card{background:%s;border:1px solid %s;border-radius:6px;padding:10px}"
         % (C_PANEL, C_BORDER))
_BTN = (
    "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
    "font-size:20px;padding:4px 10px}" % (C_PANEL, C_TEXT, C_BORDER)
    + "QPushButton:hover{border-color:" + C_ACCENT + ";color:" + C_ACCENT + "}"
    + "QPushButton:disabled{color:" + C_SUBTEXT + "}"
)
_BTN_ACCENT = (
    "QPushButton{background:%s;color:#0D1117;border:none;border-radius:4px;"
    "font-size:20px;font-weight:700;padding:6px 14px}" % C_ACCENT
    + "QPushButton:hover{background:#E0B888}"
    + "QPushButton:disabled{background:" + C_BORDER + ";color:" + C_SUBTEXT + "}"
)
_TABLE = (
    "QTableWidget{background:%s;color:%s;border:1px solid %s;gridline-color:%s;font-size:19px}"
    % (C_PANEL, C_TEXT, C_BORDER, C_BORDER)
    + "QHeaderView::section{background:" + C_PANEL + ";color:" + C_SUBTEXT
    + ";border:none;padding:3px;font-size:19px}"
    + "QTableWidget::item:selected{background:" + C_ACCENT + ";color:#0D1117}"
)

# ──────────────────────────────────────────────────────────
#  AccountBar
# ──────────────────────────────────────────────────────────

class _AccountBar(QWidget):
    account_changed = pyqtSignal(int)

    def __init__(self, engine):
        super().__init__()
        self._engine = engine
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        lbl = QLabel("\u8d26\u6237:")
        lbl.setStyleSheet("color:%s;font-size:20px;background:transparent" % C_SUBTEXT)
        lo.addWidget(lbl)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(dp(120))
        self._combo.setStyleSheet(
            "QComboBox{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
            "padding:3px 8px;font-size:20px}" % (C_PANEL, C_TEXT, C_BORDER)
            + "QComboBox:hover{border-color:%s}" % C_ACCENT
            + "QComboBox QAbstractItemView{background:%s;color:%s;"
            "selection-background-color:%s;selection-color:#0D1117;border:1px solid %s}"
            % (C_PANEL, C_TEXT, C_ACCENT, C_BORDER)
        )
        self._combo.currentIndexChanged.connect(self._emit)
        lo.addWidget(self._combo)

        btn_new = QPushButton("+\u65b0\u5efa")
        btn_new.setFixedHeight(dp(28))
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.setStyleSheet(_BTN)
        btn_new.clicked.connect(self._create)
        lo.addWidget(btn_new)

        btn_reset = QPushButton("\u91cd\u7f6e")
        btn_reset.setFixedHeight(dp(28))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(_BTN)
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
        aid = self._engine.create_account("\u4e3b\u8d26\u6237", 100000)
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


# ──────────────────────────────────────────────────────────
#  SummaryCards
# ──────────────────────────────────────────────────────────

class _SummaryCards(QWidget):
    def __init__(self):
        super().__init__()
        self._labels = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        items = [
            ("\u603b\u8d44\u4ea7", "total_assets", 0, 0),
            ("\u53ef\u7528\u8d44\u91d1", "balance", 0, 1),
            ("\u51bb\u7ed3\u8d44\u91d1", "frozen", 0, 2),
            ("\u6301\u4ed3\u5e02\u503c", "market_value", 1, 0),
            ("\u6d6e\u52a8\u76c8\u4e8f", "float_pnl", 1, 1),
            ("\u7d2f\u8ba1\u76c8\u4e8f", "total_profit", 1, 2),
        ]
        for label, key, row, col in items:
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(_CARD)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 6, 8, 6)
            cl.setSpacing(2)

            lb = QLabel(label)
            lb.setStyleSheet("color:%s;font-size:19px;background:transparent" % C_SUBTEXT)
            cl.addWidget(lb)

            val = QLabel("--")
            val.setStyleSheet("color:%s;font-size:22px;font-weight:700;background:transparent" % C_TEXT)
            cl.addWidget(val)
            self._labels[key] = val
            grid.addWidget(card, row, col)

    def update_summary(self, summary):
        if summary is None:
            return
        fmt = lambda k, f: self._labels[k].setText(f.format(summary.get(k, 0)))

        fmt("total_assets", "{:,.2f}")
        fmt("balance", "{:,.2f}")
        fmt("frozen", "{:,.2f}")
        fmt("market_value", "{:,.2f}")

        fp = summary.get("float_pnl", 0)
        fp_label = self._labels["float_pnl"]
        fp_label.setText("{:+,.2f}".format(fp))
        fp_label.setStyleSheet("color:%s;font-size:22px;font-weight:700;background:transparent"
                               % (C_UP if fp >= 0 else C_DOWN))

        tp = summary.get("total_profit", 0)
        tp_label = self._labels["total_profit"]
        tp_label.setText("{:+,.2f} ({:+.2f}%)".format(tp, summary.get("total_profit_pct", 0)))
        tp_label.setStyleSheet("color:%s;font-size:13px;font-weight:700;background:transparent"
                               % (C_RED if tp > 0 else (C_GREEN if tp < 0 else C_SUBTEXT)))


# ──────────────────────────────────────────────────────────
#  StockSearch
# ──────────────────────────────────────────────────────────

class _StockSearch(QWidget):
    stock_selected = pyqtSignal(str, str)  # code, name

    def __init__(self, kline_db):
        super().__init__()
        self._kline_db = kline_db
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._do_search)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._input = QLineEdit()
        self._input.setPlaceholderText("\u8f93\u5165\u4ee3\u7801\u6216\u540d\u79f0...")
        self._input.setStyleSheet(
            "QLineEdit{background:%s;color:%s;border:1px solid %s;"
            "border-radius:4px;padding:4px 8px;font-size:20px}"
            "QLineEdit:focus{border-color:%s}" % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        self._input.textChanged.connect(self._on_text)
        lo.addWidget(self._input)

        self._list = QListWidget()
        self._list.setMaximumHeight(dp(150))
        self._list.setStyleSheet(
            "QListWidget{background:%s;color:%s;border:1px solid %s;font-size:19px}"
            "QListWidget::item{padding:4px 8px}"
            "QListWidget::item:selected{background:%s;color:#0D1117}"
            % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        self._list.itemClicked.connect(self._on_select)
        self._list.hide()
        lo.addWidget(self._list)

    def _on_text(self, text):
        text = text.strip()
        if len(text) < 1:
            self._list.hide()
            return
        self._timer.start(250)

    def _do_search(self):
        text = self._input.text().strip()
        if len(text) < 1:
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


# ──────────────────────────────────────────────────────────
#  OrderPanel
# ──────────────────────────────────────────────────────────

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
        lo.setSpacing(6)

        # Side toggle
        sr = QHBoxLayout()
        sr.setSpacing(0)
        self._buy_btn = QPushButton("\U0001f4c8 \u4e70\u5165")
        self._buy_btn.setCheckable(True)
        self._buy_btn.setChecked(True)
        self._buy_btn.setFixedHeight(dp(32))
        self._buy_btn.setCursor(Qt.PointingHandCursor)
        self._buy_btn.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px 0 0 4px;"
            "font-size:13px;font-weight:700}"
            "QPushButton:checked{background:%s;color:#0D1117;border-color:%s}"
            % (C_PANEL, C_UP, C_BORDER, C_UP, C_UP)
        )
        self._buy_btn.clicked.connect(lambda: self._set_side('buy'))
        sr.addWidget(self._buy_btn, 1)

        self._sell_btn = QPushButton("\U0001f4c9 \u5356\u51fa")
        self._sell_btn.setCheckable(True)
        self._sell_btn.setFixedHeight(dp(32))
        self._sell_btn.setCursor(Qt.PointingHandCursor)
        self._sell_btn.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:0 4px 4px 0;"
            "font-size:13px;font-weight:700}"
            "QPushButton:checked{background:%s;color:#0D1117;border-color:%s}"
            % (C_PANEL, C_DOWN, C_BORDER, C_DOWN, C_DOWN)
        )
        self._sell_btn.clicked.connect(lambda: self._set_side('sell'))
        sr.addWidget(self._sell_btn, 1)
        lo.addLayout(sr)

        # Price display
        self._price_label = QLabel("\u73b0\u4ef7: --")
        self._price_label.setStyleSheet("color:%s;font-size:13px;font-weight:600;background:transparent" % C_TEXT)
        lo.addWidget(self._price_label)

        # Order type toggle
        tr = QHBoxLayout()
        tr.setSpacing(0)
        self._market_btn = QPushButton("\u5e02\u4ef7\u5355")
        self._market_btn.setCheckable(True)
        self._market_btn.setChecked(True)
        self._market_btn.setFixedHeight(dp(28))
        self._market_btn.setCursor(Qt.PointingHandCursor)
        self._market_btn.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px 0 0 4px;font-size:19px}"
            "QPushButton:checked{background:%s;color:%s;border-color:%s}"
            % (C_PANEL, C_SUBTEXT, C_BORDER, C_ACCENT, C_ACCENT, C_ACCENT)
        )
        self._market_btn.clicked.connect(lambda: self._set_order_type('market'))
        tr.addWidget(self._market_btn, 1)

        self._limit_btn = QPushButton("\u9650\u4ef7\u5355")
        self._limit_btn.setCheckable(True)
        self._limit_btn.setFixedHeight(dp(28))
        self._limit_btn.setCursor(Qt.PointingHandCursor)
        self._limit_btn.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:0 4px 4px 0;font-size:19px}"
            "QPushButton:checked{background:%s;color:%s;border-color:%s}"
            % (C_PANEL, C_SUBTEXT, C_BORDER, C_ACCENT, C_ACCENT, C_ACCENT)
        )
        self._limit_btn.clicked.connect(lambda: self._set_order_type('limit'))
        tr.addWidget(self._limit_btn, 1)
        lo.addLayout(tr)

        # Qty
        qr = QHBoxLayout()
        qr.setSpacing(6)
        ql = QLabel("\u6570\u91cf:")
        ql.setStyleSheet("color:%s;font-size:19px;background:transparent" % C_SUBTEXT)
        qr.addWidget(ql)
        self._qty = QSpinBox()
        self._qty.setRange(100, 1000000)
        self._qty.setSingleStep(100)
        self._qty.setValue(100)
        self._qty.setStyleSheet(
            "QSpinBox{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
            "padding:4px 6px;font-size:20px}"
            "QSpinBox:focus{border-color:%s}" % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        self._qty.valueChanged.connect(self._refresh_estimate)
        qr.addWidget(self._qty, 1)
        lo.addLayout(qr)

        # Limit price
        self._price_box = QDoubleSpinBox()
        self._price_box.setRange(0.01, 99999)
        self._price_box.setDecimals(2)
        self._price_box.setValue(0.01)
        self._price_box.setStyleSheet(
            "QDoubleSpinBox{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
            "padding:4px 6px;font-size:20px}"
            "QDoubleSpinBox:focus{border-color:%s}" % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        self._price_box.valueChanged.connect(self._refresh_estimate)
        self._price_box.hide()

        self._price_row = QHBoxLayout()
        self._price_row.setSpacing(6)
        pl = QLabel("\u4ef7\u683c:")
        pl.setStyleSheet("color:%s;font-size:19px;background:transparent" % C_SUBTEXT)
        self._price_row.addWidget(pl)
        self._price_row.addWidget(self._price_box, 1)
        lo.addLayout(self._price_row)

        # Estimate
        self._est = QLabel("")
        self._est.setStyleSheet("color:%s;font-size:19px;background:transparent;padding:2px 0" % C_SUBTEXT)
        lo.addWidget(self._est)

        # Place button
        self._place_btn = QPushButton("\u786e\u8ba4\u4e0b\u5355")
        self._place_btn.setFixedHeight(dp(36))
        self._place_btn.setCursor(Qt.PointingHandCursor)
        self._place_btn.setStyleSheet(_BTN_ACCENT)
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
        self._price_box.setVisible(ot == 'limit')
        self._refresh_estimate()

    def set_stock(self, code, name):
        self._code = code
        self._name = name
        self._price_label.setText("%s  %s  \u73b0\u4ef7: --" % (code, name))

    def set_current_price(self, price):
        self._current_price = price
        change = ""
        self._price_label.setText("%s  %s  \u73b0\u4ef7: %.2f%s"
                                  % (self._code, self._name, price, change))
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
            self._est.setText("\u9884\u4f30\u6210\u672c: {:,.2f}  (\u4f63\u91d1: {:.2f})".format(cost, commission))
            self._est.setStyleSheet("color:%s;font-size:19px;background:transparent;padding:2px 0" % C_UP)
        else:
            proceeds = exec_price * qty - commission - stamp
            self._est.setText("\u9884\u8ba1\u6536\u5165: {:,.2f}  (\u4f63\u91d1: {:.2f} + \u5370\u82b1: {:.2f})"
                              .format(proceeds, commission, stamp))
            self._est.setStyleSheet("color:%s;font-size:19px;background:transparent;padding:2px 0" % C_DOWN)

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


# ──────────────────────────────────────────────────────────
#  PositionTable
# ──────────────────────────────────────────────────────────

class _PositionTable(QTableWidget):
    row_clicked = pyqtSignal(str, str)  # code, name
    quick_sell = pyqtSignal(str, str)   # code, name

    def __init__(self):
        super().__init__(0, 6)
        self.setHorizontalHeaderLabels([
            "\u4ee3\u7801", "\u540d\u79f0", "\u6570\u91cf", "\u6210\u672c",
            "\u73b0\u4ef7", "\u76c8\u4e8f/\u5e02\u503c",
        ])
        self._setup()
        self.cellClicked.connect(self._on_click)

    def _setup(self):
        self.setStyleSheet(_TABLE)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setColumnWidth(0, dp(60))
        self.setColumnWidth(1, dp(70))
        self.setColumnWidth(2, dp(50))
        self.setColumnWidth(3, dp(60))
        self.setColumnWidth(4, dp(60))

    def _on_click(self, row, col):
        code = self.item(row, 0).text() if self.item(row, 0) else ""
        name = self.item(row, 1).text() if self.item(row, 1) else ""
        if code:
            self.row_clicked.emit(code, name)

    def load(self, positions):
        self.setRowCount(len(positions))
        for i, p in enumerate(positions):
            fp = p.get('float_pnl', 0)
            items = [
                (p['code'], C_TEXT),
                (p['name'], C_TEXT),
                (str(p['qty']), C_TEXT),
                ("%.2f" % p['cost_price'], C_SUBTEXT),
                ("%.2f" % p['current_price'], C_TEXT),
                ("{:+,.2f} / {:.0f}".format(fp, p.get('market_value', 0)),
                 C_UP if fp >= 0 else C_DOWN),
            ]
            for j, (val, clr) in enumerate(items):
                it = QTableWidgetItem(str(val))
                it.setForeground(QColor(clr))
                self.setItem(i, j, it)


# ──────────────────────────────────────────────────────────
#  PendingOrders
# ──────────────────────────────────────────────────────────

class _PendingOrders(QWidget):
    cancel_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)

        self._header = QPushButton("\u25b8 \u5f85\u6210\u4ea4\u59d4\u6258 (0)")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setCheckable(True)
        self._header.setChecked(True)
        self._header.setStyleSheet(
            "QPushButton{background:transparent;color:%s;border:none;font-size:20px;"
            "font-weight:600;text-align:left;padding:4px 0}"
            "QPushButton:checked{color:%s}" % (C_SUBTEXT, C_TEXT)
        )
        self._header.clicked.connect(self._toggle)
        lo.addWidget(self._header)

        self._content = QWidget()
        self._content_lo = QVBoxLayout(self._content)
        self._content_lo.setContentsMargins(0, 0, 0, 0)
        self._content_lo.setSpacing(2)
        lo.addWidget(self._content)

    def _toggle(self):
        self._content.setVisible(not self._content.isVisible())

    def load(self, orders, on_cancel):
        self._header.setText("\u25b8 \u5f85\u6210\u4ea4\u59d4\u6258 (%d)" % len(orders))

        while self._content_lo.count():
            w = self._content_lo.takeAt(0).widget()
            if w:
                w.deleteLater()

        for o in orders:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)
            rl.setSpacing(6)

            side_color = C_UP if o['side'] == 'buy' else C_DOWN
            side_text = "\u4e70\u5165" if o['side'] == 'buy' else "\u5356\u51fa"
            info = QLabel("%s %s \u9650\u4ef7 %.2f %d\u80a1"
                          % (o['code'], side_text, o['price'], o['qty']))
            info.setStyleSheet("color:%s;font-size:19px;background:transparent" % C_TEXT)
            rl.addWidget(info, 1)

            cancel_btn = QPushButton("\u64a4\u5355")
            cancel_btn.setFixedSize(dp(40), dp(22))
            cancel_btn.setCursor(Qt.PointingHandCursor)
            cancel_btn.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:3px;font-size:19px}"
                "QPushButton:hover{color:%s;border-color:%s}"
                % (C_PANEL, C_SUBTEXT, C_BORDER, C_RED, C_RED)
            )
            cancel_btn.clicked.connect(lambda checked, oid=o['id']: on_cancel(oid))
            rl.addWidget(cancel_btn)

            self._content_lo.addWidget(row)


# ──────────────────────────────────────────────────────────
#  TradeHistory
# ──────────────────────────────────────────────────────────

class _TradeHistory(QTableWidget):
    def __init__(self):
        super().__init__(0, 5)
        self.setHorizontalHeaderLabels([
            "\u65f6\u95f4", "\u4ee3\u7801", "\u65b9\u5411", "\u4ef7\u683c", "\u6570\u91cf",
        ])
        self._setup()

    def _setup(self):
        self.setStyleSheet(_TABLE)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setColumnWidth(0, dp(130))
        self.setColumnWidth(1, dp(55))
        self.setColumnWidth(2, dp(40))
        self.setColumnWidth(3, dp(60))

    def load(self, trades):
        self.setRowCount(len(trades))
        for i, t in enumerate(trades):
            side_text = "\u4e70" if t['side'] == 'buy' else "\u5356"
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


# ──────────────────────────────────────────────────────────
#  TradePanel
# ──────────────────────────────────────────────────────────

class TradePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._kline_db = None
        self._engine = TradeEngine()
        self._cur_account = None
        self.on_open_kline = None
        self.on_status = None

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._poll_prices)

        self._build_ui()

        accs = self._engine.list_accounts()
        if not accs:
            self._engine.create_account("\u4e3b\u8d26\u6237", 100000)

    def set_kline_db(self, path):
        self._kline_db = path

    def _status(self, msg):
        if self.on_status:
            self.on_status(msg)

    def _build_ui(self):
        self.setStyleSheet("background:%s" % C_BG)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:%s;border:none}" % C_BG)

        container = QWidget()
        container.setStyleSheet("background:%s" % C_BG)
        lo = QVBoxLayout(container)
        lo.setContentsMargins(10, 8, 10, 8)
        lo.setSpacing(8)

        title = QLabel("\U0001f4c8 \u6a21\u62df\u4ea4\u6613")
        title.setStyleSheet("color:%s;font-size:22px;font-weight:700;background:transparent" % C_TEXT)
        lo.addWidget(title)

        self._account_bar = _AccountBar(self._engine)
        self._account_bar.account_changed.connect(self._on_account_changed)
        lo.addWidget(self._account_bar)

        self._cards = _SummaryCards()
        lo.addWidget(self._cards)

        self._search = _StockSearch(self._kline_db)
        self._search.stock_selected.connect(self._on_stock_selected)
        lo.addWidget(self._search)

        self._order = _OrderPanel()
        self._order.order_placed.connect(self._on_place_order)
        lo.addWidget(self._order)

        self._pending = _PendingOrders()
        lo.addWidget(self._pending)

        pos_title = QLabel("\u6301\u4ed3")
        pos_title.setStyleSheet("color:%s;font-size:20px;font-weight:600;background:transparent" % C_SUBTEXT)
        lo.addWidget(pos_title)

        self._pos_table = _PositionTable()
        self._pos_table.row_clicked.connect(self._on_position_clicked)
        lo.addWidget(self._pos_table)

        trade_title = QLabel("\u6210\u4ea4\u8bb0\u5f55")
        trade_title.setStyleSheet("color:%s;font-size:20px;font-weight:600;background:transparent" % C_SUBTEXT)
        lo.addWidget(trade_title)

        self._trade_hist = _TradeHistory()
        self._trade_hist.setMaximumHeight(dp(150))
        lo.addWidget(self._trade_hist)

        lo.addStretch()

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_account_changed(self, aid):
        self._cur_account = aid
        self._poll_prices()
        self._timer.start()

    def _on_stock_selected(self, code, name):
        self._order.set_stock(code, name)
        self._fetch_and_set_price(code)

    def _on_position_clicked(self, code, name):
        self._search.set_code(code)
        self._order.set_stock(code, name)
        self._order._set_side('sell')
        self._fetch_and_set_price(code)

    def _fetch_and_set_price(self, code):
        try:
            from data_manager import fetch_realtime_prices
            results = fetch_realtime_prices([code])
            if results:
                self._order.set_current_price(results[0]['price'])
        except Exception as e:
            self._status("\u83b7\u53d6\u73b0\u4ef7\u5931\u8d25: %s" % e)

    def _on_place_order(self):
        if self._cur_account is None:
            self._status("\u8bf7\u5148\u9009\u62e9\u8d26\u6237")
            return
        p = self._order.get_params()
        if not p['code']:
            self._status("\u8bf7\u5148\u9009\u62e9\u80a1\u7968")
            return

        order, result = self._engine.place_order(
            self._cur_account, p['code'], p['name'], p['side'],
            p['order_type'], p['price'], p['qty'],
            current_price=p['current_price'],
        )

        if order is None:
            self._status("\u4e0b\u5355\u5931\u8d25: %s" % result)
            return

        side_text = "\u4e70\u5165" if p['side'] == 'buy' else "\u5356\u51fa"
        type_text = "\u5e02\u4ef7" if p['order_type'] == 'market' else "\u9650\u4ef7"
        if result is not None:
            self._status("\u5df2\u6210\u4ea4: %s %s %d\u80a1 @ %.2f"
                         % (side_text, p['code'], p['qty'], result['price']))
        else:
            self._status("\u5df2\u6302\u5355: %s %s %d\u80a1 @ %.2f"
                         % (type_text, p['code'], p['qty'], order['price']))

        self.refresh()

    def _poll_prices(self):
        if self._cur_account is None:
            return
        try:
            from data_manager import fetch_realtime_prices

            positions = self._engine.get_positions(self._cur_account)
            pending = self._engine.get_orders(self._cur_account, status='pending')
            codes = set(p['code'] for p in positions)
            codes.update(o['code'] for o in pending)

            if not codes:
                self.refresh()
                return

            results = fetch_realtime_prices(list(codes)) or []

            for r in results:
                code = r['code']
                price = r['price']
                self._engine.update_position_price(self._cur_account, code, price)
                self._engine.check_orders(self._cur_account, code, price)

            self.refresh()
        except Exception as e:
            self._status("\u4ef7\u683c\u8f6e\u8be2\u5931\u8d25: %s" % e)

    def _on_cancel_order(self, order_id):
        ok, err = self._engine.cancel_order(order_id)
        if ok:
            self._status("\u5df2\u64a4\u5355")
        else:
            self._status("\u64a4\u5355\u5931\u8d25: %s" % (err or ""))
        self.refresh()

    def refresh(self):
        if self._cur_account is None:
            return

        summary = self._engine.get_summary(self._cur_account)
        self._cards.update_summary(summary)

        positions = self._engine.get_positions(self._cur_account)
        self._pos_table.load(positions)

        pending = self._engine.get_orders(self._cur_account, status='pending')
        self._pending.load(pending, self._on_cancel_order)

        trades = self._engine.get_trades(self._cur_account, limit=30)
        self._trade_hist.load(trades)
