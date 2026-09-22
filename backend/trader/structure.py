# -*- coding: utf-8 -*-
"""价格结构特征（确定性的"客观事实"，供模型引用而不是自己数）。

借鉴 PA_Agent 的 `market_features.py`：**只算低歧义的事实**（区间位置、波段结构、
突破质量、回撤深度、重叠/粘滞度），复杂形态（楔形、MTR 等）仍交给模型判断。
我们在其基础上按 A 股日线口径重写，并补两项自用字段：

    position / zone      收盘在近 N 日包络中的分位与区位（上/中/下三分之一）
    range_width_atr      区间宽度（×ATR14）—— 跨股票可比的"振幅"度量
    dist_high/low_atr    距上下沿几个 ATR —— 比百分比更可比的"空间"度量
    swing_structure      波段结构标签（上升 HH/HL、下降 LH/LL、区间、未定）
    pullback_atr         自最近极点回撤（×ATR）
    breakout_quality     对 20 日箱体的突破质量：none/wick_probe/close_breakout/
                         failed/testing/surviving（决定"能不能追"）
    overlap_mean_10      近 10 根平均实体重叠率（越高越"磨"）
    barbwire_score       十字星+内包占比 + 重叠的综合分（≥0.62 视为铁丝网/横盘粘滞）
    gap_ma20_atr         收盘距 20 日均线几个 ATR（偏离度）

所有函数 as-of 安全：只读 `date <= as_of` 的 K 线。
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from ..api.paths import KLINE_DB

LOOKBACK = 60          # 区间包络回看
BARBWIRE_THRESHOLD = 0.62
#: 紧凑度（最近 10 根区间宽度 ÷ 平均波段高度）阈值：按本库 200 只 A 股日线实测的 p25/p50
COMPACT_TIGHT = 0.98
COMPACT_MID = 1.32


def _bars(code: str, as_of: str, n: int = 120) -> list:
    """取 as_of（含）之前最近 n 根日线（qfq）：[(date, open, high, low, close), ...] 升序。"""
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


def _swings(bars: list, k: int = 3) -> list:
    """简单枢轴：左右各 k 根都不超过它 → 摆动高/低点。返回 [{'i','kind','price'}] 升序。"""
    out = []
    for i in range(k, len(bars) - k):
        h = bars[i][2]
        l = bars[i][3]
        left = bars[i - k:i]
        right = bars[i + 1:i + 1 + k]
        if all(h >= b[2] for b in left + right):
            out.append({"i": i, "kind": "high", "price": round(h, 3)})
        elif all(l <= b[3] for b in left + right):
            out.append({"i": i, "kind": "low", "price": round(l, 3)})
    return out[-8:]


def _label_structure(swings: list) -> str:
    """按最近 4 个枢轴的高低关系给结构标签。"""
    if len(swings) < 3:
        return "未定"
    hi = [s for s in swings if s["kind"] == "high"]
    lo = [s for s in swings if s["kind"] == "low"]
    up = len(hi) >= 2 and hi[-1]["price"] > hi[-2]["price"] and len(lo) >= 2 and lo[-1]["price"] > lo[-2]["price"]
    down = len(hi) >= 2 and hi[-1]["price"] < hi[-2]["price"] and len(lo) >= 2 and lo[-1]["price"] < lo[-2]["price"]
    if up:
        return "上升（HH+HL）"
    if down:
        return "下降（LH+LL）"
    return "区间/交错"


def _overlap(bar, prev) -> Optional[float]:
    if not prev:
        return None
    _, _, h, l, _ = bar
    _, _, ph, pl, _ = prev
    rng = min(h - l, ph - pl)
    if rng <= 0:
        return None
    ov = min(h, ph) - max(l, pl)
    return max(0.0, min(1.0, ov / rng))


_CACHE: dict = {}


def compute_cached(code: str, as_of: str, lookback: int = LOOKBACK) -> dict:
    """带进程内缓存的 compute（闸门 + 工具同一交易日会重复问同一只）。"""
    key = (str(code), str(as_of)[:10], int(lookback))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    val = compute(code, as_of, lookback)
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[key] = val
    return val


def compute(code: str, as_of: str, lookback: int = LOOKBACK) -> dict:
    """算一只股票在 as_of 的结构特征。数据不足时返回 {'ok': False, 'reason': ...}。"""
    bars = _bars(code, as_of, n=max(150, lookback + 60))
    if len(bars) < 25:
        return {"ok": False, "reason": f"K线不足（{len(bars)} 根）"}
    atr = _atr(bars)
    win = bars[-lookback:] if len(bars) >= lookback else bars
    hi = max(b[2] for b in win)
    lo = min(b[3] for b in win)
    close = bars[-1][4]
    pos = (close - lo) / (hi - lo) if hi > lo else None
    zone = "上三分之一" if (pos or 0) >= 0.667 else ("下三分之一" if (pos or 1) <= 0.333 else "中部")
    swings = _swings(bars)
    struct = _label_structure(swings)
    # 回撤：自最近极点（高点或低点）到当前收盘
    pullback_atr = None
    if atr:
        last_ext = max((s["price"] for s in swings if s["kind"] == "high"), default=None)
        if last_ext and last_ext > close:
            pullback_atr = round((last_ext - close) / atr, 2)
    # 突破质量：对 20 日箱体（不含最后 1 根）
    box = bars[-21:-1]
    bq = "none"
    if len(box) >= 10 and atr:
        bh = max(b[2] for b in box)
        bl = min(b[3] for b in box)
        last = bars[-1]
        prev_close = bars[-2][4]
        if last[2] > bh and last[4] <= bh:
            bq = "wick_probe"                      # 上影试探未站稳
        elif last[4] > bh:
            closed_above = sum(1 for b in bars[-4:] if b[4] > bh)
            bq = "surviving" if closed_above >= 2 else "close_breakout"
        elif prev_close > bh and last[4] <= bh:
            bq = "failed"                          # 突破次日收回
        elif bh - close <= 0.5 * atr:
            bq = "testing"                         # 贴着上沿，可能在回测
        elif last[4] < bl:
            bq = "broke_down"
    # 紧凑度 = 区间宽度 / 平均波段高度（PA_Agent 判铁丝网的主口径：<25% 铁丝网，25~35% 过渡区）
    # 紧凑度 = **最近 10 根**的区间宽度 / 平均波段高度
    # （PA_Agent 判铁丝网的主口径：<25% 铁丝网、25~35% 过渡区。
    #   注意要用"最近"的区间 —— 60 日包络宽度反映不了当前的粘滞程度。）
    compact_ratio = None
    try:
        last10 = bars[-10:]
        r10 = max(b[2] for b in last10) - min(b[3] for b in last10)
        prices = [s["price"] for s in swings] if len(swings) >= 3 else []
        legs = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        avg_leg = (sum(legs) / len(legs)) if legs else (2 * atr if atr else 0)
        if avg_leg and avg_leg > 0 and r10 > 0:
            compact_ratio = round(r10 / avg_leg, 3)
    except Exception:
        compact_ratio = None

    # 重叠 / 铁丝网
    ovs = [o for o in (_overlap(bars[i], bars[i - 1]) for i in range(len(bars) - 10, len(bars))) if o is not None]
    overlap10 = round(sum(ovs) / len(ovs), 3) if ovs else None
    doji_inside = 0
    for i in range(len(bars) - 10, len(bars)):
        _, o, h, l, c = bars[i]
        rng = h - l
        is_doji = rng > 0 and abs(c - o) / rng <= 0.25
        inside = i > 0 and bars[i][2] <= bars[i - 1][2] and bars[i][3] >= bars[i - 1][3]
        if is_doji or inside:
            doji_inside += 1
    barbwire = round(0.5 * (overlap10 or 0) + 0.5 * (doji_inside / 10), 3)
    gap_ma20 = None
    if atr and len(bars) >= 20:
        ma20 = sum(b[4] for b in bars[-20:]) / 20
        gap_ma20 = round((close - ma20) / atr, 2)
    return {"ok": True, "as_of": as_of, "bars": len(bars), "close": round(close, 3),
            "atr14": round(atr, 3) if atr else None,
            "range_high": round(hi, 3), "range_low": round(lo, 3), "lookback": len(win),
            "position": round(pos, 3) if pos is not None else None, "zone": zone,
            "range_width_atr": round((hi - lo) / atr, 2) if atr else None,
            "dist_high_atr": round((hi - close) / atr, 2) if atr else None,
            "dist_low_atr": round((close - lo) / atr, 2) if atr else None,
            "swing_structure": struct,
            "swings": [{"kind": s["kind"], "price": s["price"]} for s in swings[-4:]],
            "pullback_atr": pullback_atr,
            "breakout_quality": bq,
            "overlap_mean_10": overlap10,
            "barbwire_score": barbwire,
            "compact_ratio": compact_ratio,
            # 阈值按本库实测分布定（200 只 A 股日线：p25=0.98、p50=1.32），
            # 不照搬原文的 0.25/0.35 —— 那是期货/外汇 tick 口径，量纲不同不可直接用。
            "compact_zone": ("紧凑/粘滞（<p25）" if (compact_ratio or 9) < COMPACT_TIGHT
                             else ("过渡区（p25~p50，只等突破）" if (compact_ratio or 9) < COMPACT_MID
                                   else "正常波动")),
            "barbwire": (barbwire >= BARBWIRE_THRESHOLD) or ((compact_ratio or 9) < COMPACT_TIGHT),
            "gap_ma20_atr": gap_ma20}


def render(d: dict, name: str = "") -> str:
    """压成一行中文（放进闸门/工具返回，避免长表格）。"""
    if not d or not d.get("ok"):
        return f"{name} 结构：数据不足"
    parts = [
        f"位置 {d['position']}（{d['zone']}）",
        f"距上沿 {d['dist_high_atr']}×ATR",
        f"结构 {d['swing_structure']}",
    ]
    if d.get("pullback_atr"):
        parts.append(f"自高点回撤 {d['pullback_atr']}×ATR")
    parts.append(f"突破质量 {d['breakout_quality']}")
    if d.get("compact_ratio") is not None:
        parts.append(f"紧凑度 {d['compact_ratio']}（{d.get('compact_zone')}）")
    if d.get("barbwire"):
        parts.append(f"铁丝网/粘滞（分数 {d['barbwire_score']}）")
    if d.get("gap_ma20_atr") is not None:
        parts.append(f"距MA20 {d['gap_ma20_atr']}×ATR")
    return f"{name} 结构：" + "；".join(parts)


def render_multi(code: str, as_of: str, name: str = "") -> str:
    return render(compute(code, as_of), name or code)
