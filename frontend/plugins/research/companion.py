# -*- coding: utf-8 -*-
"""研究/策略 —— 右侧伴侣: 组合纸面盘(重平衡净值 vs 等权买持) + 摘要 + 目标持仓."""
from __future__ import annotations

import sys
import os

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from frontend.platform.theme import (
    dp, dps, fs,
    C_BG, C_PANEL, C_RAISED, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_DOWN, C_UP, qss_card, style_h1, style_h2, style_label, style_caption, style_num,
)

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QPainter, QPen, QColor, QPainterPath, QFont


def _card(title: str) -> "_Stat":
    c = QFrame()
    c.setObjectName("card")
    c.setStyleSheet(qss_card(8))
    lo = QVBoxLayout(c)
    lo.setContentsMargins(dp(10), dp(8), dp(10), dp(8))
    lo.setSpacing(dp(2))
    t = QLabel(title)
    t.setStyleSheet(style_caption())
    lo.addWidget(t)
    v = QLabel("--")
    v.setStyleSheet(f"color:{C_TEXT};font-size:{fs(16)};font-weight:700;background:transparent;"
                    f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
    lo.addWidget(v)
    lo.addStretch()
    return _Stat(c, v)


class _Stat:
    def __init__(self, frame, value_label):
        self.frame = frame
        self.value = value_label

    def set(self, text, color=None):
        self.value.setText(text)
        if color:
            self.value.setStyleSheet(
                f"color:{color};font-size:{fs(16)};font-weight:700;background:transparent;"
                f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")


class _NavCurve(QWidget):
    """QPainter 双线净值曲线(重平衡 vs 买持)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nav = []
        self._bh = []
        self._dates = []
        self._bh_dates = []
        self.setMinimumHeight(dp(220))

    def set_data(self, dates, nav, bh_dates, bh_nav):
        # 归一化成"倍数"(各序列自身起点=1.0) → 净值(绝对值~1M)与买持(价格比~1.0)同轴可比
        def _idx(vals):
            vals = [float(x) for x in vals or []]
            base = vals[0] if vals else 1.0
            return [v / base for v in vals] if base else vals
        self._dates = dates or []
        self._nav = _idx(nav)
        self._bh_dates = bh_dates or []
        self._bh = _idx(bh_nav)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(C_PANEL))
        # padding
        pad_l, pad_r, pad_t, pad_b = dp(46), dp(12), dp(14), dp(22)
        iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
        if iw <= 0 or ih <= 0:
            p.end()
            return
        # baseline
        p.setPen(QPen(QColor(C_BORDER_SOFT), 1))
        p.drawLine(pad_l, pad_t + ih, pad_l + iw, pad_t + ih)
        # axis label (value / percent)
        allv = [float(x) for x in self._nav] + [float(x) for x in self._bh]
        if not allv:
            p.setPen(QColor(C_FAINT))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "运行研究后显示纸面盘")
            p.end()
            return
        lo, hi = min(allv), max(allv)
        if hi - lo < 1e-9:
            hi = lo + 1.0
        def _y(v):
            return pad_t + ih - (float(v) - lo) / (hi - lo) * ih

        def _x(idx, series_len):
            if series_len <= 1:
                return pad_l + iw / 2
            return pad_l + iw * idx / (series_len - 1)

        # grid hints (min/max labels)
        p.setPen(QPen(QColor(C_BORDER_SOFT), 1, Qt.DashLine))
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(C_FAINT))
        p.drawText(QRectF(0, pad_t - dp(14), pad_l - dp(6), dp(14)), Qt.AlignRight | Qt.AlignVCenter, f"{hi:,.2f}")
        p.drawText(QRectF(0, pad_t + ih - dp(5), pad_l - dp(6), dp(14)), Qt.AlignRight | Qt.AlignVCenter, f"{lo:,.2f}")
        # buy-hold (subtext) first
        if len(self._bh) >= 2:
            path = QPainterPath(QPointF(_x(0, len(self._bh)), _y(self._bh[0])))
            for i in range(1, len(self._bh)):
                path.lineTo(QPointF(_x(i, len(self._bh)), _y(self._bh[i])))
            p.setPen(QPen(QColor(C_SUBTEXT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        # rebalancer (accent gold)
        if len(self._nav) >= 2:
            path = QPainterPath(QPointF(_x(0, len(self._nav)), _y(self._nav[0])))
            for i in range(1, len(self._nav)):
                path.lineTo(QPointF(_x(i, len(self._nav)), _y(self._nav[i])))
            p.setPen(QPen(QColor(C_ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            # end dot
            last = QPointF(pad_l + iw, _y(self._nav[-1]))
            p.setBrush(QColor(C_ACCENT))
            p.setPen(Qt.NoPen)
            p.drawEllipse(last, dp(3), dp(3))
        # legend
        p.setPen(QColor(C_ACCENT)); p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(pad_l, pad_t - dp(18), dp(90), dp(14)), "— 重平衡")
        p.setPen(QColor(C_SUBTEXT))
        p.drawText(QRectF(pad_l + dp(72), pad_t - dp(18), dp(90), dp(14)), "— 买持")
        p.end()


class ResearchCompanion(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap = None
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        lo.setSpacing(dp(8))

        t = QLabel("组合纸面盘")
        t.setStyleSheet(style_h1())
        lo.addWidget(t)
        cap = QLabel("重平衡器(接 portfolio_value_alloc) · 逐期调仓 · 净值 vs 等权买持")
        cap.setStyleSheet(style_caption())
        lo.addWidget(cap)

        # 摘要卡 (2x2 网格, 适配窄栏)
        sum_grid = QGridLayout()
        sum_grid.setSpacing(dp(8))
        self._c_nav = _card("期末净值")
        self._c_ret = _card("组合收益")
        self._c_reb = _card("调仓次数")
        self._c_turn = _card("平均换手")
        for i, c in enumerate((self._c_nav, self._c_ret, self._c_reb, self._c_turn)):
            c.frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            sum_grid.addWidget(c.frame, i // 2, i % 2)
        lo.addLayout(sum_grid)

        self._curve = _NavCurve()
        lo.addWidget(self._curve, 1)

        t2 = QLabel("当前调仓目标")
        t2.setStyleSheet(style_h2())
        lo.addWidget(t2)
        self._targets = QTableWidget(0, 2)
        self._targets.setStyleSheet(
            f"QTableWidget{{background:{C_BG};color:{C_TEXT};border:1px solid {C_BORDER_SOFT};"
            f"border-radius:{dps(6)};gridline-color:{C_BORDER_SOFT};font-size:{fs(11)};}}"
            f"QHeaderView::section{{background:{C_PANEL};color:{C_SUBTEXT};border:none;"
            f"border-bottom:1px solid {C_BORDER};padding:{dps(4)} {dps(8)};font-size:{fs(10)};}}")
        self._targets.setHorizontalHeaderLabels(["代码", "持仓"])
        self._targets.verticalHeader().setVisible(False)
        self._targets.horizontalHeader().setStretchLastSection(True)
        self._targets.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._targets.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._targets.setMaximumHeight(dp(200))
        lo.addWidget(self._targets)

    def set_snapshot(self, snap):
        self._snap = snap
        p = snap.get("paper", {}) or {}
        nav = p.get("nav", []) or []
        bh = p.get("buyhold_nav", []) or []
        if nav:
            nav0, navl = nav[0], nav[-1]
            ret = (navl / nav0 - 1.0) * 100 if nav0 else 0.0
            self._c_nav.set(f"{navl:,.0f}", C_TEXT)
            self._c_ret.set(f"{ret:+.2f}%", C_DOWN if ret < 0 else C_UP)
            self._c_reb.set(str(p.get("rebalances", 0)), C_TEXT)
            turn = p.get("turnover_avg", 0.0)
            self._c_turn.set(f"{turn:.1%}", C_TEXT)
        self._curve.set_data(p.get("dates") or [], nav, p.get("buyhold_dates") or [], bh)
        # 目标持仓
        fh = p.get("final_holdings", {}) or {}
        rows = sorted(fh.items(), key=lambda kv: -kv[1])[:20]
        self._targets.setRowCount(len(rows))
        for i, (code, qty) in enumerate(rows):
            for j, val in enumerate((code, str(qty))):
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setForeground(QColor(C_TEXT if j == 0 else C_SUBTEXT))
                self._targets.setItem(i, j, it)
        self._targets.resizeColumnsToContents()
