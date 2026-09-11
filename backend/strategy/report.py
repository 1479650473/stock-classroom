# -*- coding: utf-8 -*-
"""回测报告生成（自包含 HTML，无新依赖）。

借鉴 Qbot 里 quantstats 的报告口径（KPI + 净值曲线 + 回撤 + 月度收益热力图 + 交易明细），
但用纯 Python 生成内联 SVG，不引入 matplotlib/seaborn，便于桌面版直接打开/导出。

对外接口：
    build_report(title, equity, dates, metrics=None, trades=None, notes=None) -> str(HTML)
    - equity: 净值序列（1.0 起步）或日收益序列（returns=True）
    - metrics: 可选，已算好的指标 dict（缺失的会按净值现算）
"""
from __future__ import annotations

import datetime as _dt
import html
import math
from typing import Dict, List, Optional, Sequence

TRADING_DAYS = 244


def _fmt_pct(v: Optional[float], digits: int = 2) -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return "—"
    return f"{v * 100:+.{digits}f}%"


def _fmt_num(v: Optional[float], digits: int = 2) -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return "—"
    return f"{v:.{digits}f}"


def _to_equity(series: Sequence[float]) -> List[float]:
    """输入日收益或净值，统一成净值序列（1.0 起步）。"""
    xs = [float(x) for x in series]
    if not xs:
        return []
    looks_like_nav = xs[0] > 0.5 and min(xs) > 0.1
    if looks_like_nav:
        base = xs[0] or 1.0
        return [x / base for x in xs]
    out, nav = [], 1.0
    for r in xs:
        nav *= (1.0 + r)
        out.append(nav)
    return out


def _max_drawdown(eq: Sequence[float]) -> float:
    peak, mdd = -1e9, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1.0 - v / peak)
    return mdd


def _daily_returns(eq: Sequence[float]) -> List[float]:
    out = []
    for i in range(1, len(eq)):
        prev = eq[i - 1]
        out.append(eq[i] / prev - 1.0 if prev else 0.0)
    return out


def compute_metrics(eq: Sequence[float], rf_annual: float = 0.0) -> Dict[str, float]:
    rets = _daily_returns(eq)
    n = len(rets) or 1
    total = (eq[-1] - 1.0) if eq else 0.0
    ann = (eq[-1] ** (TRADING_DAYS / n) - 1.0) if eq and eq[-1] > 0 else -1.0
    mu = sum(rets) / n if rets else 0.0
    sd = (sum((r - mu) ** 2 for r in rets) / n) ** 0.5 if rets else 0.0
    downside = [r for r in rets if r < 0]
    dsd = (sum(r * r for r in downside) / len(downside)) ** 0.5 if downside else sd
    mdd = _max_drawdown(eq)
    return {
        "total_return": total,
        "annual_return": ann,
        "volatility": sd * math.sqrt(TRADING_DAYS),
        "sharpe": ((ann - rf_annual) / (sd * math.sqrt(TRADING_DAYS))) if sd > 0 else 0.0,
        "sortino": ((ann - rf_annual) / (dsd * math.sqrt(TRADING_DAYS))) if dsd > 0 else 0.0,
        "max_drawdown": mdd,
        "calmar": (ann / mdd) if mdd > 0 else 0.0,
        "win_rate": (sum(1 for r in rets if r > 0) / n) if rets else 0.0,
        "days": float(n),
    }


def _sparkline(eq: Sequence[float], width: int = 900, height: int = 220) -> str:
    """净值曲线 + 回撤阴影（内联 SVG）。"""
    if len(eq) < 2:
        return ""
    lo, hi = min(eq), max(eq)
    rng = (hi - lo) or 1e-9
    n = len(eq)
    pts = []
    for i, v in enumerate(eq):
        x = i / (n - 1) * width
        y = height - (v - lo) / rng * (height - 20) - 10
        pts.append(f"{x:.1f},{y:.1f}")
    # 回撤区域
    peak = -1e9
    dd_pts = []
    for i, v in enumerate(eq):
        peak = max(peak, v)
        x = i / (n - 1) * width
        y = height - (v - lo) / rng * (height - 20) - 10
        yp = height - (peak - lo) / rng * (height - 20) - 10
        dd_pts.append(f"{x:.1f},{y:.1f}")
    line = " ".join(pts)
    area = f"0,{height} " + line + f" {width},{height}"
    return f"""<svg viewBox="0 0 {width} {height}" class="chart" preserveAspectRatio="none">
  <polygon points="{area}" fill="url(#g1)" opacity="0.35"/>
  <polyline points="{line}" fill="none" stroke="#d4a574" stroke-width="2"/>
  <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#d4a574"/><stop offset="100%" stop-color="transparent"/>
  </linearGradient></defs>
</svg>"""


def bar_chart(labels, values, width: int = 900, height: int = 200,
              pos_color: str = "#ff6b6b", neg_color: str = "#2ec27e") -> str:
    """分组收益柱状图（内联 SVG，正值/负值双色）。"""
    if not values:
        return ""
    vmax = max(abs(float(v)) for v in values) or 1e-9
    n = len(values)
    gap = 6
    bw = max(6, (width - gap * (n + 1)) / max(1, n))
    bars = []
    zero = height / 2
    for i, (lab, v) in enumerate(zip(labels, values)):
        v = float(v)
        h = abs(v) / vmax * (height / 2 - 14)
        x = gap + i * (bw + gap)
        y = zero - h if v >= 0 else zero
        color = pos_color if v >= 0 else neg_color
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="{color}" rx="2"/>')
        bars.append(f'<text x="{x + bw / 2:.1f}" y="{height - 4:.1f}" fill="#8b929b" '
                    f'font-size="10" text-anchor="middle">{html.escape(str(lab))}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" class="chart" preserveAspectRatio="none">'
            f'<line x1="0" y1="{zero}" x2="{width}" y2="{zero}" stroke="#23262c" stroke-width="1"/>'
            + "".join(bars) + "</svg>")


def _monthly_table(eq: Sequence[float], dates: Optional[Sequence[str]]) -> str:
    """月度收益热力图（按净值差算月收益）。"""
    if not dates or len(dates) != len(eq):
        return ""
    buckets: Dict[str, List[float]] = {}
    for d, v in zip(dates, eq):
        key = str(d).replace("-", "")[:6]
        buckets.setdefault(key, []).append(v)
    months = sorted(buckets)
    if not months:
        return ""
    years: Dict[str, Dict[str, float]] = {}
    for m in months:
        vals = buckets[m]
        first = vals[0]
        prev_month_end = None
        years.setdefault(m[:4], {})[m[4:6]] = vals[-1] / first - 1.0
        _ = prev_month_end
    head = "".join(f"<th>{i:02d}月</th>" for i in range(1, 13)) + "<th>全年</th>"
    rows = []
    for y in sorted(years):
        cells = []
        prod = 1.0
        for mm in range(1, 13):
            v = years[y].get(f"{mm:02d}")
            if v is None:
                cells.append("<td class='na'>—</td>")
                continue
            prod *= (1.0 + v)
            cls = "pos" if v > 0 else ("neg" if v < 0 else "")
            cells.append(f"<td class='{cls}'>{v * 100:+.1f}%</td>")
        tot = prod - 1.0
        cells.append(f"<td class='{'pos' if tot > 0 else 'neg'} tot'>{tot * 100:+.1f}%</td>")
        rows.append(f"<tr><th>{y}</th>{''.join(cells)}</tr>")
    return f"<table class='grid'><thead><tr><th>年份</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build_report(title: str, series: Sequence[float], dates: Optional[Sequence[str]] = None,
                 metrics: Optional[Dict[str, float]] = None, trades: Optional[List[dict]] = None,
                 notes: Optional[str] = None, subtitle: str = "") -> str:
    eq = _to_equity(series)
    m = dict(compute_metrics(eq))
    if metrics:
        for k, v in metrics.items():
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                m[k] = float(v)
    cards = [
        ("累计收益", _fmt_pct(m.get("total_return"))),
        ("年化收益", _fmt_pct(m.get("annual_return"))),
        ("最大回撤", _fmt_pct(-abs(m.get("max_drawdown") or 0.0))),
        ("夏普", _fmt_num(m.get("sharpe"))),
        ("Sortino", _fmt_num(m.get("sortino"))),
        ("Calmar", _fmt_num(m.get("calmar"))),
        ("年化波动", _fmt_pct(m.get("volatility"))),
        ("日胜率", _fmt_pct(m.get("win_rate"), 1)),
    ]
    if m.get("ex_ann") is not None:
        cards.insert(2, ("超额年化", _fmt_pct(m.get("ex_ann"))))
    if m.get("turnover") is not None:
        cards.append(("换手（日）", _fmt_num(m.get("turnover"))))
    cards_html = "".join(
        f"<div class='kpi'><div class='k'>{html.escape(k)}</div><div class='v'>{v}</div></div>"
        for k, v in cards)
    trades_html = ""
    if trades:
        rows = []
        for t in trades[:60]:
            rows.append("<tr>" + "".join(
                f"<td>{html.escape(str(t.get(k, '')))}</td>"
                for k in ("date", "code", "name", "side", "qty", "price", "pnl", "pnl_pct", "reason")) + "</tr>")
        trades_html = (
            "<h2>交易明细（前 60 条）</h2><table class='grid'><thead><tr>"
            "<th>日期</th><th>代码</th><th>名称</th><th>方向</th><th>数量</th><th>价格</th>"
            "<th>盈亏</th><th>盈亏%</th><th>原因</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")
    gen = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>{html.escape(title)}</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; padding:28px 32px; background:#0b0d11; color:#e6e8ea;
        font:14px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
 h1 {{ font-size:20px; margin:0 0 4px; color:#d4a574; }}
 .sub {{ color:#8b929b; font-size:12px; margin-bottom:18px; }}
 .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px;
          background:#23262c; border-radius:10px; overflow:hidden; margin-bottom:20px; }}
 .kpi {{ background:#14171c; padding:12px 16px; }}
 .kpi .k {{ font-size:11px; color:#8b929b; }}
 .kpi .v {{ font-size:18px; font-weight:700; margin-top:4px; }}
 h2 {{ font-size:14px; margin:22px 0 8px; color:#c9ccd1; font-weight:600; }}
 .chart {{ width:100%; height:220px; background:#14171c; border-radius:10px; }}
 table.grid {{ border-collapse:collapse; width:100%; font-size:12px; background:#14171c; border-radius:10px; overflow:hidden; }}
 table.grid th, table.grid td {{ padding:6px 10px; text-align:right; border-bottom:1px solid #23262c; }}
 table.grid th:first-child, table.grid td:first-child {{ text-align:left; }}
 table.grid thead th {{ color:#8b929b; font-weight:600; }}
 td.pos, td.tot.pos {{ color:#ff6b6b; }}
 td.neg, td.tot.neg {{ color:#2ec27e; }}
 td.na {{ color:#3a3f46; }}
 td.tot {{ font-weight:700; }}
 .notes {{ margin-top:18px; padding:12px 16px; background:#14171c; border-radius:10px; color:#a9aeb6; font-size:12px; }}
 footer {{ margin-top:22px; color:#5d636b; font-size:11px; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(subtitle)} · 生成于 {gen} · 交易日 {int(m.get('days') or 0)} 天</div>
<div class="kpis">{cards_html}</div>
<h2>净值曲线</h2>
{_sparkline(eq)}
{('<h2>月度收益</h2>' + _monthly_table(eq, dates)) if dates else ''}
{trades_html}
{('<div class="notes">' + notes + '</div>') if notes else ''}
<footer>stock-classroom · 报告由后端内联生成（不依赖第三方绘图库）</footer>
</body></html>"""
