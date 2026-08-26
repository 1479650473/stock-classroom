# -*- coding: utf-8 -*-
"""Holdings Panel — 主流程末步「纸面盘」账本可视化(多策略).

读 data/paper_runs.json (run_paper_multi 持久化): 多个策略契约各自的
收益曲线(对比) + 每调仓日持仓 + 每笔调仓历史; 无 paper_runs.json 时回退单个 data/paper_run.json.
数据源后端: strategy/portfolio_rebalance.py::forward_paper_run (记录 daily_holdings/rebalance_log)."""
import os, json, sqlite3
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
                             QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTabWidget,
                             QAbstractItemView, QPushButton, QButtonGroup, QDialog, QGridLayout,
                             QScrollArea, QStackedWidget)
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF, QFont, QFontMetricsF
from PyQt5.QtCore import QPointF
from frontend.platform.theme import dp, fs, dps, tr, style_title
from frontend.platform.premium import PAL, card_qss, label_ss, value_ss, hero_ss, well

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PAPER_RUNS = os.path.join(ROOT, 'data', 'paper_runs.json')
PAPER_JSON = os.path.join(ROOT, 'data', 'paper_run.json')
KLINE_DB = os.path.join(ROOT, 'data', 'kline.db')
HS300_JSON = os.path.join(ROOT, 'data', 'hs300.json')
SIM_DB = os.path.join(ROOT, 'data', 'sim_trade.db')
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


def _last_close(code):
    """某股 kline 最新收盘价."""
    try:
        con = sqlite3.connect(KLINE_DB)
        r = con.execute("SELECT close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1", (code,)).fetchone()
        con.close()
        return float(r[0]) if r else None
    except Exception:
        return None


def _names_map(codes):
    """kline stock_list 的 code→name."""
    try:
        con = sqlite3.connect(KLINE_DB)
        q = "SELECT code, name FROM stock_list WHERE code IN (%s)" % ",".join("?" for _ in codes)
        m = {r[0]: r[1] for r in con.execute(q, list(codes))}
        con.close()
        return m
    except Exception:
        return {}


def _kline_as_of():
    """kline_daily 最新交易日(实时/历史持仓的'数据截至'基准). 归一化为 YYYY-MM-DD."""
    try:
        con = sqlite3.connect(KLINE_DB)
        r = con.execute("SELECT MAX(date) FROM kline_daily").fetchone()
        con.close()
        d = r[0] if r and r[0] else None
        if not d:
            return None
        s = str(d)
        return s[:4] + "-" + s[4:6] + "-" + s[6:8] if len(s) == 8 else s[:10]
    except Exception:
        return None


def _load_live_holdings():
    """读模拟盘今日实时持仓(选有持仓的账户), 用 kline 最新收盘价刷新市值/浮盈.

    返回 {account_id, account_name, cash, holdings:[{code,name,qty,cost,px,value,pnl,weight}],
          market_value, total_asset, total_pnl, pct_pnl}."""
    try:
        con = sqlite3.connect(SIM_DB); con.row_factory = sqlite3.Row
        c = con.cursor()
        acc = c.execute("""SELECT a.id, a.name, a.balance FROM accounts a
                           WHERE a.id IN (SELECT DISTINCT account_id FROM positions WHERE qty>0)
                           ORDER BY a.id DESC LIMIT 1""").fetchone()
        if not acc:
            acc = c.execute("SELECT id,name,balance FROM accounts ORDER BY id DESC LIMIT 1").fetchone()
            if not acc:
                return None
            return {"account_id": acc["id"], "account_name": acc["name"], "cash": float(acc["balance"] or 0),
                    "holdings": [], "market_value": 0.0, "total_asset": float(acc["balance"] or 0),
                    "total_pnl": 0.0, "pct_pnl": 0.0}
        aid, aname, cash = acc["id"], acc["name"], float(acc["balance"] or 0)
        rows = c.execute("SELECT code,name,qty,cost_price,current_price FROM positions WHERE account_id=? AND qty>0", (aid,)).fetchall()
        con.close()
        holdings = []
        for r in rows:
            code, name, qty, cost = r["code"], r["name"], int(r["qty"]), float(r["cost_price"] or 0)
            px = _last_close(code)
            if px is None or px <= 0:
                px = float(r["current_price"] or cost) or 0.0
            value = qty * px
            holdings.append({"code": code, "name": name, "qty": qty, "cost": cost,
                             "px": px, "value": value, "pnl": qty * (px - cost)})
        holdings = [h for h in holdings if h["value"] > 0]
        total_mv = sum(h["value"] for h in holdings)
        total_pnl = sum(h["pnl"] for h in holdings)
        for h in holdings:
            h["weight"] = (h["value"] / total_mv) if total_mv else 0.0
        total_asset = cash + total_mv
        return {"account_id": aid, "account_name": aname, "cash": cash, "holdings": holdings,
                "market_value": total_mv, "total_pnl": total_pnl, "total_asset": total_asset,
                "as_of": _kline_as_of(),
                "pct_pnl": (total_pnl / (total_asset - total_pnl) * 100.0) if (total_asset - total_pnl) else 0.0}
    except Exception as e:
        return {"error": str(e)}


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


def _rebalance_rows(paper):
    """把 rebalance_log 摊平成 [{date, code, side, qty, price, amt}] 行(供调仓表/详图分页)."""
    log = paper.get('rebalance_log', []) or []
    rows = []
    for r in log:
        for t in r.get('trades', []) or []:
            amt = t['qty'] * t['price']
            rows.append([r['date'], t['code'], "买入" if t['side'] == 'buy' else "卖出",
                         f'{t["qty"]:,}', f'{t["price"]:.2f}', f'{amt:,.0f}'])
    return rows


def _snapshot_holdings(holdings, date):
    """把 {code: qty} + 日期 → [{code,name,qty,px,value,weight}] 按市值降序(供环形图/卡片)."""
    if not holdings:
        return []
    codes = list(holdings)
    cmap = _close_map(codes, date)
    nmap = _names_map(codes)
    total = 0
    for c, q in holdings.items():
        px = cmap.get(c)
        if px:
            total += q * px
    rows = []
    for c, q in holdings.items():
        px = cmap.get(c)
        val = q * px if px else 0.0
        rows.append({"code": c, "name": nmap.get(c, ''), "qty": q,
                     "px": px if px is not None else 0.0, "value": val,
                     "weight": (val / total) if total else 0.0})
    rows.sort(key=lambda r: -r['value'])
    return rows


class StrategyDetailDialog(QDialog):
    """单策略详图: 大号净值曲线(vs 买持/沪深300) + 该策略完整调仓记录(分页)."""
    PER_PAGE = 100
    HEADERS = ["调仓日", "代码", "方向", "数量", "价格", "金额"]

    def __init__(self, name, paper, buyhold, hs300, as_of, parent=None):
        super().__init__(parent)
        self._name = name
        self._paper = paper
        self._rows = _rebalance_rows(paper)
        self._page = 0
        self.setWindowTitle(f"单策略详图 · {name}")
        self.resize(dp(960), dp(780))
        self.setStyleSheet(f"background:{PAL['bg']}; color:{PAL['text']};")
        root = QVBoxLayout(self); root.setContentsMargins(dp(14), dp(12), dp(14), dp(12)); root.setSpacing(dp(10))
        # 标题
        t = QLabel(f"单策略详图 · {name}")
        t.setStyleSheet(label_ss(size=13) + f"color:{PAL['text']};")
        root.addWidget(t)
        # 摘要卡(精确指标: 总收益/年化/夏普/α/胜率/回撤)
        nav = paper.get('nav', []) or []
        m = paper.get('metrics') or {}
        ret = (nav[-1] / _INIT - 1) if nav else 0
        _f = lambda x, s="%": (f"{x*100:+.1f}{s}" if x is not None else "—")
        terms = [("累计收益", _f(m.get('total_return', ret))),
                 ("年化α", _f(m.get('alpha'), "%")),
                 ("年化收益", _f(m.get('cagr'), "%")),
                 ("夏普", f"{m.get('sharpe', 0):.2f}" if m else "—"),
                 ("胜率", _f(m.get('win_rate')) if m.get('win_rate') is not None else "—"),
                 ("最大回撤", _f(m.get('max_drawdown'))),
                 ("as_of", str(as_of or '—'))]
        sum_row = QHBoxLayout(); sum_row.setSpacing(dp(8))
        for k, val in terms:
            card = QFrame(); card.setStyleSheet(card_qss("card"))
            lo = QVBoxLayout(card); lo.setContentsMargins(dp(10), dp(8), dp(10), dp(8)); lo.setSpacing(0)
            lb = QLabel(k); lb.setStyleSheet(label_ss(size=8))
            v = QLabel(val); v.setStyleSheet(value_ss(color=PAL['accent'], size=13))
            lo.addWidget(lb); lo.addWidget(v)
            sum_row.addWidget(card, 1)
        root.addLayout(sum_row)
        # 策略条件原理(买入/持有/卖出) —— 命中用户"F/D策略条件原理"
        desc = paper.get('describe') or {}
        if desc:
            cond_frame = QFrame(); cond_frame.setStyleSheet(
                f"background:{PAL['bg']};border:1px solid {PAL['border_lo']};border-radius:6px;")
            clo = QVBoxLayout(cond_frame); clo.setContentsMargins(dp(10), dp(6), dp(10), dp(6)); clo.setSpacing(dp(2))
            def _cond_line(k, v):
                lbl = QLabel(f"{k}：{v}")
                lbl.setStyleSheet(f"color:{PAL['sub']};font-size:{fs(9)};background:transparent;")
                lbl.setWordWrap(True)
                clo.addWidget(lbl)
            hd = QLabel(f"策略原理 · {desc.get('kind', '')}")
            hd.setStyleSheet(label_ss(size=9) + f"color:{PAL['accent']};")
            clo.addWidget(hd)
            _cond_line("买入条件", desc.get('buy_condition', '—'))
            if desc.get('hold_period'):
                _cond_line("持有/调仓", desc.get('hold_period'))
            _cond_line("卖出条件", desc.get('sell_conditions', '—'))
            root.addWidget(cond_frame)
        # 大曲线(单策略 vs 基线)
        cur = QFrame(); cur.setStyleSheet(card_qss("card"))
        clo = QVBoxLayout(cur); clo.setContentsMargins(dp(10), dp(6), dp(10), dp(6))
        cl = QLabel("净值走势 · vs 买持 / 沪深300"); cl.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        clo.addWidget(cl)
        self._curve = _EquityCurve(); self._curve.setMinimumHeight(dp(300))
        series = [{'name': name, 'dates': paper.get('dates', []), 'nav': paper.get('nav', []), 'selected': True}]
        bh_abs = {'dates': buyhold.get('dates', []), 'nav': [(v * _INIT) for v in buyhold.get('nav', [])]} if buyhold else None
        self._curve.set_series(series, bh_abs, hs300)
        clo.addWidget(self._curve)
        root.addWidget(cur, 1)
        # 完整调仓记录(分页)
        tbl_frame = QFrame(); tbl_frame.setStyleSheet(card_qss("card"))
        tlo = QVBoxLayout(tbl_frame); tlo.setContentsMargins(dp(10), dp(6), dp(10), dp(6)); tlo.setSpacing(dp(4))
        tl = QLabel("调仓记录(完整 · 分页)"); tl.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        tlo.addWidget(tl)
        self._table = QTableWidget()
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False); self._table.setShowGrid(False)
        self._table.verticalHeader().setDefaultSectionSize(dp(22))
        self._table.setFont(QFont("Microsoft YaHei", _pt(9)))
        tlo.addWidget(self._table)
        pg_row = QHBoxLayout(); pg_row.setSpacing(dp(8))
        self._prev = QPushButton("◀ 上一页"); self._prev.setObjectName("indBtn")
        self._next = QPushButton("下一页 ▶"); self._next.setObjectName("indBtn")
        self._pg_label = QLabel("—"); self._pg_label.setStyleSheet(value_ss(size=9) + f"color:{PAL['sub']};")
        self._prev.clicked.connect(lambda: self._go(self._page - 1))
        self._next.clicked.connect(lambda: self._go(self._page + 1))
        pg_row.addWidget(self._prev); pg_row.addStretch(1)
        pg_row.addWidget(self._pg_label); pg_row.addStretch(1)
        pg_row.addWidget(self._next)
        tlo.addLayout(pg_row)
        root.addWidget(tbl_frame)
        self._render_page()

    def _go(self, page):
        n = max(1, (len(self._rows) + self.PER_PAGE - 1) // self.PER_PAGE)
        self._page = max(0, min(page, n - 1))
        self._render_page()

    def _render_page(self):
        rows = self._rows
        n = max(1, (len(rows) + self.PER_PAGE - 1) // self.PER_PAGE)
        self._page = min(self._page, max(0, n - 1))
        start = self._page * self.PER_PAGE
        page_rows = rows[start:start + self.PER_PAGE]
        self._table.setColumnCount(len(self.HEADERS)); self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.setRowCount(len(page_rows))
        for i, row in enumerate(page_rows):
            for j, val in enumerate(row):
                it = QTableWidgetItem(str(val))
                it.setTextAlignment(Qt.AlignCenter if j else Qt.AlignLeft)
                self._table.setItem(i, j, it)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._pg_label.setText(f"第 {self._page + 1} / {n} 页 · 共 {len(rows)} 条")
        self._prev.setEnabled(self._page > 0)
        self._next.setEnabled(self._page < n - 1)


class _StockTile(QFrame):
    """单只股票的持仓卡片(代码+权重 / 名称 / 数量+现价 / 市值). 固定高三行, 紧凑高级."""

    def __init__(self, h, color, parent=None):
        super().__init__(parent)
        self.setStyleSheet(card_qss('card'))
        self.setFixedHeight(dp(86))
        lo = QVBoxLayout(self); lo.setContentsMargins(dp(11), dp(9), dp(11), dp(9)); lo.setSpacing(dp(2))
        # 行1: 代码(白, 大) + 权重%(彩色, 右)
        top = QHBoxLayout(); top.setSpacing(dp(6))
        code = QLabel(h['code']); code.setStyleSheet(value_ss(size=12) + f"color:{PAL['text']};")
        wt = QLabel(f"{h['weight']*100:.1f}%")
        wt.setStyleSheet(value_ss(color=PAL['gold'], size=11))
        top.addWidget(code); top.addStretch(1); top.addWidget(wt)
        lo.addLayout(top)
        # 行2: 名称(金色小 label)
        nm = QLabel(h.get('name', '')); nm.setStyleSheet(label_ss(size=10, gold=True))
        lo.addWidget(nm)
        # 行3: 数量 · 现价 · 市值(灰, 一行紧凑)
        meta = QLabel(f"数量 {h['qty']:,}   现价 {h['px']:.2f}")
        meta.setStyleSheet(value_ss(size=9) + f"color:{PAL['sub']};")
        lo.addWidget(meta)
        val = QLabel(f"市值 {h['value']:,.0f}")
        val.setStyleSheet(value_ss(size=9) + f"color:{PAL['faint']};")
        lo.addWidget(val)


class _Donut(QWidget):
    """权重环形图(主题 token 配色, 纯色段安全)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(dp(156))
        self._seg = []
        self._t = ""
        self._b = ""

    def set_data(self, seg, top, bot):
        self._seg = seg; self._t = top; self._b = bot; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        total = sum(v for v, _c in self._seg) or 1.0
        r = min(w, h) * 0.45
        cx, cy = w // 2, h // 2
        p.setPen(Qt.NoPen); p.setBrush(QColor(PAL['c_mid']))
        p.drawEllipse(QPointF(cx, cy), r, r)
        a0 = 90 * 16
        for v, c in self._seg:
            span = -int(360 * 16 * v / total)
            p.setPen(Qt.NoPen); p.setBrush(c)
            p.drawPie(QRectF(cx - r, cy - r, r * 2, r * 2), a0, span)
            a0 += span
        inner = r * 0.62
        p.setBrush(QColor(PAL['bg']))
        p.drawEllipse(QPointF(cx, cy), inner, inner)
        p.setPen(QColor(PAL['text'])); p.setFont(QFont("Microsoft YaHei", _pt(11)))
        fm1 = p.fontMetrics()
        p.drawText(QPointF(cx - fm1.width(self._t) / 2, cy - _pt(2)), self._t)
        p.setPen(QColor(PAL['sub'])); p.setFont(QFont("Microsoft YaHei", _pt(8)))
        fm2 = p.fontMetrics()
        p.drawText(QPointF(cx - fm2.width(self._b) / 2, cy + _pt(14)), self._b)
        p.end()


class _HoldingsView(QWidget):
    """直观持仓: 权重环形图 + 股票卡片网格(2列, 可滚动)."""

    PALETTE = ['accent', 'up', 'down', 'text', 'border_hi', 'sub', 'faint', 'grid']

    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self); lo.setContentsMargins(dp(2), dp(2), dp(2), dp(2)); lo.setSpacing(dp(6))
        self._donut = _Donut(); lo.addWidget(self._donut)
        self._legend = QLabel(''); self._legend.setStyleSheet(value_ss(size=8) + f"color:{PAL['sub']};")
        lo.addWidget(self._legend)
        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(dp(2), dp(2), dp(2), dp(2)); self._grid.setSpacing(dp(6))
        self._scroll.setWidget(self._grid_host)
        lo.addWidget(self._scroll, 1)

    def _color(self, i):
        return QColor(PAL[self.PALETTE[i % len(self.PALETTE)]])

    def set_holdings(self, holdings):
        while self._grid.count():
            it = self._grid.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if not holdings:
            self._donut.set_data([], "—", "无持仓")
            self._legend.setText("暂无持仓(模拟盘今日)")
            return
        total = sum(h['value'] for h in holdings)
        seg = [(h['value'], self._color(i)) for i, h in enumerate(holdings)]
        self._donut.set_data(seg, f"{total:,.0f}", f"{len(holdings)} 只")
        self._legend.setText("   ".join(f"{h['code']}·{h['weight']*100:.0f}%" for h in holdings[:10]))
        cols = 2
        for i, h in enumerate(holdings):
            tile = _StockTile(h, self._color(i))
            self._grid.addWidget(tile, i // cols, i % cols)
        self._grid.setColumnStretch(0, 1); self._grid.setColumnStretch(1, 1)
        # 固定行高: 卡片已 setFixedHeight, 行不 stretch, 滚动区按内容自然高度排列
        for rr in range((len(holdings) + cols - 1) // cols):
            self._grid.setRowMinimumHeight(rr, dp(92))
            self._grid.setRowStretch(rr, 0)


class HoldingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.db_path = KLINE_DB
        self.on_open_kline = None
        self.on_status = None
        self.setStyleSheet(f"background:{PAL['bg']}")
        self._data = {"runs": {}, "buyhold": {}, "selected": None}
        self._mode = 'live'
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
        t = QLabel("持仓"); t.setStyleSheet(style_title() + f"color:{PAL['text']};")
        self._cards_lo.addWidget(t)
        cap = QLabel("实时持仓(模拟盘) · 历史持仓(纸面盘回测) 可切换")
        cap.setStyleSheet(label_ss(size=10) + f"color:{PAL['sub']};")
        self._cards_lo.addWidget(cap)
        # 实时/历史 切换(分段, 不占满宽)
        mode_row = QHBoxLayout(); mode_row.setSpacing(dp(6))
        self._mode_group = QButtonGroup(self); self._mode_group.setExclusive(True)
        self._mode_btns = {}
        for key, label in [("live", "实时持仓"), ("hist", "历史持仓")]:
            b = QPushButton(label); b.setCheckable(True)
            b.setProperty('mode', key)
            b.setMinimumWidth(dp(88))
            # 内联选中样式(父级 setStyleSheet 破坏全局 indBtn 背景级联, 须内联)
            b.setStyleSheet(
                f"QPushButton{{background:{PAL['c_mid']};color:{PAL['sub']};"
                f"border:1px solid {PAL['border_lo']};border-top:1px solid {PAL['border_hi']};"
                f"border-radius:{dps(6)};font-size:{fs(tr(12))};font-weight:600;padding:{dps(3)} {dps(12)};}}"
                f"QPushButton:hover{{color:{PAL['text']};border-top-color:{PAL['gold']};}}"
                f"QPushButton:checked{{background:{PAL['gold']};color:#14110B;border-color:{PAL['gold']};}}")
            self._mode_group.addButton(b); self._mode_btns[key] = b
            mode_row.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
        mode_row.addStretch()   # 不占满 → 未选中态不是大空盒
        self._cards_lo.addLayout(mode_row)
        # 页栈
        self._stack = QStackedWidget()
        self._live_page = self._build_live()
        self._hist_page = self._build_hist()
        self._stack.addWidget(self._live_page)
        self._stack.addWidget(self._hist_page)
        self._cards_lo.addWidget(self._stack, 1)

    def _build_live(self):
        """实时持仓页: 账户摘要 + 直观持仓(环形图+卡片)."""
        page = QWidget()
        lo = QVBoxLayout(page); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(dp(8))
        self._acct_row = QHBoxLayout(); self._acct_row.setSpacing(dp(8))
        self._acct_labels = {}
        for k, name in [("ta", "总资产"), ("cash", "现金"), ("mv", "持仓市值"), ("pnl", "浮动盈亏")]:
            card = QFrame(); card.setStyleSheet(card_qss("card"))
            c = QVBoxLayout(card); c.setContentsMargins(dp(11), dp(9), dp(11), dp(9)); c.setSpacing(2)
            lb = QLabel(name); lb.setStyleSheet(label_ss(size=9, gold=True))
            v = QLabel("—"); v.setStyleSheet(hero_ss(size=15))
            c.addWidget(lb); c.addWidget(v)
            self._acct_row.addWidget(card, 1)
            self._acct_labels[k] = v
        lo.addLayout(self._acct_row)
        self._acct_cap = QLabel(""); self._acct_cap.setStyleSheet(value_ss(size=9) + f"color:{PAL['sub']};")
        lo.addWidget(self._acct_cap)
        self._live_view = _HoldingsView()
        lo.addWidget(self._live_view, 1)
        return page

    def _build_hist(self):
        """历史持仓页: 策略卡片 + 摘要 + 对比曲线 + 持仓(环形图)/调仓记录."""
        page = QWidget()
        lo = QVBoxLayout(page); lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(dp(8))
        # 策略卡片
        self._chips_wrap = QWidget()
        self._chips_lo = QVBoxLayout(self._chips_wrap); self._chips_lo.setContentsMargins(0, 0, 0, 0); self._chips_lo.setSpacing(dp(6))
        self._chip_row = QHBoxLayout(); self._chip_row.setSpacing(dp(6))
        self._chips_lo.addLayout(self._chip_row)
        self._zoom_btn = QPushButton("🔍 进入单策略详图"); self._zoom_btn.setObjectName("indBtn")
        self._zoom_btn.clicked.connect(lambda: self._show_detail(self._selected_strategy()))
        self._chips_lo.addWidget(self._zoom_btn)
        lo.addWidget(self._chips_wrap)
        self._strategy_btns = {}
        self._strategy_group = QButtonGroup(page); self._strategy_group.setExclusive(True)
        # 摘要卡
        self._sum_row = QHBoxLayout(); self._sum_row.setSpacing(dp(8))
        self._sum_labels = {}
        for k, name in [("v0", "期初"), ("vend", "期末净值"), ("ret", "累计收益"),
                        ("reb", "调仓次数"), ("to", "换手率"), ("asof", "as_of")]:
            card = QFrame(); card.setStyleSheet(card_qss("card"))
            c = QVBoxLayout(card); c.setContentsMargins(dp(10), dp(8), dp(10), dp(8)); c.setSpacing(0)
            lb = QLabel(name); lb.setStyleSheet(label_ss(size=8))
            v = QLabel("—"); v.setStyleSheet(value_ss(color=PAL['accent'], size=13))
            c.addWidget(lb); c.addWidget(v)
            self._sum_row.addWidget(card, 1)
            self._sum_labels[k] = v
        lo.addLayout(self._sum_row)
        # 收益曲线
        cur = QFrame(); cur.setStyleSheet(card_qss("card"))
        clo = QVBoxLayout(cur); clo.setContentsMargins(dp(10), dp(6), dp(10), dp(6))
        cl = QLabel("收益曲线(策略对比)"); cl.setStyleSheet(label_ss(size=9) + f"color:{PAL['sub']};")
        clo.addWidget(cl)
        self._curve = _EquityCurve()
        clo.addWidget(self._curve)
        lo.addWidget(cur)
        # 表格区
        tabs = QTabWidget()
        tabs.setStyleSheet(f"QTabWidget::pane{{border:1px solid {PAL['border_lo']};}}")
        self._hx_date = QComboBox(); self._hx_date.currentIndexChanged.connect(lambda _: self._render_hold())
        self._hx_view = _HoldingsView()
        hx = QWidget(); hl = QVBoxLayout(hx); hl.setContentsMargins(dp(6), dp(6), dp(6), dp(6)); hl.setSpacing(dp(6))
        self._hx_cap = QLabel("")
        self._hx_cap.setStyleSheet(label_ss(size=10, gold=True))
        hl.addWidget(self._hx_cap)
        hl.addWidget(self._hx_date)
        hl.addWidget(self._hx_view)
        tabs.addTab(hx, "持仓(按调仓日)")
        self._reb_table = self._mk_table()
        tabs.addTab(self._reb_table, "调仓记录")
        lo.addWidget(tabs, 1)
        return page

    def _set_mode(self, mode):
        b = self._mode_btns.get(mode)
        if b: b.setChecked(True)
        self._stack.setCurrentWidget(self._live_page if mode == 'live' else self._hist_page)
        self._mode = mode
        if mode == 'live':
            self._render_live()
        else:
            self._render()

    def _render_live(self):
        info = _load_live_holdings()
        if not info or info.get('error'):
            for k in ('ta', 'cash', 'mv', 'pnl'):
                self._acct_labels[k].setText("—")
            self._acct_cap.setText("读取模拟盘持仓失败")
            self._live_view.set_holdings([])
            return
        self._acct_labels['ta'].setText(f"{info['total_asset']:,.0f}")
        self._acct_labels['cash'].setText(f"{info['cash']:,.0f}")
        self._acct_labels['mv'].setText(f"{info['market_value']:,.0f}")
        pnl = info['total_pnl']
        self._acct_labels['pnl'].setText(f"{pnl:+,.0f}")
        self._acct_labels['pnl'].setStyleSheet(value_ss(color=(PAL['up'] if pnl >= 0 else PAL['down']), size=13))
        self._acct_cap.setText(
            f"{info['account_name']} (账户 #{info['account_id']}) · {len(info['holdings'])} 只持仓 · "
            f"数据截至 {info.get('as_of') or '—'}")
        self._live_view.set_holdings(info['holdings'])

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
        # 重建策略卡片
        while self._chip_row.count():
            it = self._chip_row.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        for b in list(self._strategy_group.buttons()):
            self._strategy_group.removeButton(b)
        self._strategy_btns = {}
        sel = self._data.get('selected')
        if sel not in runs:
            sel = list(runs)[0] if runs else None
        for name in runs:
            btn = QPushButton(name)
            btn.setObjectName("indBtn"); btn.setCheckable(True)
            btn.setProperty('strategy', name)
            btn.setFont(QFont("Microsoft YaHei", _pt(8)))
            btn.setToolTip(f"{name} · 点卡片查看单策略详图")
            self._strategy_group.addButton(btn)
            self._strategy_btns[name] = btn
            self._chip_row.addWidget(btn, 1)
            btn.clicked.connect(lambda _=False, n=name: self._select_strategy(n))
        self._chips_wrap.setVisible(len(runs) > 1)
        if sel:
            b = self._strategy_btns.get(sel)
            if b: b.setChecked(True)
        self._set_mode(getattr(self, '_mode', 'live'))

    def _selected_strategy(self):
        b = self._strategy_group.checkedButton()
        return b.property('strategy') if b else None

    def _select_strategy(self, name):
        b = self._strategy_btns.get(name)
        if b: b.setChecked(True)
        self._render()
        self._show_detail(name)   # 点策略卡片 → 进入单策略详图

    def _show_detail(self, name):
        if not name:
            return
        runs = self._data.get('runs') or {}
        paper = runs.get(name)
        if not isinstance(paper, dict) or paper.get('error'):
            return
        bh = self._data.get('buyhold') or {}
        grid = paper.get('dates', []) or []
        hs300 = _load_hs300(grid) if grid else None
        dlg = StrategyDetailDialog(name, paper, bh, hs300, self._data.get('as_of'), self)
        dlg.exec_()

    def _active_paper(self):
        runs = self._data.get('runs') or {}
        name = self._selected_strategy()
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
                           'selected': name == self._selected_strategy()})
        bh = self._data.get('buyhold') or {}
        bh_abs = {'dates': bh.get('dates', []), 'nav': [(v * _INIT) for v in bh.get('nav', [])]}
        grid = series[0]['dates'] if series else []
        hs300 = _load_hs300(grid) if grid else None
        self._curve.set_series(series, bh_abs, hs300)
        if not paper or paper.get('error'):
            for k in ("v0", "vend", "ret", "reb", "to", "asof"):
                self._sum_labels[k].setText("—")
            self._hx_date.clear(); self._hx_view.set_holdings([]); self._reb_table.setRowCount(0)
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
            self._hx_view.set_holdings([]); self._hx_cap.setText(""); return
        h = dh[idx]
        holds = h.get('holdings', {})
        rows = _snapshot_holdings(holds, h['date'])
        self._hx_view.set_holdings(rows)
        # 明确标注: [策略] 于 [调仓日] 的持仓
        st = self._selected_strategy() or ""
        self._hx_cap.setText(f"{st} 于 {_fmt_date(h['date'])} 的持仓" if st else f"{_fmt_date(h['date'])} 的持仓")

    def _render_reb(self, paper):
        rows = _rebalance_rows(paper)
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


def _fmt_date(d):
    """把 'YYYYMMDD' / 'YYYY-MM-DD HH:MM:SS' 归一化为 'YYYY-MM-DD'."""
    s = str(d).strip()
    s = s[:10].replace('/', '-')
    if len(s) == 8 and s.isdigit():
        return s[:4] + "-" + s[4:6] + "-" + s[6:8]
    return s
