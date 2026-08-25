# -*- coding: utf-8 -*-
"""研究/策略面板 —— 后端研究能力的前端呈现(诊断+因子研究+多因子排名).

布局(暗色金调, 经 theme 缩放):
  ① 控制条: 持有期分段(5/10/20/40) + 运行研究按钮
  ② 市场环境: value_tilt / market_breadth / portfolio_value_alloc / 决策门 4 卡
  ③ 价值因子研究: BP/EP/ROE 截面 IC·ICIR·单调性·多空 3 卡
  ④ 多因子选股: composite z(BP)+z(REV20)-z(VOL20) 排名表(点行开K线)
右侧 companion 展示组合纸面盘净值曲线.
"""
from __future__ import annotations

import os
import sys

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend"))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from frontend.platform.theme import (
    dp, dps, fs,
    C_BG, C_PANEL, C_RAISED, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_ACCENT_HOVER, C_ACCENT_DIM, C_ON_ACCENT, C_UP, C_DOWN, C_INFO, C_WARN,
    qss_btn, qss_btn_accent, qss_table, qss_card, style_h1, style_h2, style_label,
    style_caption, style_num,
)
from frontend.platform.local_worker import LocalWorker

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
    QButtonGroup, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont


def _sec_title(text: str, hint: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style_h2())
    if hint:
        lbl.setToolTip(hint)
    return lbl


def _sec_caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style_caption())
    return lbl


class _StatCard(QFrame):
    """诊断卡: 标题(caption) + 主值(num) + 次值(caption)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(qss_card(8))
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(10), dp(8), dp(10), dp(8))
        lo.setSpacing(dp(2))
        t = QLabel(title)
        t.setStyleSheet(style_caption())
        lo.addWidget(t)
        self._value = QLabel("--")
        self._value.setStyleSheet(f"color:{C_TEXT};font-size:{fs(16)};font-weight:700;background:transparent;"
                                  f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
        lo.addWidget(self._value)
        self._sub = QLabel("")
        self._sub.setStyleSheet(style_caption())
        self._sub.setWordWrap(True)
        lo.addWidget(self._sub)
        lo.addStretch()

    def set(self, value: str, sub: str = "", color: str = None, value_size: int = 16):
        self._value.setText(value)
        self._value.setStyleSheet(
            f"color:{color or C_TEXT};font-size:{fs(value_size)};font-weight:700;background:transparent;"
            f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
        self._sub.setText(sub)


class _SecCard(QFrame):
    """因子研究卡: 标题 + IC/ICIR/单调/多空 网格."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(qss_card(8))
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(10), dp(8), dp(10), dp(8))
        lo.setSpacing(dp(4))
        head = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(f"color:{C_ACCENT};font-size:{fs(13)};font-weight:700;background:transparent;"
                        f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
        head.addWidget(t)
        head.addStretch()
        self._conf = QLabel("")
        self._conf.setStyleSheet(style_caption())
        head.addWidget(self._conf)
        lo.addLayout(head)
        self._grid = QLabel("--")
        self._grid.setStyleSheet(f"color:{C_SUBTEXT};font-size:{fs(11)};background:transparent;"
                                 f"font-family:'Consolas','Microsoft YaHei';")
        lo.addWidget(self._grid)
        lo.addStretch()

    def set(self, v: dict):
        if not v or "error" in v:
            self._conf.setText("数据不可用")
            self._grid.setText(str(v.get("error", "")) if v else "")
            return
        self._grid.setText(
            f"IC  {v.get('ic', 0):+.4f}\nICIR {v.get('icir', 0):+.3f}\n"
            f"IC正率 {v.get('ic_positive', 0):.0%}   单调 {v.get('monotonicity', 0):+.2f}\n"
            f"多空(净) {v.get('long_short_net', 0):+.2%}   覆盖 {v.get('coverage', 0):.0%}")


def _btn(text: str, accent: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(qss_btn_accent() if accent else qss_btn())
    return b


class ResearchPanel(QWidget):
    snapshot_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = None
        self.on_open_kline = None
        self.on_status = None
        self._snap = None
        self._hp = 20
        self._workers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"QScrollArea{{background:{C_BG};border:none}}")
        body = QWidget()
        body.setStyleSheet(f"background:{C_BG}")
        lo = QVBoxLayout(body)
        lo.setContentsMargins(dp(12), dp(12), dp(12), dp(12))
        lo.setSpacing(dp(10))

        # 标题 + 控制条
        title = QLabel("量化研究")
        title.setStyleSheet(style_h1())
        lo.addWidget(title)
        cap = QLabel("LLM-in-the-loop · 价值因子 · 多因子分层 · 组合纸面盘")
        cap.setStyleSheet(style_caption())
        lo.addWidget(cap)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addWidget(QLabel("持有期"))
        self._segs = {}
        group = QButtonGroup(self)
        for hp in (5, 10, 20, 40):
            b = QPushButton(f"{hp}日")
            b.setCheckable(True)
            b.setFixedHeight(dp(26))
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._seg_style())
            group.addButton(b)
            self._segs[hp] = b
            ctrl.addWidget(b)
            if hp == 20:
                b.setChecked(True)
        group.buttonClicked.connect(self._on_hp)
        ctrl.addStretch()
        self._btn_run = _btn("运行研究", accent=True)
        self._btn_run.setFixedHeight(dp(30))
        self._btn_run.clicked.connect(self.load)
        ctrl.addWidget(self._btn_run)
        lo.addLayout(ctrl)

        # 研究代理 · 市场环境
        lo.addWidget(_sec_title("市场环境  ·  研究代理信号"))
        env_row = QHBoxLayout()
        env_row.setSpacing(dp(8))
        self._card_mkt = _StatCard("市场状态")
        self._card_breadth = _StatCard("市场宽度")
        self._card_wvalue = _StatCard("组合价值权重")
        self._card_gate = _StatCard("决策门")
        for c in (self._card_mkt, self._card_breadth, self._card_wvalue, self._card_gate):
            c.setMinimumWidth(dp(140))
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            env_row.addWidget(c)
        lo.addLayout(env_row)

        # 价值因子研究
        lo.addWidget(_sec_title("价值因子研究  ·  截面 IC / ICIR"))
        study_row = QHBoxLayout()
        study_row.setSpacing(dp(8))
        self._card_bp = _SecCard("BP  账面市值比")
        self._card_ep = _SecCard("EP  盈利收益率")
        self._card_roe = _SecCard("ROE  净资产收益率")
        for c in (self._card_bp, self._card_ep, self._card_roe):
            c.setMinimumWidth(dp(170))
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            study_row.addWidget(c)
        lo.addLayout(study_row)

        # 多因子选股
        lo.addWidget(_sec_title("多因子选股  ·  z(BP)+z(REV20)−z(VOL20) 综合分"))
        self._rank_table = QTableWidget()
        self._rank_table.setStyleSheet(qss_table())
        self._rank_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rank_table.verticalHeader().setVisible(False)
        self._rank_table.horizontalHeader().setStretchLastSection(True)
        self._rank_table.cellClicked.connect(self._on_row_click)
        self._rank_table.setMinimumHeight(dp(300))
        lo.addWidget(self._rank_table)

        lo.addWidget(_sec_caption("研究池 = 跨板块均衡池(≈287只, 板块中性化)。权威口径(全市场/2500池)见 backend verify_*.py。"))
        lo.addStretch()

        self._scroll.setWidget(body)
        outer.addWidget(self._scroll)

        self._set_loading()

    def _seg_style(self) -> str:
        return (f"QPushButton{{background:{C_PANEL};color:{C_ACCENT};border:1px solid {C_BORDER};"
                f"font-size:{fs(12)};font-weight:600;padding:{dps(3)} {dps(12)};}}"
                f"QPushButton:hover{{border-color:{C_ACCENT};}}"
                f"QPushButton:checked{{background:{C_ACCENT};color:{C_ON_ACCENT};border-color:{C_ACCENT};}}")

    def _on_hp(self, btn):
        for hp, b in self._segs.items():
            if b is btn:
                self._hp = hp

    def set_kline_db(self, path):
        self.db_path = path

    def _set_loading(self):
        self._card_mkt.set("--", "加载中...")
        self._card_breadth.set("--", "加载中...")
        self._card_wvalue.set("--", "加载中...")
        self._card_gate.set("--", "加载中...")
        for c in (self._card_bp, self._card_ep, self._card_roe):
            c.set({})
        self._rank_table.setRowCount(0)
        self._rank_table.setColumnCount(0)

    def load(self):
        if self.on_status:
            self.on_status(f"运行研究 (持有期 {self._hp}日)...")
        self._set_loading()
        w = LocalWorker(self._work, "research", args=[self._hp])
        w.result.connect(self._on_data)
        self._workers.append(w)
        w.start()

    def _work(self, hp):
        from .worker import build_snapshot
        return build_snapshot(hp=hp)

    def _on_data(self, tag, data):
        # LocalWorker emits {"code":0,"data":snap} or {"code":-1,"error":...}
        if not isinstance(data, dict):
            return
        if data.get("code") == -1:
            if self.on_status:
                self.on_status("研究运行失败: %s" % data.get("error"))
            return
        snap = data.get("data") or data
        if "signals" not in snap:
            if self.on_status:
                self.on_status("研究无数据: %s" % snap.get("frames_error"))
            return
        self._snap = snap
        self._render(snap)
        self.snapshot_ready.emit(snap)
        if self.on_status:
            self.on_status(f"研究完成 持有期{snap.get('hp')}日 池{len(snap.get('codes') or [])}只")

    def _render(self, snap):
        sig = snap.get("signals", {})
        vt = sig.get("value_tilt", {}) or {}
        br = sig.get("breadth", {}) or {}
        al = sig.get("alloc", {}) or {}
        hr = sig.get("hard_rule")

        # 市场状态卡
        vt_tilt = vt.get("value_tilt", "neutral")
        vt_color = {"value_favorable": C_DOWN, "value_headwind": C_UP}.get(vt_tilt, C_SUBTEXT)
        self._card_mkt.set(
            {"state": "weak", "value_tilt": "value_favorable"}.get(vt_tilt, vt_tilt.replace("value_", "value_")),
            sub=f"{vt.get('state', '')} · 回撤 {vt.get('drawdown', 0):.1%}" if isinstance(vt.get('drawdown'), float)
                else str(vt.get("reason", ""))[:60],
            color=vt_color, value_size=14)

        # 市场宽度卡
        b = br.get("breadth", 0.5)
        b_tilt = br.get("tilt", "value_neutral")
        b_color = {"value_favorable": C_DOWN, "value_headwind": C_UP}.get(b_tilt, C_SUBTEXT)
        self._card_breadth.set(f"{b:.0%}", sub=f"破年线占比 · {b_tilt.replace('value_','')}", color=b_color)

        # 组合价值权重卡
        wv = al.get("w_value", 1.0)
        wlabel = al.get("tilt_label", "")
        wcolor = {"value_favorable": C_DOWN, "value_headwind": C_UP}.get(wlabel, C_SUBTEXT)
        self._card_wvalue.set(f"×{wv:.1f}", sub=f"{wlabel.replace('value_','')} · 三路信号多数决", color=wcolor)

        # 决策门卡
        if hr and isinstance(hr, dict) and "error" not in hr:
            act = hr.get("action", "hold")
            gate_color = C_UP if act == "hold" else C_DOWN
            self._card_gate.set(act.upper(), sub=str(hr.get("reason", ""))[:70], color=gate_color)
        else:
            self._card_gate.set("--", "无价值硬裁决" if not (hr and hr.get("error")) else "判断不可用")

        # 价值因子研究
        st = snap.get("study", {})
        self._card_bp.set(st.get("BP", {}))
        self._card_ep.set(st.get("EP", {}))
        self._card_roe.set(st.get("ROE", {}))

        # 多因子排名
        rk = snap.get("ranking", []) or []
        cols = ["代码", "现价", "涨跌%", "综合分"]
        self._rank_table.setRowCount(len(rk))
        self._rank_table.setColumnCount(len(cols))
        self._rank_table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rk):
            items = [
                (str(r.get("code", "")), C_TEXT),
                ("{:.2f}".format(r.get("price", 0)), C_SUBTEXT),
                (("{:+.2f}".format(r.get("chg", 0))), C_DOWN if r.get("chg", 0) < 0 else C_UP),
                ("{:.3f}".format(r.get("comp", 0)), C_ACCENT),
            ]
            for j, (text, color) in enumerate(items):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setForeground(QColor(color))
                if j == 3:
                    it.setFont(QFont("", -1, QFont.Bold))
                self._rank_table.setItem(i, j, it)
        self._rank_table.resizeColumnsToContents()

    def _on_row_click(self, row, col):
        if not self._snap or row >= len(self._snap.get("ranking", [])):
            return
        code = self._snap["ranking"][row].get("code", "")
        if code and self.on_open_kline:
            self.on_open_kline(code, "")
