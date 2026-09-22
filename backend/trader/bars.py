# -*- coding: utf-8 -*-
"""K 线几何特征（棒级信号，用于**买入/卖出时点**）（借鉴 PA_Agent 的 kline_features.py）。

我们的结构特征（structure.py）回答"处在什么位置、能不能追"；本模块回答"**这根棒本身说明了什么**"：
单棒形态（实体/影线/收盘位置/相对 ATR 的波动）、与前一棒的关系（内包/外包/内-外-内/微双顶底/重叠率）、
相对 EMA20 的位置（跳空棒）、对前 5 棒区间的突破类型，以及——最实用的一条——**信号棒后续是否有跟随**
（follow-through：多头信号棒之后收盘继续走高 = 有跟随；跌破该棒开盘价 = 反向失败）。

只输出客观事实，不做形态命名（楔形/MTR 仍由模型判断），也不给买卖建议。
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from ..api.paths import KLINE_DB


def _bars(code: str, as_of: str, n: int = 60) -> list:
    try:
        con = sqlite3.connect(str(KLINE_DB))
        rows = con.execute(
            "SELECT date, open, high, low, close FROM kline_daily "
            "WHERE code=? AND date<=? ORDER BY date DESC LIMIT ?",
            (str(code), str(as_of).replace("-", "")[:8], int(n))).fetchall()
        con.close()
        return [(str(r[0]), float(r[1] or 0), float(r[2] or 0), float(r[3] or 0), float(r[4] or 0))
                for r in reversed(rows) if r[4]]
    except Exception:
        return []


def _atr(bars: list, n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(len(bars) - n, len(bars)):
        _, _, h, l, c = bars[i]
        pc = bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    trs = [x for x in trs if x > 0]
    return sum(trs) / len(trs) if trs else None


def _ema(vals: list, n: int = 20) -> Optional[float]:
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _classify(o: float, h: float, l: float, c: float,
              prev: Optional[tuple] = None) -> dict:
    """单棒形态 + 与前一棒的关系。"""
    rng = h - l
    body = abs(c - o)
    body_ratio = round(body / rng, 3) if rng > 0 else None
    upper_wick = round((h - max(o, c)) / rng, 3) if rng > 0 else None
    lower_wick = round((min(o, c) - l) / rng, 3) if rng > 0 else None
    close_pos = round((c - l) / rng, 3) if rng > 0 else None
    kind = "flat"
    if prev is not None:
        if h <= prev[2] and l >= prev[3]:
            kind = "inside"                       # 内包：波动收敛
        elif h >= prev[2] and l <= prev[3]:
            kind = "outside_bull" if c >= o else "outside_bear"   # 外包：变盘
    if kind == "flat" and body_ratio is not None and close_pos is not None:
        if body_ratio <= 0.25:
            kind = "doji"
        elif c > o and close_pos >= 0.65:
            kind = "trend_bull"                   # 收盘在高位：强多头棒
        elif c < o and close_pos <= 0.35:
            kind = "trend_bear"
        else:
            kind = "other"
    return {"kind": kind, "body_ratio": body_ratio, "upper_wick": upper_wick,
            "lower_wick": lower_wick, "close_pos": close_pos,
            "direction": "阳线" if c > o else ("阴线" if c < o else "平")}


def compute(code: str, as_of: str, n: int = 40) -> dict:
    """算最近 n 根的棒级几何 + 最后 3 根的详情。"""
    bars = _bars(code, as_of, n=max(60, n + 20))
    if len(bars) < 25:
        return {"ok": False, "reason": f"K线不足（{len(bars)} 根）"}
    atr = _atr(bars)
    ema20 = _ema([b[4] for b in bars], 20)
    seq = []
    for i in range(len(bars) - n, len(bars)):
        d, o, h, l, c = bars[i]
        prev = bars[i - 1] if i > 0 else None
        info = _classify(o, h, l, c, prev)
        # 重叠率（与前一棒）
        ov = None
        if prev:
            rng = min(h - l, prev[2] - prev[3])
            if rng > 0:
                ov = round(max(0.0, min(1.0, (min(h, prev[2]) - max(l, prev[3])) / rng)), 3)
        # 内-外-内（IOI）：连续三根的运动收敛再放大再收敛
        ioi = False
        if i >= 2:
            a, b_, cbar = bars[i - 2], bars[i - 1], bars[i]
            ioi = (b_[2] > a[2] and b_[3] < a[3]) and (cbar[2] < b_[2] and cbar[3] > b_[3])
        # 微双底/微双顶：两个相邻低（高）点足够接近。
        # PA_Agent 用 2% ATR（期货/外汇 tick 级口径），A 股日线过严 → 取 20% ATR
        micro = "none"
        if prev and atr:
            tol = atr * 0.2
            if abs(l - prev[3]) <= tol:
                micro = "MDB"     # micro double bottom
            elif abs(h - prev[2]) <= tol:
                micro = "MDT"     # micro double top
        # 跳空棒：整根在 EMA20 一侧
        gap = "none"
        if ema20:
            if l > ema20:
                gap = "bull_gap"
            elif h < ema20:
                gap = "bear_gap"
        # 对前 5 棒区间的突破
        bp = "none"
        if i >= 5:
            prev5 = bars[i - 5:i]
            if h > max(x[2] for x in prev5) and l < min(x[3] for x in prev5):
                bp = "both"
            elif h > max(x[2] for x in prev5):
                bp = "up"
            elif l < min(x[3] for x in prev5):
                bp = "down"
        seq.append({"date": d, **info, "overlap_prev": ov, "ioi": ioi, "micro_double": micro,
                    "gap_vs_ema20": gap, "breakout_prev5": bp,
                    "range_atr": round((h - l) / atr, 2) if atr else None})
    # follow-through：对新近的"信号棒"（趋势棒/外包棒）看后续 1-2 根是否跟随
    ft = "pending"
    if len(bars) >= 4:
        sig = bars[-3]           # 用倒数第 3 根当信号棒，后面有 2 根可判
        d_, o, h, l, c = sig
        direction = 1 if c > o else (-1 if c < o else 0)
        newer = bars[-2:]
        if direction:
            same = sum(1 for b in newer if (b[4] > c if direction > 0 else b[4] < c))
            opp = sum(1 for b in newer if (b[4] < o if direction > 0 else b[4] > o))
            ft = "yes" if same else ("failed" if opp else "no")
    # 连续同向计数（3 连阳/连阴）
    streak = 0
    for b in reversed(bars):
        if b[4] > b[1]:
            if streak >= 0:
                streak += 1
            else:
                break
        elif b[4] < b[1]:
            if streak <= 0:
                streak -= 1
            else:
                break
        else:
            break
    legs = leg_counts(bars)
    return {"ok": True, "as_of": as_of, "atr14": round(atr, 3) if atr else None,
            "leg_counts": legs,
            "ema20": round(ema20, 3) if ema20 else None,
            "last": seq[-1] if seq else {}, "prev": seq[-2] if len(seq) > 1 else {},
            "recent": seq[-6:],
            "follow_through": ft, "streak": streak,
            "note": ("follow_through=yes 表示信号棒之后收盘继续同向（跟随确认）；"
                     "failed 表示反向吞掉信号棒（信号失效）")}


def leg_counts(bars: list) -> dict:
    """H1/H2/L1/L2 计数（借鉴 PA_Agent 文件19）：以"突破前一棒极点"为触发。

    上涨背景：High1 = 第一腿回撤后第一根突破前棒高点的做多触发；High2 = 第二腿之后再次触发。
    下跌背景对称。H3/L3 常演变为楔形，不宜当 H2 用（这里只给到计数，判断留给模型）。
    """
    if len(bars) < 12:
        return {"label": "", "note": ""}
    # 最近 12 根里找"极点"作为起点
    tail = bars[-12:]
    hi_i = max(range(len(tail)), key=lambda i: tail[i][2])
    lo_i = min(range(len(tail)), key=lambda i: tail[i][3])
    def _count_from(start: int, up: bool) -> tuple:
        n, weak = 0, False
        for i in range(start + 1, len(tail)):
            o, h, l, c = tail[i][1], tail[i][2], tail[i][3], tail[i][4]
            prev = tail[i - 1]
            rng = h - l
            if up:
                trig = h > prev[2] and c > o
            else:
                trig = l < prev[3] and c < o
            if trig:
                n += 1
                body = abs(c - o) / rng if rng > 0 else 0
                wick = ((h - max(o, c)) / rng if up else (min(o, c) - l) / rng) if rng > 0 else 0
                weak = body < 0.4 or wick > 0.4
        return n, weak
    # 谁更近：从高点回撤（找 H 计数）还是从低点反弹（找 L 计数）
    if hi_i > lo_i:
        n, weak = _count_from(hi_i, up=True)
        if n:
            return {"label": f"H{min(n, 3)}", "count": n, "weak": weak,
                    "note": f"自最近高点回撤后的第 {n} 次突破前棒高点"
                            + ("（信号棒偏弱：实体小/上影长，按资料宜等 H2 或更明确信号）" if weak else "")}
        return {"label": "回撤中（尚未出现做多触发）", "count": 0, "weak": False, "note": ""}
    n, weak = _count_from(lo_i, up=False)
    if n:
        return {"label": f"L{min(n, 3)}", "count": n, "weak": weak,
                "note": f"自最近低点反弹后的第 {n} 次跌破前棒低点"}
    return {"label": "反弹中（尚未出现做空触发）", "count": 0, "weak": False, "note": ""}


def render(d: dict, name: str = "") -> str:
    if not d or not d.get("ok"):
        return f"{name} 棒级：数据不足"
    L = d.get("last") or {}
    P = d.get("prev") or {}
    parts = [f"最新棒 {L.get('date')} {L.get('direction')}/{L.get('kind')}",
             f"实体占比 {L.get('body_ratio')}", f"收盘位置 {L.get('close_pos')}",
             f"波动 {L.get('range_atr')}×ATR"]
    if L.get("overlap_prev") is not None:
        parts.append(f"与前棒重叠 {L.get('overlap_prev')}")
    if L.get("micro_double") and L["micro_double"] != "none":
        parts.append("微双底 MDB" if L["micro_double"] == "MDB" else "微双顶 MDT")
    if L.get("ioi"):
        parts.append("内-外-内(IOI)")
    if L.get("gap_vs_ema20") != "none":
        parts.append("EMA20 上方跳空棒" if L["gap_vs_ema20"] == "bull_gap" else "EMA20 下方跳空棒")
    if L.get("breakout_prev5") != "none":
        parts.append({"up": "突破前5棒高点", "down": "跌破前5棒低点", "both": "同时突破上下沿"}[L["breakout_prev5"]])
    parts.append(f"信号棒跟随 {d.get('follow_through')}")
    lc = d.get("leg_counts") or {}
    if lc.get("label"):
        parts.append(str(lc["label"]))
    if abs(int(d.get("streak") or 0)) >= 2:
        parts.append(f"{'连阳' if d['streak'] > 0 else '连阴'} {abs(d['streak'])} 根")
    return f"{name} 棒级：" + "；".join(str(x) for x in parts)
