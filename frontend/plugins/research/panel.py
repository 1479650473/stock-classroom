# -*- coding: utf-8 -*-
"""研究/策略面板 —— 后端研究能力的前端呈现(诊断+因子研究+多因子排名).

布局(暗色高质感, 克制配色, 真实景深斜面, 精致排版):
  ① 控制条: 持有期分段(5/10/20/40) + 运行研究按钮
  ② 市场环境: value_tilt / market_breadth / portfolio_value_alloc / 决策门 2x2 高级卡
  ③ 价值因子研究: BP/EP/ROE 截面 IC·ICIR·单调·多空 (纵向堆叠高级卡)
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
    dp, dps, fs, tr, style_title,
    C_BG, C_PANEL, C_RAISED, C_BORDER, C_BORDER_SOFT, C_TEXT, C_SUBTEXT, C_FAINT,
    C_ACCENT, C_ACCENT_HOVER, C_ACCENT_DIM, C_ON_ACCENT, C_UP, C_DOWN, C_INFO, C_WARN,
    C_GOLD, C_GOLD_HOVER,
    qss_btn, qss_btn_accent, qss_table, qss_card, qss_combo, style_h1, style_h2, style_label,
    style_caption, style_num,
)
from frontend.platform.local_worker import LocalWorker
from frontend.platform.premium import (
    BreadthGauge, card_qss as _card_qss, PAL as _PAL, well, MachinedWell,
)
from frontend.platform.premium import value_ss as _value_ss, label_ss as _label_ss, pill_ss as _pill_ss
from .worker import STRATEGY_LABELS

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QScrollArea,
    QButtonGroup, QSizePolicy, QComboBox, QDateEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QDate
from PyQt5.QtGui import QColor, QFont


def _sec_title(text: str, hint: str = "") -> QWidget:
    """信字体小节标题: 字距拉开小号 + 金色短杆(克制)."""
    w = QWidget()
    lo = QHBoxLayout(w)
    lo.setContentsMargins(0, 0, 0, 0)
    lo.setSpacing(dp(6))
    bar = QFrame()
    bar.setFixedSize(dp(3), dp(14))
    bar.setStyleSheet(f"background:{_PAL['gold']};border-radius:1px;")
    lo.addWidget(bar)
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{_PAL['text']};font-size:{fs(tr(12))};font-weight:600;"
        f"letter-spacing:{dp(1)}px;background:transparent;")
    lo.addWidget(lbl)
    lo.addStretch()
    if hint:
        w.setToolTip(hint)
    return w


def _sec_caption(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{_PAL['faint']};font-size:{fs(10)};letter-spacing:{dp(0.5)}px;"
        f"background:transparent;")
    return lbl


def _pill(text: str, color: str) -> QLabel:
    """状态药丸(tinted bg + border), 用于 value_headwind / 决策门 等状态值."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background:rgba({color},0.13);color:{color};"
        f"border:1px solid rgba({color},0.42);border-radius:{dps(5)};"
        f"padding:{dps(2)} {dps(8)};font-size:{fs(12)};font-weight:600;"
        f"letter-spacing:{dp(0.5)}px;background:transparent;")
    lbl.setWordWrap(True)
    return lbl


class _StatCard(MachinedWell):
    """高级诊断卡: 字距标题 + 主值(药丸状态/轻量数字) + 副注."""

    def __init__(self, title: str, parent=None):
        super().__init__("rstat", 10, parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(12), dp(10), dp(12), dp(10))
        lo.setSpacing(dp(6))
        t = QLabel(title)
        t.setStyleSheet(
            f"color:{_PAL['sub']};font-size:{fs(tr(11))};font-weight:500;"
            f"letter-spacing:{dp(2)}px;background:transparent;")
        lo.addWidget(t)
        self._value = QLabel("--")
        self._value.setStyleSheet(
            f"color:{_PAL['text']};font-size:{fs(tr(18))};font-weight:300;background:transparent;"
            f"font-family:'Segoe UI Light','Microsoft YaHei UI Light','Microsoft YaHei',sans-serif;"
            f"letter-spacing:{dp(0.5)}px;")
        lo.addWidget(self._value)
        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"color:{_PAL['faint']};font-size:{fs(tr(11))};background:transparent;")
        self._sub.setWordWrap(True)
        lo.addWidget(self._sub)
        lo.addStretch()

    def set(self, value, sub: str = "", color: str = None, value_size: int = 17, pill: bool = False):
        self._sub.setText(sub)
        if pill:
            # 状态 → 药丸
            self._value.setStyleSheet(
                f"background:rgba({color},0.12);color:{color};"
                f"border:1px solid rgba({color},0.35);border-radius:{dps(5)};"
                f"padding:{dps(2)} {dps(9)};font-size:{fs(value_size)};font-weight:600;"
                f"letter-spacing:{dp(0.5)}px;background:transparent;"
                f"font-family:'Segoe UI','Microsoft YaHei';")
            self._value.setText(value)
        else:
            self._value.setStyleSheet(
                f"color:{color or _PAL['text']};font-size:{fs(value_size)};font-weight:300;"
                f"background:transparent;letter-spacing:{dp(0.5)}px;"
                f"font-family:'Segoe UI Light','Microsoft YaHei UI Light','Microsoft YaHei',sans-serif;")
            self._value.setText(str(value))


class _SecCard(MachinedWell):
    """高级因子研究卡: 标题 + 指标网格(轻量数字 + 字距标签)."""

    def __init__(self, title: str, parent=None):
        super().__init__("rstat", 10, parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(dp(12), dp(10), dp(12), dp(10))
        lo.setSpacing(dp(6))
        head = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(
            f"color:{_PAL['gold']};font-size:{fs(tr(12))};font-weight:600;background:transparent;"
            f"letter-spacing:{dp(0.5)}px;font-family:'Segoe UI','Microsoft YaHei';")
        head.addWidget(t)
        head.addStretch()
        self._conf = QLabel("")
        self._conf.setStyleSheet(style_caption())
        head.addWidget(self._conf)
        lo.addLayout(head)
        self._grid = QLabel("--")
        self._grid.setStyleSheet(
            f"color:{_PAL['sub']};font-size:{fs(11)};background:transparent;"
            f"font-family:'Consolas','Segoe UI','Microsoft YaHei';")
        lo.addWidget(self._grid)
        lo.addStretch()

    def set(self, v: dict):
        if not v or "error" in v:
            self._conf.setText("数据不可用")
            self._grid.setText(str(v.get("error", "")) if v else "")
            return
        self._conf.setText("")   # 数据到位后清掉加载态残留
        self._grid.setText(
            f"IC   {v.get('ic', 0):+.4f}\nICIR {v.get('icir', 0):+.3f}\n"
            f"IC正率 {v.get('ic_positive', 0):.0%}    单调 {v.get('monotonicity', 0):+.2f}\n"
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
        lo.setContentsMargins(dp(14), dp(14), dp(14), dp(14))
        lo.setSpacing(dp(12))

        # 标题(金色) + 说明
        title = QLabel("量化研究")
        title.setStyleSheet(style_title() + f"color:{_PAL['text']};")
        lo.addWidget(title)
        cap = QLabel("LLM-IN-THE-LOOP · 价值因子 · 多因子分层 · 组合纸面盘")
        cap.setStyleSheet(
            f"color:{_PAL['faint']};font-size:{fs(tr(10))};letter-spacing:{dp(1)}px;background:transparent;")
        lo.addWidget(cap)

        # 控制条
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        lbl = QLabel("持有期")
        lbl.setStyleSheet(
            f"color:{_PAL['sub']};font-size:{fs(10)};letter-spacing:{dp(1)}px;background:transparent;")
        ctrl.addWidget(lbl)
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

        # 研究代理 · 市场环境 (2x2 高级卡)
        lo.addWidget(_sec_title("市场环境  ·  研究代理信号"))
        env_grid = QGridLayout()
        env_grid.setSpacing(dp(8))
        self._card_mkt = _StatCard("市场状态")
        self._card_breadth = _StatCard("市场宽度")
        self._card_wvalue = _StatCard("组合价值权重")
        self._card_gate = _StatCard("决策门")
        env_cards = [self._card_mkt, self._card_breadth, self._card_wvalue, self._card_gate]
        for i, card in enumerate(env_cards):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            env_grid.addWidget(card, i // 2, i % 2)
        lo.addLayout(env_grid)

        # 市场宽度仪表 (研究信号可视化: 破年线占比 + 弱市/强市分区)
        self._gauge_card = well("rstat")
        gl = QVBoxLayout(self._gauge_card)
        gl.setContentsMargins(dp(12), dp(10), dp(12), dp(8))
        gl.setSpacing(0)
        self._breadth_gauge = BreadthGauge()
        self._breadth_gauge.setFixedHeight(dp(110))
        gl.addWidget(self._breadth_gauge)
        self._gauge_cap = QLabel("市场宽度 · 破年线占比 (研究中...)" )
        self._gauge_cap.setStyleSheet(
            f"color:{_PAL['faint']};font-size:{fs(9)};background:transparent;")
        self._gauge_cap.setAlignment(Qt.AlignCenter)
        self._gauge_cap.setWordWrap(True)
        gl.addWidget(self._gauge_cap)
        lo.addWidget(self._gauge_card)

        # 价值因子研究 (纵向堆叠高级卡)
        lo.addWidget(_sec_title("价值因子研究  ·  截面 IC / ICIR"))
        self._card_bp = _SecCard("BP  账面市值比")
        self._card_ep = _SecCard("EP  盈利收益率")
        self._card_roe = _SecCard("ROE  净资产收益率")
        for c in (self._card_bp, self._card_ep, self._card_roe):
            c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lo.addWidget(c)

        # 多因子选股
        lo.addWidget(_sec_title("多因子选股  ·  z(BP)+z(REV20)−z(VOL20) 综合分"))
        # 回测选股控制条: 策略 + 日期 + 查看按钮 (选'该日'截面选股)
        pick_row = QHBoxLayout(); pick_row.setSpacing(dp(8))
        pick_row.addWidget(QLabel("策略"))
        self._pick_strategy = QComboBox()
        self._pick_strategy.setFixedHeight(dp(28))
        self._pick_strategy.setMinimumWidth(dp(110))
        for name in STRATEGY_LABELS:
            self._pick_strategy.addItem(name)
        self._pick_strategy.setStyleSheet(qss_combo())
        pick_row.addWidget(self._pick_strategy)
        pick_row.addWidget(QLabel("日期"))
        self._pick_date = QDateEdit()
        self._pick_date.setCalendarPopup(True)
        self._pick_date.setDisplayFormat("yyyy-MM-dd")
        self._pick_date.setFixedHeight(dp(28))
        self._pick_date.setStyleSheet(qss_combo())
        self._pick_date.setDate(QDate.currentDate())
        pick_row.addWidget(self._pick_date)
        self._btn_pick = _btn("查看该日选股", accent=True)
        self._btn_pick.setFixedHeight(dp(28))
        self._btn_pick.clicked.connect(self._on_pick)
        pick_row.addWidget(self._btn_pick)
        self._btn_sim_buy = _btn("一键模拟买入")
        self._btn_sim_buy.setFixedHeight(dp(28))
        self._btn_sim_buy.setToolTip("把当前选股结果等权分配模拟账户资金市价买入")
        self._btn_sim_buy.clicked.connect(self._on_sim_buy)
        pick_row.addWidget(self._btn_sim_buy)
        pick_row.addStretch()
        lo.addLayout(pick_row)
        # 选股/买入结果 caption(独立一行, 避免窄窗口被裁)
        self._pick_cap = QLabel("")
        self._pick_cap.setStyleSheet(_label_ss(size=9) + f"color:{_PAL['faint']};")
        self._pick_cap.setWordWrap(True)
        lo.addWidget(self._pick_cap)
        self._rank_table = QTableWidget()
        self._rank_table.setStyleSheet(self._table_qss())
        self._rank_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rank_table.verticalHeader().setVisible(False)
        self._rank_table.horizontalHeader().setStretchLastSection(True)
        self._rank_table.cellClicked.connect(self._on_row_click)
        self._rank_table.setMinimumHeight(dp(320))
        lo.addWidget(self._rank_table)

        lo.addWidget(_sec_caption("研究池 = 跨板块均衡池(≈287只, 板块中性化)。权威口径(全市场/2500池)见 backend verify_*.py。"))
        lo.addStretch()

        self._scroll.setWidget(body)
        outer.addWidget(self._scroll)

        self._set_loading()

    def _seg_style(self) -> str:
        return (
            f"QPushButton{{background:{_PAL['c_mid']};color:{_PAL['sub']};"
            f"border:1px solid {_PAL['border_lo']};border-top:1px solid {_PAL['border_hi']};"
            f"border-radius:{dps(6)};font-size:{fs(tr(11))};font-weight:600;padding:{dps(3)} {dps(11)};}}"
            f"QPushButton:hover{{border-color:{_PAL['gold']};color:{_PAL['text']};}}"
            f"QPushButton:checked{{background:{_PAL['gold']};color:#14110B;border-color:{_PAL['gold']};}}")

    def _table_qss(self) -> str:
        return (
            f"QTableWidget{{background:{C_BG};color:{_PAL['text']};border:1px solid {_PAL['border_lo']};"
            f"border-radius:{dps(8)};gridline-color:{_PAL['border_lo']};font-size:{fs(13)};}}"
            f"QTableWidget::item{{padding:{dps(4)} {dps(9)};border-bottom:1px solid #12161d;}}"
            f"QTableWidget::item:selected{{background:{_PAL['gold']};color:#14110B;}}"
            f"QTableWidget::item:hover:!selected{{background:{_PAL['c_mid']};}}"
            f"QHeaderView::section{{background:{_PAL['c_mid']};color:{_PAL['sub']};border:none;"
            f"border-bottom:1px solid {_PAL['border_lo']};padding:{dps(6)} {dps(9)};font-size:{fs(12)};"
            f"font-weight:600;letter-spacing:{dp(0.5)}px;}}")

    def _on_hp(self, btn):
        for hp, b in self._segs.items():
            if b is btn:
                self._hp = hp

    def set_hp_and_run(self, hp):
        """外部(总览主功能入口)设定持有期并立刻运行研究."""
        try:
            hp = int(hp)
            if hp in self._segs:
                self._segs[hp].setChecked(True)
                self._hp = hp
            self.load()
        except Exception:
            pass

    def apply_navigation(self, payload):
        """总览主功能入口跳转落地: payload 可含 hp(默认持有期)."""
        hp = payload.get("hp") if isinstance(payload, dict) else None
        try:
            if hp:
                self.set_hp_and_run(hp)
            else:
                self.load()
        except Exception:
            self.load()

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

    def on_theme_changed(self):
        self._rank_table.setStyleSheet(self._table_qss())
        self._rank_table.viewport().update()
        if self._snap:
            try:
                self._render(self._snap)
            except Exception:
                pass
        self.update()

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

    def _on_pick(self):
        """按所选策略+日期做'该日截面'选股(回测选股快照), 填排名表."""
        strategy = self._pick_strategy.currentText()
        date = self._pick_date.date().toString("yyyy-MM-dd")
        w = LocalWorker(self._work_pick, "pick", args=[strategy, date])
        w.result.connect(self._on_pick_data)
        self._workers.append(w)
        w.start()

    def _work_pick(self, strategy, date):
        from .worker import pick_at
        return pick_at(strategy, date)

    def _on_pick_data(self, tag, data):
        if not isinstance(data, dict) or data.get("error"):
            if self.on_status:
                self.on_status("选股失败: %s" % (data.get("error") if data else "无数据"))
            return
        codes = data.get("codes", [])
        self._last_pick_codes = codes
        self._fill_rank_table(codes)
        self._pick_cap.setText(
            f"{data.get('strategy')} · 选股日 {data.get('date')} · 池 {data.get('pool_size')}只")
        if self.on_status:
            self.on_status(f"{data.get('strategy')} {data.get('date')} 选股 {len(codes)} 只")

    def _on_sim_buy(self):
        """把当前选股结果一键模拟买入(等权分配模拟账户资金)."""
        codes = getattr(self, "_last_pick_codes", []) or []
        if not codes:
            # 回退默认: 用当前排名表代码
            codes = [{"code": self._rank_table.item(i, 0).text()}
                     for i in range(self._rank_table.rowCount())
                     if self._rank_table.item(i, 0)]
        codes = [c for c in codes if c.get("code")]
        if not codes:
            if self.on_status:
                self.on_status("无可买入的选股(先查看某日选股)")
            return
        w = LocalWorker(self._work_sim_buy, "sim_buy", args=[codes])
        w.result.connect(self._on_sim_buy_data)
        self._workers.append(w)
        w.start()

    def _work_sim_buy(self, codes):
        from .worker import sim_buy_picks
        return sim_buy_picks(codes)

    def _on_sim_buy_data(self, tag, data):
        if not isinstance(data, dict) or data.get("error"):
            if self.on_status:
                self.on_status("模拟买入失败: %s" % (data.get("error") if data else "无数据"))
            return
        nb = len(data.get("bought", []))
        nskip = len(data.get("skipped", []))
        self._pick_cap.setText(
            f"模拟买入 {nb} 只 / 跳过 {nskip} 只 · 花费 {data.get('total_cost', 0):,.0f} · 账户#{data.get('account_id')}")
        if self.on_status:
            self.on_status(f"模拟买入完成: {nb}只 花费 {data.get('total_cost', 0):,.0f} (跳过{nskip})")

    def _render(self, snap):
        sig = snap.get("signals", {})
        vt = sig.get("value_tilt", {}) or {}
        br = sig.get("breadth", {}) or {}
        al = sig.get("alloc", {}) or {}
        hr = sig.get("hard_rule")

        # 市场状态(药丸)
        vt_tilt = vt.get("value_tilt", "neutral")
        vt_color = _PAL["down"] if vt_tilt == "value_favorable" else (_PAL["up"] if vt_tilt == "value_headwind" else _PAL["sub"])
        self._card_mkt.set("value_headwind" if vt_tilt == "value_headwind" else vt_tilt,
                           sub=f"{vt.get('state', '')} · 回撤 {vt.get('drawdown', 0):.1%}" if isinstance(vt.get('drawdown'), float)
                           else str(vt.get("reason", ""))[:60],
                           color=vt_color, value_size=12, pill=True)

        # 市场宽度(轻量数字)
        b = br.get("breadth", 0.5)
        b_tilt = br.get("tilt", "value_neutral")
        b_color = _PAL["down"] if b_tilt == "value_favorable" else (_PAL["up"] if b_tilt == "value_headwind" else _PAL["sub"])
        self._card_breadth.set(f"{b:.0%}", sub=f"破年线占比 · {b_tilt.replace('value_','')}", color=b_color)
        self._breadth_gauge.set_value(b, b_tilt)
        self._gauge_cap.setText(
            "市场宽度 · 破年线占比 — " + str(br.get("reason", "")).split("→")[0].strip()[:48])

        # 组合价值权重
        wv = al.get("w_value", 1.0)
        wlabel = al.get("tilt_label", "")
        wcolor = _PAL["down"] if wlabel == "value_favorable" else (_PAL["up"] if wlabel == "value_headwind" else _PAL["sub"])
        self._card_wvalue.set(f"×{wv:.1f}", sub=f"{wlabel.replace('value_','')} · 三路信号多数决", color=wcolor)

        # 决策门(药丸)
        if hr and isinstance(hr, dict) and "error" not in hr:
            act = hr.get("action", "hold")
            gcolor = _PAL["up"] if act == "hold" else _PAL["down"]
            self._card_gate.set(act.upper(), sub=str(hr.get("reason", ""))[:70], color=gcolor, pill=True)
        else:
            self._card_gate.set("--", "无价值硬裁决" if not (hr and hr.get("error")) else "判断不可用")

        # 价值因子研究
        st = snap.get("study", {})
        self._card_bp.set(st.get("BP", {}))
        self._card_ep.set(st.get("EP", {}))
        self._card_roe.set(st.get("ROE", {}))

        # 多因子排名(默认=最新截面 as_of)
        rk = snap.get("ranking", []) or []
        self._fill_rank_table(rk)
        self._pick_cap.setText(
            f"默认 · {self._hp}日因子 · 数据截至 {snap.get('as_of')} · 池 {snap.get('pool_size')}只")

    def _fill_rank_table(self, rk):
        """把排名/选股行填进排名表(代码/现价/涨跌%/综合分). rk: [{code,price,chg,comp}]."""
        cols = ["代码", "现价", "涨跌%", "综合分"]
        self._rank_table.setRowCount(len(rk))
        self._rank_table.setColumnCount(len(cols))
        self._rank_table.setHorizontalHeaderLabels(cols)
        for i, r in enumerate(rk):
            items = [
                (str(r.get("code", "")), _PAL["text"]),
                ("{:.2f}".format(r.get("price", 0)), _PAL["sub"]),
                (("{:+.2f}".format(r.get("chg", 0))), _PAL["down"] if r.get("chg", 0) < 0 else _PAL["up"]),
                ("{:.3f}".format(r.get("comp", 0)), _PAL["gold"]),
            ]
            for j, (text, color) in enumerate(items):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                it.setForeground(QColor(color))
                if j == 3:
                    it.setFont(QFont("", -1, QFont.Bold))
                self._rank_table.setItem(i, j, it)
        self._rank_table.resizeColumnsToContents()
        self._rank_table.setColumnWidth(0, dp(84))
        self._rank_table.setColumnWidth(3, dp(96))

    def _on_row_click(self, row, col):
        # 支持'该日选股'后的点击: 用当前表格首列代码开K线
        item = self._rank_table.item(row, 0)
        if not item:
            return
        code = item.text()
        if code and self.on_open_kline:
            self.on_open_kline(code, "")
