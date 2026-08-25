# -*- coding: utf-8 -*-
"""Holdings Panel — 主流程末步「纸面盘」账本可视化(多策略).

读 data/paper_runs.json (run_paper_multi 持久化): 多个策略契约各自的
收益曲线(对比) + 每调仓日持仓 + 每笔调仓历史; 无 paper_runs.json 时回退单个 data/paper_run.json.
数据源后端: strategy/portfolio_rebalance.py::forward_paper_run (记录 daily_holdings/rebalance_log)."""
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
PAPER_RUNS = os.path.join(ROOT, 'data', 'paper_runs.json')
PAPER_JSON = os.path.join(ROOT, 'data', 'paper_run.json')
KLINE_DB = os.path.join(ROOT, 'data', 'kline.db')
HS300_JSON = os.path.join(ROOT, 'data', 'hs300.json')
_INIT = 1_000_000.0


def _load_paper_runs():
    """读多策略账本; 无则回退单策略 paper_run.json. 返回 {runs, buyhold, selected, as_of, pool_size, hp}."""
    try:
        d = json.load(open(PAPER_RUNS, encoding='utf-8'))
        runs = d.get('runs') or {}
        if runs:
            return {"runs": runs, "buyhold": d.get('buyhold') or {}, "selected": d.get('selected'),
                    "as_of": d.get('as_of'), "pool_size": d.get('pool_size'), "hp": d.get('hp')}
    except Exception:
        pass
    try:
        d = json.load(open(PAPER_JSON, encoding='utf-8'))
        p = d.get('paper') or {}
        if p.get('error'):
            return {"runs": {}, "buyhold": {}, "selected": None, "as_of": d.get('as_of'),
                    "pool_size": d.get('pool_size'), "hp": d.get('hp'), "error": p['error']}
        bh = {"dates": p.get('buyhold_dates', []), "nav": p.get('buyhold_nav', [])}
        return {"runs": {"默认": p}, "buyhold": bh, "selected": "默认",
                "as_of": d.get('as_of'), "pool_size": d.get('pool_size'), "hp": d.get('hp')}
    except Exception:
        return {"runs": {}, "buyhold": {}, "selected": None}


def _close_map(codes, date):
    """取某日一批 code 的 close (kline_daily), 供计算持仓市值. 日期归一化为紧凑 YYYYMMDD."""
    try:
        d = str(date)[:10].replace('-', '')
        con = sqlite3.connect(KLINE_DB)
        q = "SELECT code, close FROM kline_daily WHERE date=? AND code IN (%s)" % \
            ",".join("?" for _ in codes)
        rows = con.execute(q, [d] + list(codes)).fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _load_hs300(rebal_dates):
    """读沪深300基线缓存 data/hs300.json → 采样到重平衡日网格, 返回 {dates, nav(绝对市值, ×INIT)}.

    nav = (close/close[首重平衡日]) * _INIT —— 与策略同单位(增长倍数×INIT), 起点=1.0."""
    import bisect
    try:
        d = json.load(open(HS300_JSON, encoding='utf-8'))
        dates = d.get('dates', []) or []
        closes = d.get('closes', []) or []
        if not dates or not rebal_dates:
            return None
        cmap = {str(x)[:10]: float(c) for x, c in zip(dates, closes)}
        keys = sorted(cmap)

        def close_on(g):
            idx = bisect.bisect_right(keys, str(g)[:10]) - 1
            return cmap[keys[idx]] if idx >= 0 else None

        base = None
        for g in rebal_dates:
            v = close_on(g)
            if v:
                base = v
                break
        if not base:
            return None
        out_d, out_n = [], []
        for g in rebal_dates:
            v = close_on(g)
            if v is not None:
                out_d.append(str(g)[:10])
                out_n.append(v / base * _INIT)
        return {'dates': out_d, 'nav': out_n} if out_n else None
    except Exception:
        return None


class _EquityCurve(QWidget):
    """多策略收益曲线(高级版): 各策略净值(选中加亮+面积填充) vs 买持/沪深300 基线.

    归一化为增长倍数(y 轴=收益率). 主题 token 驱动, 无硬编码 hex; 选中=accent 粗线,
    非选中=accent 阶梯透明度, 基线=中性灰不同线型(买持虚线 / 沪深300点线)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(dp(224))
        self._series = []   # [{name, dates, nav, selected}]
        self._bh = None     # {dates, nav}
        self._hs300 = None  # {dates, nav}

    def set_series(self, series, buyhold=None, hs300=None):
        self._series = series or []
        self._bh = buyhold or None
        self._hs300 = hs300 or None
        self.update()

    def _common_axis(self):
        ds = set()
        for s in self._series:
            ds.update(s.get('dates', []))
        if self._bh:
            ds.update(self._bh.get('dates', []))
        if self._hs300:
            ds.update(self._hs300.get('dates', []))
        return sorted(ds)

    @staticmethod
    def _align(common, dates, values):
        d2v = {d: v for d, v in zip(dates, values)}
        out, last = [], None
        for d in common:
            if d in d2v:
                last = d2v[d]
            out.append(last)
        return out

    def _yrange(self):
        vals = []
        for s in self._series:
            vals += [(v / _INIT) for v in s.get('nav', [])]
        for src in (self._bh, self._hs300):
            if src:
                vals += [(v / _INIT) for v in src.get('nav', [])]
        vals = [v for v in vals if v is not None]
        if not vals:
            return 0.9, 1.1
        return min(vals), max(vals)

    def _paint_bg(self, p, w, h):
        # 极致克制的底部微亮(纯色极低alpha, 避免深色图上渐变硬崩风险)
        c = QColor(PAL['c_mid']); c.setAlpha(14)
        p.fillRect(0, 0, w, h, c)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = dp(50), dp(18), dp(44), dp(30)
        self._paint_bg(p, w, h)
        if not self._series:
            self._empty(p, w, h); p.end(); return
        common = self._common_axis()
        if len(common) < 2:
            self._empty(p, w, h); p.end(); return
        vmin, vmax = self._yrange()
        span = vmax - vmin
        if span < 1e-6:
            vmax += 0.02; span = vmax - vmin
        vmin, vmax = vmin - span * 0.07, vmax + span * 0.07

        def X(i): return pad_l + (w - pad_l - pad_r) * (i / (len(common) - 1))
        def Y(v): return pad_t + (h - pad_t - pad_b) * (1 - (v - vmin) / (vmax - vmin))

        # 网格 + y 刻度
        gridd = QColor(PAL['border_lo']); gridd.setAlpha(100)
        p.setFont(QFont("Microsoft YaHei", _pt(8)))
        for i in range(5):
            gy = pad_t + (h - pad_t - pad_b) * (i / 4)
            v = vmax - (vmax - vmin) * (i / 4)
            p.setPen(QPen(gridd, 1))
            p.drawLine(QPointF(pad_l, gy), QPointF(w - pad_r, gy))
            p.setPen(QColor(PAL['sub']))
            p.drawText(QPointF(4, gy + _pt(3)), f"{v - 1.0:+.0%}")
        # 零线(收益=0)
        if vmin < 1.0 < vmax:
            zc = QColor(PAL['faint']); zc.setAlpha(70)
            p.setPen(QPen(zc, 1, Qt.DashLine))
            p.drawLine(QPointF(pad_l, Y(1.0)), QPointF(w - pad_r, Y(1.0)))

        def aligned(dates, values):
            return self._align(common, dates, values)

        acc = QColor(PAL['accent'])
        alphas = [165, 128, 95, 62]
        sel_idx = next((i for i, s in enumerate(self._series) if s.get('selected')), -1)
        # 先画基线(买持灰虚线, 沪深300点线)
        baselines = []
        if self._bh:
            baselines.append(('买持', aligned(self._bh['dates'], self._bh['nav']),
                              QColor(PAL['faint']), 1.3, Qt.DashLine))
        if self._hs300:
            baselines.append(('沪深300', aligned(self._hs300['dates'], self._hs300['nav']),
                              QColor(PAL['sub']), 1.4, Qt.DashDotLine))
        for name, vlist, color, width, dash in baselines:
            poly = QPolygonF([QPointF(X(i), Y(v / _INIT)) for i, v in enumerate(vlist) if v is not None])
            pen = QPen(color, width); pen.setStyle(dash)
            p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPolyline(poly)
        # 非选中策略(accent 阶梯透明度, 细)
        non_sel = [s for i, s in enumerate(self._series) if i != sel_idx]
        for k, s in enumerate(non_sel):
            c = QColor(acc); c.setAlpha(alphas[k % len(alphas)])
            vlist = aligned(s['dates'], s['nav'])
            poly = QPolygonF([QPointF(X(i), Y(v / _INIT)) for i, v in enumerate(vlist) if v is not None])
            p.setPen(QPen(c, 1.2)); p.setBrush(Qt.NoBrush); p.drawPolyline(poly)
        # 选中策略: 面积填充 + 粗线(最上层)
        if sel_idx >= 0:
            s = self._series[sel_idx]
            vlist = aligned(s['dates'], s['nav'])
            pts = [(X(i), Y(v / _INIT)) for i, v in enumerate(vlist) if v is not None]
            if len(pts) >= 2:
                band = QPolygonF([QPointF(x, y) for x, y in pts] +
                                 [QPointF(pts[-1][0], h - pad_b), QPointF(pts[0][0], h - pad_b)])
                # 纯色极低alpha填充(柔和不抢戏; 避免渐变画笔在部分Qt5上的稳定问题)
                fillc = QColor(acc); fillc.setAlpha(22)
                p.setPen(Qt.NoPen); p.setBrush(fillc); p.drawPolygon(band)
                p.setPen(QPen(QColor(acc), 2.6)); p.setBrush(Qt.NoBrush)
                p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
            self._final_label(p, pts[-1], vlist, QColor(acc), pad_r, w, pad_l)
        # 基线端收益标注
        for name, vlist, color, width, dash in baselines:
            bpts = [(X(i), Y(v / _INIT)) for i, v in enumerate(vlist) if v is not None]
            if bpts:
                self._final_label(p, bpts[-1], vlist, color, pad_r, w, pad_l)
        # 首末日期
        p.setPen(QColor(PAL['sub']))
        p.drawText(QPointF(pad_l, h - 6), str(common[0])[:10])
        last_label = str(common[-1])[:10]
        p.drawText(QPointF(w - pad_r - QFontMetricsF(p.font()).width(last_label), h - 6), last_label)
        # 图例
        self._legend(p, w, pad_l, pad_r, acc, alphas, sel_idx)
        p.end()

    def _final_label(self, p, pt, vlist, color, pad_r, w, pad_l):
        """在序列末端标注最终收益率(右对齐). pt: 末端 (x,y); vlist: 对齐序列."""
        last = None
        for v in reversed(vlist):
            if v is not None:
                last = v / _INIT
                break
        if last is None or pt is None:
            return
        txt = f"{last - 1.0:+.1%}"
        fm = p.fontMetrics()
        tw = fm.width(txt)
        x = pt[0] - tw - dp(8)
        if x < pad_l:
            x = pad_l
        p.setPen(QColor(color))
        p.drawText(QPointF(x, pt[1] + _pt(4)), txt)

    def _legend(self, p, w, pad_l, pad_r, acc, alphas, sel_idx):
        items = []
        for i, s in enumerate(self._series):
            if s.get('selected'):
                items.append((QColor(acc), 2.6, "★ " + s.get('name', '')))
            else:
                c = QColor(acc); c.setAlpha(alphas[[j for j, x in enumerate(self._series) if x is not s][0] % len(alphas)])
                items.append((c, 1.2, s.get('name', '')))
        if self._bh:
            items.append((QColor(PAL['faint']), 1.3, "买持"))
        if self._hs300:
            items.append((QColor(PAL['sub']), 1.4, "沪深300"))
        # 图例底衬
        n_rows = 1
        fm = p.fontMetrics()
        x0, y = pad_l, dp(6)
        est_w = pad_l
        for color, width, label in items:
            lw = fm.width(label)
            if est_w + dp(13) + dp(6) + lw + dp(14) > w - pad_r:
                n_rows += 1
                est_w = pad_l
            est_w += dp(13) + dp(6) + lw + dp(14)
        leg_h = dp(6) + n_rows * dp(16)
        bg0 = QColor(PAL['c_mid']); bg0.setAlpha(120)
        p.fillRect(0, 0, w, leg_h, bg0)
        p.setPen(QPen(QColor(PAL['border_lo']), 1))
        p.drawLine(QPointF(0, leg_h), QPointF(w, leg_h))
        x0, y = pad_l, dp(6)
        for color, width, label in items:
            sw = dp(13)
            lw = fm.width(label)
            if x0 + sw + dp(6) + lw > w - pad_r:
                x0 = pad_l; y += dp(16)
            pen = QPen(color, width); p.setPen(pen)
            p.drawLine(QPointF(x0, y + dp(7)), QPointF(x0 + sw, y + dp(7)))
            p.setPen(QColor(PAL['text']))
            p.drawText(QPointF(x0 + sw + dp(5), y + dp(10)), label)
            x0 += sw + dp(6) + lw + dp(14)

    def _empty(self, p, w, h):
        p.setPen(QColor(PAL['faint']))
        p.drawText(QPointF(w // 2 - dp(70), h // 2), "无纸面盘数据(需先运行流程)")


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = KLINE_DB
        self.on_open_kline = None
        self.on_status = None
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._data = {"runs": {}, "buyhold": {}, "selected": None}
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
        cap = QLabel("主流程末步 · 组合重平衡/纸面盘 · 多策略对比 · 每日持仓 · 每笔调仓")
        cap.setStyleSheet(value_ss(size=10) + f"color:{PAL['sub']};")
        self._cards_lo.addWidget(cap)
        # 策略选择器
        self._strategy_combo = QComboBox()
        self._strategy_combo.setStyleSheet(f"QComboBox{{background:{PAL['c_mid']};color:{PAL['text']};"
                                           f"border:1px solid {PAL['border_lo']};padding:2px 8px;}}")
        self._strategy_combo.currentIndexChanged.connect(lambda _: self._render())
        self._cards_lo.addWidget(self._strategy_combo)
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
        # 收益曲线(多策略对比)
        cur = QFrame(); cur.setStyleSheet(card_qss("card"))
        clo = QVBoxLayout(cur); clo.setContentsMargins(dp(10), dp(6), dp(10), dp(6))
        cl = QLabel("收益曲线(策略对比)"); cl.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
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
        self._data = _load_paper_runs()
        runs = self._data.get('runs') or {}
        self._strategy_combo.blockSignals(True)
        self._strategy_combo.clear()
        for name in runs:
            self._strategy_combo.addItem(name)
        sel = self._data.get('selected')
        if sel not in runs:
            sel = list(runs)[0] if runs else None
        if sel:
            self._strategy_combo.setCurrentIndex(list(runs).index(sel))
        self._strategy_combo.setVisible(len(runs) > 1)
        self._strategy_combo.blockSignals(False)
        self._render()

    def _active_paper(self):
        runs = self._data.get('runs') or {}
        name = self._strategy_combo.currentText()
        return runs.get(name) if name else None

    def _render(self):
        paper = self._active_paper()
        runs = self._data.get('runs') or {}
        # 曲线(所有策略 + 买持)
        series = []
        for name, run in runs.items():
            if not isinstance(run, dict) or run.get('error'):
                continue
            series.append({'name': name, 'dates': run.get('dates', []), 'nav': run.get('nav', []),
                           'selected': name == self._strategy_combo.currentText()})
        bh = self._data.get('buyhold') or {}
        bh_abs = {'dates': bh.get('dates', []), 'nav': [(v * _INIT) for v in bh.get('nav', [])]}
        grid = series[0]['dates'] if series else []
        hs300 = _load_hs300(grid) if grid else None
        self._curve.set_series(series, bh_abs, hs300)
        if not paper or paper.get('error'):
            for k in ("v0", "vend", "ret", "reb", "to", "asof"):
                self._sum_labels[k].setText("—")
            self._hx_date.clear(); self._hx_table.setRowCount(0); self._reb_table.setRowCount(0)
            self._paper = None
            return
        self._paper = paper
        nav = paper.get('nav', [])
        self._sum_labels["v0"].setText(f"{_INIT:,.0f}")
        self._sum_labels["vend"].setText(f"{(nav[-1] if nav else 0):,.0f}")
        ret = (nav[-1] / _INIT - 1) if nav else 0
        self._sum_labels["ret"].setText(f"{ret:+.1%}")
        self._sum_labels["reb"].setText(str(paper.get('rebalances', 0)))
        to = paper.get('turnover_avg', 0)
        self._sum_labels["to"].setText(f"{to*100:.1f}%")
        self._sum_labels["asof"].setText(str(self._data.get('as_of', "—")))
        # 持仓日期选择
        dh = paper.get('daily_holdings', [])
        self._hx_date.blockSignals(True)
        self._hx_date.clear()
        for h in dh:
            self._hx_date.addItem(f"{h['date']} · 持仓{len(h.get('holdings', {}))}只 · 净值{hm(h['nav'])}")
        self._hx_date.blockSignals(False)
        self._render_hold()
        self._render_reb(paper)

    def _render_hold(self):
        idx = self._hx_date.currentIndex()
        dh = self._paper.get('daily_holdings', []) if getattr(self, '_paper', None) else []
        if idx < 0 or idx >= len(dh):
            self._hx_table.setRowCount(0); return
        h = dh[idx]
        holds = h.get('holdings', {})
        cmap = _close_map(list(holds.keys()), h['date'])
        rows = [{"code": c, "qty": q, "px": cmap.get(c),
                 "val": (q * cmap[c]) if cmap.get(c) else None} for c, q in holds.items()]
        rows.sort(key=lambda r: -(r['val'] or 0))
        self._fill_table(self._hx_table, ["代码", "数量", "现价", "市值", "权重"],
                         [[r['code'], f'{r["qty"]:,}', f'{r["px"]:.2f}' if r['px'] else "—",
                           f'{r["val"]:,.0f}' if r['val'] is not None else "—",
                           f'{r["val"]/(h.get("nav") or 1):.1%}' if r['val'] else "—"] for r in rows])

    def _render_reb(self, paper):
        log = paper.get('rebalance_log', [])
        rows = []
        entry = paper.get('daily_holdings', [])
        for r in log:
            for t in r.get('trades', []):
                amt = t['qty'] * t['price']
                rows.append([r['date'], t['code'], "买入" if t['side'] == 'buy' else "卖出",
                             f'{t["qty"]:,}', f'{t["price"]:.2f}', f'{amt:,.0f}'])
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
