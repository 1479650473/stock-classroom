# -*- coding: utf-8 -*-
"""Trade companion — profit curve + account management."""

import os, sys, sqlite3
from datetime import datetime, date
from collections import defaultdict

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from trade_engine.engine import TradeEngine
from frontend.platform.theme import dp, dps

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDoubleSpinBox, QFrame, QInputDialog, QMessageBox,
)
from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QPainterPath

from .styles import (
    C_BG, C_PANEL, C_BORDER, C_TEXT, C_SUBTEXT, C_ACCENT,
    C_GREEN, C_RED, C_UP, C_DOWN,
)


class ProfitCurve(QWidget):
    """QPainter line chart — account total-assets trajectory over time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(dp(160))
        self._points = []
        self._engine = None
        self._account_id = None
        self._hover_idx = -1

    def set_data(self, points):
        self._points = points if points else []
        self._hover_idx = -1
        self.update()

    def load(self, engine, account_id):
        self._engine = engine
        self._account_id = account_id
        points = self._calc_curve(engine, account_id)
        self.set_data(points)

    def _calc_curve(self, engine, account_id):
        acc = engine.get_account(account_id)
        if not acc:
            return []
        initial = acc['initial_capital']
        created = acc.get('created_at', '')[:10]
        if not created:
            created = ''
        trades = engine.get_trades(account_id, limit=99999)
        items = []
        if created:
            items.append((created, initial, 'init'))
        if not trades:
            summary = engine.get_summary(account_id)
            total = summary['total_assets'] if summary else initial
            items.append((datetime.now().strftime('%Y-%m-%d'), total, 'now'))
            return items
        trades.sort(key=lambda t: t['traded_at'])
        daily_cash = defaultdict(float)
        for t in trades:
            day = t['traded_at'][:10]
            price = t.get('price', 0) or 0
            qty = t.get('qty', 0) or 0
            comm = t.get('commission', 0) or 0
            tax = t.get('stamp_tax', 0) or 0
            if t['side'] == 'buy':
                daily_cash[day] -= price * qty + comm
            else:
                daily_cash[day] += price * qty - comm - tax
        running = initial
        for day in sorted(daily_cash.keys()):
            running += daily_cash[day]
            items.append((day, running, 'cash'))
        summary = engine.get_summary(account_id)
        if summary:
            items.append((datetime.now().strftime('%Y-%m-%d'), summary['total_assets'], 'now'))
        return items

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        if w < 50 or h < 50:
            painter.end()
            return

        points = self._points
        if not points:
            painter.setPen(QColor(C_SUBTEXT))
            f = QFont()
            f.setPixelSize(13)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignCenter, "\u6682\u65e0\u6536\u76ca\u6570\u636e")
            painter.end()
            return

        font_val = QFont()
        font_val.setPixelSize(11)
        font_date = QFont()
        font_date.setPixelSize(10)

        MARGIN_T = 8
        MARGIN_B = 28
        MARGIN_L = 60
        MARGIN_R = 12

        chart_w = w - MARGIN_L - MARGIN_R
        chart_h = h - MARGIN_T - MARGIN_B
        if chart_w < 10 or chart_h < 10:
            painter.end()
            return

        vals = [p[1] for p in points]
        v_min = min(vals)
        v_max = max(vals)
        if v_max == v_min:
            v_max = v_min + 1
        pad = (v_max - v_min) * 0.1 or 1
        v_min -= pad
        v_max += pad

        def to_x(i):
            return MARGIN_L + (i / max(len(points) - 1, 1)) * chart_w

        def to_y(v):
            return MARGIN_T + (1 - (v - v_min) / (v_max - v_min)) * chart_h

        point_color = QColor(C_UP) if vals[-1] >= vals[0] else QColor(C_DOWN)

        # Background
        painter.fillRect(0, 0, w, h, QColor(C_BG))

        # Grid lines
        painter.setPen(QPen(QColor("#1A1F28"), 1, Qt.DotLine))
        n_grid = 5
        for j in range(n_grid + 1):
            y = MARGIN_T + (j / n_grid) * chart_h
            painter.drawLine(int(MARGIN_L), int(y), int(w - MARGIN_R), int(y))
            val = v_max - (j / n_grid) * (v_max - v_min)
            painter.setFont(font_val)
            painter.setPen(QColor(C_SUBTEXT))
            label = "{:,.0f}".format(val) if abs(val) >= 1000 else "{:.0f}".format(val)
            painter.drawText(QRectF(0, y - 8, MARGIN_L - 4, 16), Qt.AlignRight | Qt.AlignVCenter, label)

        # Filled area under curve
        grad_path = QPainterPath()
        first_y = to_y(points[0][1])
        grad_path.moveTo(to_x(0), MARGIN_T + chart_h)
        for i, (_, v, _) in enumerate(points):
            grad_path.lineTo(to_x(i), to_y(v))
        grad_path.lineTo(to_x(len(points) - 1), MARGIN_T + chart_h)
        grad_path.closeSubpath()
        painter.setPen(Qt.NoPen)
        gc = QColor(point_color)
        gc.setAlpha(30)
        painter.setBrush(gc)
        painter.drawPath(grad_path)

        # Curve line
        pen = QPen(point_color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for i in range(1, len(points)):
            x0, x1 = to_x(i - 1), to_x(i)
            y0, y1 = to_y(points[i - 1][1]), to_y(points[i][1])
            painter.drawLine(int(x0), int(y0), int(x1), int(y1))

        # Last point dot
        last_x = to_x(len(points) - 1)
        last_y = to_y(points[-1][1])
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(point_color, 2))
        painter.drawEllipse(int(last_x - 4), int(last_y - 4), 8, 8)

        # X-axis labels
        painter.setPen(QColor(C_SUBTEXT))
        painter.setFont(font_date)
        n_labels = min(len(points), 8)
        step = max(len(points) // max(n_labels, 1), 1)
        for i in range(0, len(points), step):
            label = points[i][0]
            if len(label) > 7:
                label = label[5:]
            x = to_x(i)
            painter.drawText(QRectF(x - 30, MARGIN_T + chart_h + 2, 60, 20),
                             Qt.AlignCenter, label)

        painter.end()

    def mouseMoveEvent(self, event):
        if not self._points:
            return
        w = self.width()
        h = self.height()
        MARGIN_L = 60
        MARGIN_R = 12
        MARGIN_T = 8
        MARGIN_B = 28
        chart_w = w - MARGIN_L - MARGIN_R
        if chart_w < 10 or len(self._points) < 2:
            return

        mx = event.x()
        idx = round((mx - MARGIN_L) / chart_w * (len(self._points) - 1))
        idx = max(0, min(idx, len(self._points) - 1))
        self._hover_idx = idx
        p = self._points[idx]
        self.setToolTip("{}\n{:,.2f}".format(p[0], p[1]))


class TradeCompanion(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:%s" % C_BG)
        self._engine = TradeEngine()
        self._account_id = None
        self.on_account_changed = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 12, 12, 12)
        lo.setSpacing(8)

        # ── Profit curve ──
        curve_title = QLabel("\U0001f4c8 \u8d26\u6237\u6536\u76ca\u66f2\u7ebf")
        curve_title.setStyleSheet(
            "color:%s;font-size:20px;font-weight:600;background:transparent" % C_ACCENT
        )
        lo.addWidget(curve_title)

        self._curve = ProfitCurve()
        lo.addWidget(self._curve, 1)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("QFrame{border:none;border-top:1px solid %s}" % C_BORDER)
        sep1.setFixedHeight(2)
        lo.addWidget(sep1)

        # ── Account management ──
        mgmt_title = QLabel("\u2699 \u8d26\u6237\u7ba1\u7406")
        mgmt_title.setStyleSheet(
            "color:%s;font-size:20px;font-weight:600;background:transparent" % C_ACCENT
        )
        lo.addWidget(mgmt_title)

        # Account info
        self._info_label = QLabel("\u8bf7\u5728\u5de6\u4fa7\u9009\u62e9\u8d26\u6237")
        self._info_label.setStyleSheet(
            "color:%s;font-size:19px;background:transparent;padding:4px 0" % C_SUBTEXT
        )
        self._info_label.setWordWrap(True)
        lo.addWidget(self._info_label)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_rename = QPushButton("\u91cd\u547d\u540d")
        btn_rename.setFixedHeight(dp(28))
        btn_rename.setCursor(Qt.PointingHandCursor)
        btn_rename.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px;font-size:19px;padding:2px 10px}"
            "QPushButton:hover{border-color:%s;color:%s}"
            % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT, C_ACCENT)
        )
        btn_rename.clicked.connect(self._on_rename)
        btn_row.addWidget(btn_rename)

        btn_delete = QPushButton("\u5220\u9664\u8d26\u6237")
        btn_delete.setFixedHeight(dp(28))
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px;font-size:19px;padding:2px 10px}"
            "QPushButton:hover{color:%s;border-color:%s}"
            % (C_PANEL, C_SUBTEXT, C_BORDER, C_RED, C_RED)
        )
        btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(btn_delete)

        btn_reset = QPushButton("\u91cd\u7f6e\u6e05\u96f6")
        btn_reset.setFixedHeight(dp(28))
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:4px;font-size:19px;padding:2px 10px}"
            "QPushButton:hover{color:%s;border-color:%s}"
            % (C_PANEL, C_SUBTEXT, C_BORDER, C_RED, C_RED)
        )
        btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(btn_reset)

        btn_row.addStretch()
        lo.addLayout(btn_row)

        # ── New account ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("QFrame{border:none;border-top:1px solid %s}" % C_BORDER)
        sep2.setFixedHeight(2)
        lo.addWidget(sep2)

        create_label = QLabel("\u65b0\u5efa\u8d26\u6237")
        create_label.setStyleSheet(
            "color:%s;font-size:19px;background:transparent" % C_SUBTEXT
        )
        lo.addWidget(create_label)

        create_row = QHBoxLayout()
        create_row.setSpacing(6)

        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("\u8d26\u6237\u540d\u79f0")
        self._new_name.setStyleSheet(
            "QLineEdit{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
            "padding:4px 8px;font-size:19px}"
            "QLineEdit:focus{border-color:%s}" % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        create_row.addWidget(self._new_name, 1)

        self._new_capital = QDoubleSpinBox()
        self._new_capital.setRange(1000, 999999999)
        self._new_capital.setDecimals(0)
        self._new_capital.setValue(100000)
        self._new_capital.setStyleSheet(
            "QDoubleSpinBox{background:%s;color:%s;border:1px solid %s;border-radius:4px;"
            "padding:4px 6px;font-size:19px}"
            "QDoubleSpinBox:focus{border-color:%s}" % (C_PANEL, C_TEXT, C_BORDER, C_ACCENT)
        )
        create_row.addWidget(self._new_capital)

        btn_create = QPushButton("\u521b\u5efa")
        btn_create.setFixedHeight(dp(28))
        btn_create.setCursor(Qt.PointingHandCursor)
        btn_create.setStyleSheet(
            "QPushButton{background:%s;color:#0D1117;border:none;border-radius:4px;"
            "font-size:19px;font-weight:700;padding:2px 14px}"
            "QPushButton:hover{background:#E0B888}" % C_ACCENT
        )
        btn_create.clicked.connect(self._on_create)
        create_row.addWidget(btn_create)
        lo.addLayout(create_row)

    def set_account(self, account_id):
        self._account_id = account_id
        if not account_id:
            self._info_label.setText("请在左侧选择账户")
            self._curve.set_data([])
            return
        self._refresh()

    def _notify(self):
        """Tell the plugin the (selected) account changed so it can keep the
        left panel's account bar in sync."""
        if self.on_account_changed:
            self.on_account_changed(self._account_id)

    def _refresh(self):
        if not self._account_id:
            return
        acc = self._engine.get_account(self._account_id)
        if acc:
            summary = self._engine.get_summary(self._account_id)
            total = summary['total_assets'] if summary else 0
            pnl_pct = summary['total_profit_pct'] if summary else 0
            sign = "+" if pnl_pct >= 0 else ""
            self._info_label.setText(
                "\u5f53\u524d\u8d26\u6237: {name}\n"
                "\u521d\u59cb\u8d44\u91d1: \uffe5{capital:,.0f}    "
                "\u5f53\u524d\u603b\u8d44\u4ea7: \uffe5{total:,.2f}\n"
                "\u521b\u5efa\u65f6\u95f4: {created}\n"
                "\u7d2f\u8ba1\u6536\u76ca\u7387: {sign}{pct:.2f}%"
                .format(
                    name=acc.get('name', '?'),
                    capital=acc.get('initial_capital', 0),
                    total=total,
                    created=acc.get('created_at', '--')[:16],
                    sign=sign,
                    pct=pnl_pct,
                )
            )
            self._curve.load(self._engine, self._account_id)
        else:
            self._info_label.setText("\u8d26\u6237\u4e0d\u5b58\u5728")
            self._curve.set_data([])

    def _on_rename(self):
        if not self._account_id:
            return
        acc = self._engine.get_account(self._account_id)
        if not acc:
            return
        new_name, ok = QInputDialog.getText(
            self, "\u91cd\u547d\u540d\u8d26\u6237",
            "\u65b0\u540d\u79f0:", text=acc.get('name', '')
        )
        if ok and new_name.strip():
            try:
                conn = sqlite3.connect(self._engine.db_path)
                conn.execute("UPDATE accounts SET name=? WHERE id=?", (new_name.strip(), self._account_id))
                conn.commit()
                conn.close()
                self._refresh()
                self._notify()
            except Exception:
                pass

    def _on_delete(self):
        if not self._account_id:
            return
        acc = self._engine.get_account(self._account_id)
        if not acc:
            return
        ret = QMessageBox.question(
            self, "\u786e\u8ba4\u5220\u9664",
            "\u786e\u5b9a\u5220\u9664\u8d26\u6237 [%s] \u53ca\u6240\u6709\u5173\u8054\u6570\u636e\uff1f\n\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u9500\u3002" % acc.get('name', '?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._engine.delete_account(self._account_id)
            self._account_id = None
            self._info_label.setText("账户已删除")
            self._curve.set_data([])
            self._notify()

    def _on_reset(self):
        if not self._account_id:
            return
        ret = QMessageBox.question(
            self, "\u786e\u8ba4\u91cd\u7f6e",
            "\u786e\u5b9a\u91cd\u7f6e\u8d26\u6237\uff1f\u5c06\u6e05\u7a7a\u6240\u6709\u6301\u4ed3\u3001\u59d4\u6258\u548c\u6210\u4ea4\u8bb0\u5f55\uff0c\u6062\u590d\u521d\u59cb\u8d44\u91d1\u3002",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._engine.reset_account(self._account_id)
            self._refresh()
            self._notify()

    def _on_create(self):
        name = self._new_name.text().strip()
        if not name:
            return
        capital = self._new_capital.value()
        aid = self._engine.create_account(name, capital)
        self._account_id = aid
        self._new_name.clear()
        self._refresh()
        self._notify()
