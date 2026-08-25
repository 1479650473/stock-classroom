# -*- coding: utf-8 -*-
"""Trade companion — profit curve + account management (premium 高级感)."""

import os, sys, sqlite3
from datetime import datetime
from collections import defaultdict

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from trade_engine.engine import TradeEngine

from frontend.platform.theme import (
    dp,
    C_TEXT, C_SUBTEXT, C_UP, C_DOWN,
    qss_btn, qss_btn_accent, qss_input, qss_spinbox,
)
from frontend.platform.premium import (
    PAL, card_qss, value_ss, label_ss, pill_ss, SectionTitle, CountUpLabel, well,
)

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDoubleSpinBox, QFrame, QInputDialog, QMessageBox, QGridLayout,
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QPainterPath, QLinearGradient

from frontend.platform.local_worker import LocalWorker
from frontend.plugins.research.worker import build_paper_only


class ProfitCurve(QWidget):
    """QPainter line chart — account total-assets trajectory (premium)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(dp(180))
        self._points = []
        self._overlay_points = []
        self._engine = None
        self._account_id = None
        self._hover_idx = -1

    def set_data(self, points):
        self._points = points if points else []
        self._hover_idx = -1
        self.update()

    def set_overlay(self, points):
        """叠加第二根净值曲线(组合纸面盘). points=[(date,value),...]; 传空清除."""
        self._overlay_points = points if points else []
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

    # ── chart scaffolding ──
    def _frame(self, w, h):
        pad_l, pad_r, pad_t, pad_b = dp(58), dp(14), dp(12), dp(24)
        return pad_l, pad_r, pad_t, pad_b, w - pad_l - pad_r, h - pad_t - pad_b

    def _fill_chart_bg(self, p, w, h):
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor(PAL["c_top"]))
        g.setColorAt(1.0, QColor(PAL["c_bot"]))
        p.fillRect(0, 0, w, h, g)

    def _grid(self, p, w, h, pad_l, pad_t, iw, ih, v_min, v_max, font_val):
        p.setPen(QPen(QColor(PAL["grid"]), 1, Qt.DotLine))
        n_grid = 5
        for j in range(n_grid + 1):
            y = pad_t + (j / n_grid) * ih
            p.drawLine(int(pad_l), int(y), int(pad_l + iw), int(y))
            val = v_max - (j / n_grid) * (v_max - v_min)
            p.setFont(font_val)
            p.setPen(QColor(PAL["faint"]))
            label = "{:,.0f}".format(val) if abs(val) >= 1000 else "{:.0f}".format(val)
            p.drawText(QRectF(0, y - 8, pad_l - 6, 16), Qt.AlignRight | Qt.AlignVCenter, label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 60 or h < 60:
            painter.end()
            return
        self._fill_chart_bg(painter, w, h)

        points = self._points
        if not points and not self._overlay_points:
            painter.setPen(QColor(PAL["faint"]))
            f = QFont("Segoe UI", 11)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无收益数据")
            painter.end()
            return

        if self._overlay_points:
            self._paint_overlay(painter, w, h)
            painter.end()
            return

        font_val = QFont("Segoe UI", 8)
        font_date = QFont("Segoe UI", 7)
        pad_l, pad_r, pad_t, pad_b, iw, ih = self._frame(w, h)
        if iw < 10 or ih < 10:
            painter.end()
            return

        def to_x(i):
            return pad_l + (i / max(len(points) - 1, 1)) * iw

        vals = [p[1] for p in points]
        v_min, v_max = min(vals), max(vals)
        if v_max == v_min:
            v_max = v_min + 1
        pad_ = (v_max - v_min) * 0.1 or 1
        v_min -= pad_
        v_max += pad_

        def to_y(v):
            return pad_t + (1 - (v - v_min) / (v_max - v_min)) * ih

        up = vals[-1] >= vals[0]
        c = QColor(C_UP) if up else QColor(C_DOWN)

        self._grid(painter, w, h, pad_l, pad_t, iw, ih, v_min, v_max, font_val)
        # baseline
        painter.setPen(QPen(QColor(PAL["axis"]), 1))
        painter.drawLine(int(pad_l), int(pad_t + ih), int(pad_l + iw), int(pad_t + ih))

        # filled area under curve (gradient up/down → transparent)
        grad_path = QPainterPath(QPointF(to_x(0), pad_t + ih))
        for i, (_, v, _) in enumerate(points):
            grad_path.lineTo(QPointF(to_x(i), to_y(v)))
        grad_path.lineTo(QPointF(to_x(len(points) - 1), pad_t + ih))
        grad_path.closeSubpath()
        g = QLinearGradient(0, pad_t, 0, pad_t + ih)
        g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 60))
        g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(g)
        painter.drawPath(grad_path)

        # curve line
        painter.setPen(QPen(c, 2))
        painter.setBrush(Qt.NoBrush)
        for i in range(1, len(points)):
            painter.drawLine(int(to_x(i - 1)), int(to_y(points[i - 1][1])),
                             int(to_x(i)), int(to_y(points[i][1])))
        # end dot
        ex, ey = to_x(len(points) - 1), to_y(points[-1][1])
        painter.setBrush(QColor(PAL["accent"]))
        painter.setPen(QPen(QColor("#FFFFFF"), 1))
        painter.drawEllipse(QRectF(ex - 3, ey - 3, 6, 6))

        # x labels
        painter.setPen(QColor(PAL["faint"]))
        painter.setFont(font_date)
        n_labels = min(len(points), 8)
        step = max(len(points) // max(n_labels, 1), 1)
        for i in range(0, len(points), step):
            lbl = points[i][0][4:] if len(points[i][0]) > 6 else points[i][0]
            painter.drawText(QRectF(to_x(i) - 30, pad_t + ih + 2, 60, 16), Qt.AlignCenter, lbl)

    def _paint_overlay(self, painter, w, h):
        """双曲线: 账户收益指数(主, 上/下色+渐变面积) vs 组合纸面盘(叠线, 金)."""
        def idx(points):
            if not points:
                return []
            base = points[0][1] or 1.0
            return [(p[0], p[1] / base * 100.0) for p in points]

        main = idx(self._points)
        over = idx(self._overlay_points)
        allv = [v for _, v in main] + [v for _, v in over]
        if not allv:
            return
        v_min, v_max = min(allv), max(allv)
        if v_max == v_min:
            v_max = v_min + 1
        pad_ = (v_max - v_min) * 0.1 or 1
        v_min -= pad_
        v_max += pad_

        font_val = QFont("Segoe UI", 8)
        font_leg = QFont("Segoe UI", 8)
        font_date = QFont("Segoe UI", 7)
        pad_l, pad_r, pad_t, pad_b, iw, ih = self._frame(w, h)
        if iw < 10 or ih < 10:
            return

        def to_x(i, n):
            return pad_l + (i / max(n - 1, 1)) * iw

        def to_y(v):
            return pad_t + (1 - (v - v_min) / (v_max - v_min)) * ih

        owner = self._points
        up = owner and owner[-1][1] >= owner[0][1]
        main_color = QColor(C_UP) if up else QColor(C_DOWN)
        over_color = QColor(PAL["accent"])

        self._grid(painter, w, h, pad_l, pad_t, iw, ih, v_min, v_max, font_val)
        painter.setPen(QPen(QColor(PAL["axis"]), 1))
        painter.drawLine(int(pad_l), int(pad_t + ih), int(pad_l + iw), int(pad_t + ih))

        # main (account) — area + line
        if len(main) >= 2:
            grad = QPainterPath(QPointF(to_x(0, len(main)), pad_t + ih))
            for i in range(len(main)):
                grad.lineTo(QPointF(to_x(i, len(main)), to_y(main[i][1])))
            grad.lineTo(QPointF(to_x(len(main) - 1, len(main)), pad_t + ih))
            grad.closeSubpath()
            g = QLinearGradient(0, pad_t, 0, pad_t + ih)
            g.setColorAt(0.0, QColor(main_color.red(), main_color.green(), main_color.blue(), 52))
            g.setColorAt(1.0, QColor(main_color.red(), main_color.green(), main_color.blue(), 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(g)
            painter.drawPath(grad)
            painter.setPen(QPen(main_color, 2))
            painter.setBrush(Qt.NoBrush)
            for i in range(1, len(main)):
                painter.drawLine(int(to_x(i - 1, len(main))), int(to_y(main[i - 1][1])),
                                 int(to_x(i, len(main))), int(to_y(main[i][1])))
            painter.setBrush(QColor(PAL["accent"]))
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            x, y = to_x(len(main) - 1, len(main)), to_y(main[-1][1])
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))

        # overlay (paper) — gold line only
        if len(over) >= 2:
            painter.setPen(QPen(over_color, 2))
            painter.setBrush(Qt.NoBrush)
            for i in range(1, len(over)):
                painter.drawLine(int(to_x(i - 1, len(over))), int(to_y(over[i - 1][1])),
                                 int(to_x(i, len(over))), int(to_y(over[i][1])))
            painter.setBrush(over_color)
            painter.setPen(Qt.NoPen)
            x, y = to_x(len(over) - 1, len(over)), to_y(over[-1][1])
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))

        # legend
        painter.setFont(font_leg)
        painter.setPen(main_color)
        painter.drawText(QRectF(pad_l, pad_t - 14, 70, 14), Qt.AlignLeft, "— 账户")
        painter.setPen(over_color)
        painter.drawText(QRectF(pad_l + 68, pad_t - 14, 90, 14), Qt.AlignLeft, "— 纸面盘")

        # x axis
        xseries = over if len(over) >= len(main) else main
        if len(xseries) >= 2:
            painter.setPen(QColor(PAL["faint"]))
            painter.setFont(font_date)
            n_labels = min(len(xseries), 6)
            step = max(len(xseries) // max(n_labels, 1), 1)
            for i in range(0, len(xseries), step):
                lbl = xseries[i][0][4:] if len(xseries[i][0]) > 6 else xseries[i][0]
                painter.drawText(QRectF(to_x(i, len(xseries)) - 30, pad_t + ih + 2, 60, 16), Qt.AlignCenter, lbl)

    def mouseMoveEvent(self, event):
        if not self._points:
            return
        pad_l, pad_r, pad_t, pad_b, iw, ih = self._frame(self.width(), self.height())
        if iw < 10 or len(self._points) < 2:
            return
        idx = round((event.x() - pad_l) / iw * (len(self._points) - 1))
        idx = max(0, min(idx, len(self._points) - 1))
        self._hover_idx = idx
        p = self._points[idx]
        self.setToolTip("{}\n¥ {:,.2f}".format(p[0], p[1]))


def _pill(pct):
    """Return (text, color) for a pct value pill (A股红涨绿跌)."""
    color = C_UP if pct >= 0 else C_DOWN
    sign = "+" if pct >= 0 else ""
    return "%s%.2f%%" % (sign, pct), color


class TradeCompanion(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:%s" % PAL["bg"])
        self._engine = TradeEngine()
        self._account_id = None
        self.on_account_changed = None
        self._build_ui()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(12), dp(12), dp(12), dp(12))
        lo.setSpacing(dp(10))

        # ── Profit curve ──
        lo.addWidget(SectionTitle("账户收益曲线"))
        self._curve = ProfitCurve()
        lo.addWidget(self._curve, 1)
        # 后台计算组合纸面盘一次(慢), 完成后叠加到收益曲线
        self._start_paper_worker()

        # ── Account management card ──
        mgmt = well("mem_card")
        ml = QVBoxLayout(mgmt)
        ml.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        ml.setSpacing(dp(7))

        self._name_label = QLabel("请选择账户")
        self._name_label.setStyleSheet(
            value_ss(color=PAL["text"], size=15))
        self._name_label.setWordWrap(True)
        ml.addWidget(self._name_label)

        cap_cap = QHBoxLayout()
        cap_cap.setSpacing(dp(10))
        self._capital_label = QLabel("初始资金: --")
        self._capital_label.setStyleSheet(label_ss(size=10))
        cap_cap.addWidget(self._capital_label)
        cap_cap.addStretch()
        self._ret_pill = QLabel("--")
        self._ret_pill.setStyleSheet(pill_ss(C_SUBTEXT))
        cap_cap.addWidget(self._ret_pill)
        ml.addLayout(cap_cap)

        total_lbl = QLabel("当前总资产")
        total_lbl.setStyleSheet(label_ss(size=9))
        ml.addWidget(total_lbl)
        self._total_label = CountUpLabel(fmt=lambda v: "¥ {:,.2f}".format(v), duration=900)
        ml.addWidget(self._total_label)

        # action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(dp(7))
        btn_rename = QPushButton("重命名")
        btn_rename.setCursor(Qt.PointingHandCursor)
        btn_rename.setStyleSheet(qss_btn())
        btn_rename.clicked.connect(self._on_rename)
        btn_row.addWidget(btn_rename)
        btn_reset = QPushButton("重置清零")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.setStyleSheet(qss_btn())
        btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(btn_reset)
        btn_delete = QPushButton("删除账户")
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setStyleSheet(
            qss_btn().replace(C_TEXT, C_UP).replace("border-top-color:#D4A574",
                                                   "border-top-color:" + C_UP))
        btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()
        ml.addLayout(btn_row)
        lo.addWidget(mgmt)

        # ── New account card ──
        nw = well("mem_card2")
        nl2 = QVBoxLayout(nw)
        nl2.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        nl2.setSpacing(dp(6))
        nl2.addWidget(SectionTitle("新建账户", size=10))
        create_row = QHBoxLayout()
        create_row.setSpacing(dp(7))
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("账户名称")
        self._new_name.setStyleSheet(qss_input())
        create_row.addWidget(self._new_name, 1)
        self._new_capital = QDoubleSpinBox()
        self._new_capital.setRange(1000, 999999999)
        self._new_capital.setDecimals(0)
        self._new_capital.setValue(100000)
        self._new_capital.setStyleSheet(qss_spinbox())
        create_row.addWidget(self._new_capital)
        btn_create = QPushButton("创建")
        btn_create.setCursor(Qt.PointingHandCursor)
        btn_create.setStyleSheet(qss_btn_accent())
        btn_create.clicked.connect(self._on_create)
        create_row.addWidget(btn_create)
        nl2.addLayout(create_row)
        lo.addWidget(nw)

        lo.addStretch()

    def _start_paper_worker(self):
        """后台计算一次组合纸面盘(慢), 完成叠加到收益曲线; 已算过则跳过."""
        if getattr(self, "_paper_done", False):
            return
        if getattr(self, "_paper_worker", None) is not None and self._paper_worker.isRunning():
            return

        def work():
            try:
                r = build_paper_only(hp=20)
                return {"code": 0, "data": r}
            except Exception as e:
                return {"code": -1, "error": str(e)}

        self._paper_worker = LocalWorker(work, "paper")
        self._paper_worker.result.connect(self._on_paper)
        self._paper_worker.start()

    def _on_paper(self, tag, data):
        if not isinstance(data, dict) or data.get("code") == -1:
            self._paper_done = True
            return
        r = data.get("data") or {}
        paper = r.get("paper") or {}
        nav = paper.get("nav") or []
        dates = paper.get("dates") or []
        if not nav or not dates:
            self._paper_done = True
            return
        pts = [(dates[i], nav[i]) for i in range(len(nav))]
        self._curve.set_overlay(pts)
        self._paper_done = True

    def set_account(self, account_id):
        self._account_id = account_id
        if not account_id:
            self._name_label.setText("请选择账户")
            self._capital_label.setText("初始资金: --")
            self._ret_pill.setText("--")
            self._ret_pill.setStyleSheet(pill_ss(C_SUBTEXT))
            self._total_label.set_immediate(0, lambda v: "¥ {:,.2f}".format(v))
            self._curve.set_data([])
            return
        self._refresh()

    def _notify(self):
        if self.on_account_changed:
            self.on_account_changed(self._account_id)

    def _set_pill(self, pct):
        txt, color = _pill(pct) if pct is not None else ("--", C_SUBTEXT)
        self._ret_pill.setText(txt)
        self._ret_pill.setStyleSheet(pill_ss(color))

    def _refresh(self):
        if not self._account_id:
            return
        acc = self._engine.get_account(self._account_id)
        if not acc:
            self._name_label.setText("账户不存在")
            self._curve.set_data([])
            return
        summary = self._engine.get_summary(self._account_id)
        total = summary['total_assets'] if summary else 0
        pnl_pct = summary['total_profit_pct'] if summary else 0
        self._name_label.setText(str(acc.get('name', '?')))
        self._capital_label.setText("初始资金: ¥ {:,.0f}".format(acc.get('initial_capital', 0)))
        self._set_pill(pnl_pct)
        self._total_label.animate_to(total, lambda v: "¥ {:,.2f}".format(v))
        self._curve.load(self._engine, self._account_id)

    def _on_rename(self):
        if not self._account_id:
            return
        acc = self._engine.get_account(self._account_id)
        if not acc:
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名账户", "新名称:", text=acc.get('name', ''))
        if ok and new_name.strip():
            try:
                conn = sqlite3.connect(self._engine.db_path)
                conn.execute("UPDATE accounts SET name=? WHERE id=?",
                             (new_name.strip(), self._account_id))
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
            self, "确认删除",
            "确定删除账户 [%s] 及所有关联数据？\n此操作不可撤销。" % acc.get('name', '?'),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._engine.delete_account(self._account_id)
            self._account_id = None
            self._name_label.setText("账户已删除")
            self._capital_label.setText("初始资金: --")
            self._ret_pill.setText("--")
            self._ret_pill.setStyleSheet(pill_ss(C_SUBTEXT))
            self._total_label.set_immediate(0, lambda v: "¥ {:,.2f}".format(v))
            self._curve.set_data([])
            self._notify()

    def _on_reset(self):
        if not self._account_id:
            return
        ret = QMessageBox.question(
            self, "确认重置",
            "确定重置账户？将清空所有持仓、委托和成交记录，恢复初始资金。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
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
