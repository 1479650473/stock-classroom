# -*- coding: utf-8 -*-
"""Holdings Panel — 主流程末步「纸面盘」账本可视化.
读 data/paper_run.json (build_paper_only 持久化): 收益曲线(净值 vs 买持) + 每调仓日持仓 + 每笔调仓历史.
数据源后端: strategy/portfolio_rebalance.py::forward_paper_run (已增强记录 daily_holdings/rebalance_log)."""
import os, json, sqlite3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
                             QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTabWidget,
                             QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF, QFont, QFontMetricsF
from PyQt5.QtCore import QPointF
from frontend.platform.theme import dp, fs, dps
from frontend.platform.premium import PAL, card_qss, label_ss, value_ss, well

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAPER_JSON = os.path.join(ROOT, 'data', 'paper_run.json')
KLINE_DB = os.path.join(ROOT, 'data', 'kline.db')
_INIT = 1_000_000.0


def _load_paper():
    try:
        d = json.load(open(PAPER_JSON, encoding='utf-8'))
        p = d.get('paper') or {}
        if p.get('error'):
            return None, d
        return p, d
    except Exception:
        return None, {}


def _close_map(codes, date):
    """取某日一批 code 的 close (kline_daily), 供计算持仓市值. 日期归一化为紧凑 YYYYMMDD."""
    try:
        # paper 日期形如 '2024-01-02 00:00:00' / '2024-01-02' → 紧凑 '20240102'
        d = str(date)[:10].replace('-', '')
        con = sqlite3.connect(KLINE_DB)
        q = "SELECT code, close FROM kline_daily WHERE date=? AND code IN (%s)" % \
            ",".join("?" for _ in codes)
        rows = con.execute(q, [d] + list(codes)).fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


class _EquityCurve(QWidget):
    """收益曲线: 纸面盘净值 vs 等权买持 (归一化为增长倍数)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(dp(190))
        self._nav = []   # growth multiples
        self._bh = []
        self._dates = []

    def set_series(self, dates, nav, bh):
        base = _INIT
        self._dates = dates
        self._nav = [(v / base) for v in nav] if nav else []
        self._bh = bh or []
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = dp(42), dp(12), dp(20), dp(26)
        if not self._nav:
            self._empty(p, w, h)
            p.end(); return
        xs = len(self._nav)
        if xs < 2:
            self._empty(p, w, h); p.end(); return
        # y 范围(含买持)
        vals = list(self._nav) + list(self._bh)
        vmin, vmax = min(vals), max(vals)
        if vmax - vmin < 1e-6:
            vmax += 0.02
        span = vmax - vmin
        vmin, vmax = vmin - span * 0.06, vmax + span * 0.06
        def X(i): return pad_l + (w - pad_l - pad_r) * (i / (xs - 1))
        def Y(v): return pad_t + (h - pad_t - pad_b) * (1 - (v - vmin) / (vmax - vmin))
        # 网格 + y 刻度
        p.setPen(QPen(QColor(PAL['border_lo']), 1))
        p.setFont(QFont("Microsoft YaHei", _pt(7)))
        for i in range(5):
            gy = pad_t + (h - pad_t - pad_b) * (i / 4)
            p.drawLine(QPointF(pad_l, gy), QPointF(w - pad_r, gy))
            v = vmax - (vmax - vmin) * (i / 4)
            p.drawText(QPointF(2, gy + _pt(3)), f"{v - 1.0:+.0%}")
        # 纸面盘曲线(accent)
        self._draw_line(p, self._nav, X, Y, QColor(PAL['accent']), 2)
        # 买持曲线(faint)
        if self._bh:
            self._draw_line(p, self._bh, X, Y, QColor(PAL['faint']), 1)
        # 首末日期
        p.setPen(QColor(PAL['sub']))
        p.drawText(QPointF(pad_l, h - 6), self._dates[0])
        p.drawText(QPointF(w - pad_r - QFontMetricsF(p.font()).width(self._dates[-1]), h - 6), self._dates[-1])
        # 图例
        lx, ly = w - pad_r - dp(150), pad_t - dp(2)
        p.setPen(QPen(QColor(PAL['accent']), 2)); p.drawLine(lx, ly + dp(4), lx + dp(14), ly + dp(4))
        p.setPen(QColor(PAL['sub'])); p.drawText(lx + dp(18), ly + dp(8), "纸面盘")
        if self._bh:
            p.setPen(QPen(QColor(PAL['faint']), 1)); p.drawLine(lx + dp(66), ly + dp(4), lx + dp(80), ly + dp(4))
            p.setPen(QColor(PAL['sub'])); p.drawText(lx + dp(84), ly + dp(8), "买持")
        p.end()

    def _draw_line(self, p, series, X, Y, color, width):
        poly = QPolygonF([QPointF(X(i), Y(v)) for i, v in enumerate(series)])
        p.setPen(QPen(color, width))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)

    def _empty(self, p, w, h):
        p.setPen(QColor(PAL['faint']))
        p.drawText(QPointF(w // 2 - dp(60), h // 2), "无纸面盘数据(需先运行流程)")


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = KLINE_DB
        self.on_open_kline = None
        self.on_status = None
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._load_ui()

    def _load_ui(self):
        self._cards_lo = QVBoxLayout(self)
        self._cards_lo.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        self._cards_lo.setSpacing(dp(8))
        self._build()
        self.load()

    def _build(self):
        while self._cards_lo.count():
            it = self._cards_lo.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        # 标题
        t = QLabel("纸面盘持仓账本"); t.setStyleSheet(label_ss(size=11) + f"color:{PAL['text']};")
        self._cards_lo.addWidget(t)
        cap = QLabel("主流程末步 · 组合重平衡/纸面盘 · 每日持仓 · 每笔调仓 · 收益曲线")
        cap.setStyleSheet(value_ss(size=10) + f"color:{PAL['sub']};")
        self._cards_lo.addWidget(cap)
        # 摘要卡
        self._sum_row = QHBoxLayout(); self._sum_row.setSpacing(dp(8))
        self._sum_labels = {}
        for k, name in [("v0", "期初"), ("vend", "期末净值"), ("ret", "累计收益"),
                        ("reb", "调仓次数"), ("to", "换手率"), ("asof", "as_of")]:
            card = QFrame(); card.setStyleSheet(card_qss("card"))
            lo = QVBoxLayout(card); lo.setContentsMargins(dp(10), dp(8), dp(10), dp(8)); lo.setSpacing(0)
            lb = QLabel(name); lb.setStyleSheet(label_ss(size=8))
            v = QLabel("—"); v.setStyleSheet(value_ss(color=PAL['accent'], size=13))
            lo.addWidget(lb); lo.addWidget(v)
            self._sum_row.addWidget(card, 1)
            self._sum_labels[k] = v
        self._cards_lo.addLayout(self._sum_row)
        # 收益曲线
        cur = QFrame(); cur.setStyleSheet(card_qss("card"))
        clo = QVBoxLayout(cur); clo.setContentsMargins(dp(10), dp(6), dp(10), dp(6))
        cl = QLabel("收益曲线"); cl.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        clo.addWidget(cl)
        self._curve = _EquityCurve()
        clo.addWidget(self._curve)
        self._cards_lo.addWidget(cur)
        # 表格区
        tabs = QTabWidget()
        tabs.setStyleSheet(f"QTabWidget::pane{{border:1px solid {PAL['border_lo']};}}")
        self._hx_table = self._mk_table()
        self._hx_date = QComboBox(); self._hx_date.currentIndexChanged.connect(lambda _: self._render_hold())
        hx = QWidget(); hl = QVBoxLayout(hx); hl.setContentsMargins(dp(6), dp(6), dp(6), dp(6))
        hl.addWidget(self._hx_date)
        hl.addWidget(self._hx_table)
        tabs.addTab(hx, "持仓(按调仓日)")
        self._reb_table = self._mk_table()
        tabs.addTab(self._reb_table, "调仓记录")
        self._cards_lo.addWidget(tabs, 1)

    def _mk_table(self):
        tbl = QTableWidget()
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.verticalHeader().setVisible(False)
        tbl.setShowGrid(False)
        tbl.verticalHeader().setDefaultSectionSize(dp(22))
        tbl.setFont(QFont("Microsoft YaHei", _pt(9)))
        return tbl

    # ── 加载 ──
    def load(self):
        paper, meta = _load_paper()
        if not paper:
            self._cards_lo.count()
            return
        # 摘要
        nav = paper.get("nav", [])
        self._sum_labels["v0"].setText(f"{_INIT:,.0f}")
        self._sum_labels["vend"].setText(f"{(nav[-1] if nav else 0):,.0f}")
        ret = (nav[-1] / _INIT - 1) if nav else 0
        self._sum_labels["ret"].setText(f"{ret:+.1%}")
        self._sum_labels["reb"].setText(str(paper.get("rebalances", 0)))
        to = paper.get("turnover_avg", 0)
        self._sum_labels["to"].setText(f"{to*100:.1f}%")
        self._sum_labels["asof"].setText(str(meta.get("as_of", "—")))
        # 曲线
        self._curve.set_series(paper.get("dates", []), nav, paper.get("buyhold_nav", []))
        # 持仓日期选择
        dh = paper.get("daily_holdings", [])
        self._hx_date.blockSignals(True)
        self._hx_date.clear()
        self._paper = paper
        for h in dh:
            self._hx_date.addItem(f"{h['date']} · 持仓{len(h.get('holdings', {}))}只 · 净值{hm(h['nav'])}")
        self._hx_date.blockSignals(False)
        self._render_hold()
        # 调仓记录
        self._render_reb(paper)

    def _render_hold(self):
        idx = self._hx_date.currentIndex()
        dh = self._paper.get("daily_holdings", []) if getattr(self, '_paper', None) else []
        if idx < 0 or idx >= len(dh):
            self._hx_table.setRowCount(0); return
        h = dh[idx]
        holds = h.get("holdings", {})
        cmap = _close_map(list(holds.keys()), h["date"])
        rows = [{"code": c, "qty": q, "px": cmap.get(c),
                 "val": (q * cmap[c]) if cmap.get(c) else None} for c, q in holds.items()]
        rows.sort(key=lambda r: -(r["val"] or 0))
        self._fill_table(self._hx_table, ["代码", "数量", "现价", "市值", "权重"],
                         [[r["code"], f'{r["qty"]:,}', f'{r["px"]:.2f}' if r["px"] else "—",
                           f'{r["val"]:,.0f}' if r["val"] is not None else "—",
                           f'{r["val"]/(h.get("nav") or 1):.1%}' if r["val"] else "—"] for r in rows])

    def _render_reb(self, paper):
        log = paper.get("rebalance_log", [])
        rows = []
        entry = paper.get("daily_holdings", [])
        nav_by_date = {e["date"]: e["nav"] for e in entry}
        for r in log:
            for t in r.get("trades", []):
                amt = t["qty"] * t["price"]
                rows.append([r["date"], t["code"], "买入" if t["side"] == "buy" else "卖出",
                             f'{t["qty"]:,}', f'{t["price"]:.2f}', f'{amt:,.0f}'])
        # 空行填充
        self._fill_table(self._reb_table, ["调仓日", "代码", "方向", "数量", "价格", "金额"], rows)

    def _fill_table(self, tbl, headers, rows):
        tbl.setColumnCount(len(headers)); tbl.setHorizontalHeaderLabels(headers)
        tbl.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                it = QTableWidgetItem(str(val))
                it.setTextAlignment(Qt.AlignCenter if j else Qt.AlignLeft)
                tbl.setItem(i, j, it)
        tbl.horizontalHeader().setStretchLastSection(True)

    def on_theme_changed(self):
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._build(); self.load()

    def refresh(self):
        self.load()


def hm(v):
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return "—"


def _pt(n):
    """fs() 返回 'Npx' 字符串, 这里取整数字号给 QFont."""
    return int(str(fs(n)).replace('px', ''))
