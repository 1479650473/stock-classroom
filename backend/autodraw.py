# -*- coding: utf-8 -*-
"""程序自动画线 / 自动技术分析（面向 K 线界面）。

这是"券商软件没有的事"：把确定性的事实（摆动点、支撑阻力带、趋势线/通道、箱体、
突破事件）算出来之后**直接画在图上**，并给出一段中文解读。所有事实只依赖
`date <= 最后一根 bar`，不存在前视。

与 AI 操盘手的关系：日线的结构标签/突破质量与 `trader.structure`、`trader.routing`
同源（复用同一套计算），所以"图上看到的"和"操盘手看到的"是一致的。

对外只暴露 `analyze(code, period='daily', days=250)` → dict（见文件末 main 打印示例）。
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

import sqlite3

# 允许 `python -m backend.autodraw` 直接跑（与 server 一致的路径引导：backend/ 进 sys.path）
_BD = os.path.dirname(os.path.abspath(__file__))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from api.paths import KLINE_DB

# ---- 参数（按 A 股日线口径；不照搬外文资料阈值）----
PIVOT_K = 3              # 左右各 3 根确认摆动点
LEVEL_TOL_ATR = 0.6      # 聚类容差（×ATR）
LEVEL_TOL_PCT = 0.012    # 聚类容差下限（1.2%）
MAX_LEVELS = 3           # 每侧最多画几条
SIGNAL_WINDOW = 60       # 棒级信号画线窗口（只看最近 N 根，避免糊图）
SIGNAL_STAT_WINDOW = 120  # 卡片里统计口径（更长的窗口）
BOX_LOOKBACK = 60        # 箱体回看
LINE_VIOL_TOL = 0.35     # 趋势线"被有效跌破"的容忍度（×ATR）


# ---------------------------------------------------------------- 数据
def _bars(code: str, period: str, days: int) -> List[tuple]:
    """返回升序 [(date(YYYYMMDD), o, h, l, c, v)]"""
    if period in ("weekly", "monthly"):
        from data_manager import get_period_kline
        rows = get_period_kline(code, period, days)
    else:
        from data_manager import get_kline_data
        rows = get_kline_data(code, days)
        rows = sorted(rows, key=lambda r: str(r.get("date") or ""))
    out = []
    for r in rows:
        try:
            out.append((str(r["date"]), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]), float(r.get("volume") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _atr(bars: List[tuple], n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        _, _, h, l, _, _ = bars[i]
        pc = bars[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return None
    win = trs[-n:]
    return sum(win) / len(win) or None


def _fmt_date(d: str) -> str:
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


# ---------------------------------------------------------------- 摆动点
def pivots(bars: List[tuple], k: int = PIVOT_K) -> List[dict]:
    """左右各 k 根都不过它 → 摆动高/低点。返回 [{i,date,price,kind}] 升序（含日期，供画线用）。"""
    out = []
    for i in range(k, len(bars) - k):
        h = bars[i][2]
        l = bars[i][3]
        left = bars[i - k:i]
        right = bars[i + 1:i + 1 + k]
        if all(h >= b[2] for b in left + right):
            out.append({"i": i, "date": _fmt_date(bars[i][0]), "price": round(h, 3), "kind": "high"})
        elif all(l <= b[3] for b in left + right):
            out.append({"i": i, "date": _fmt_date(bars[i][0]), "price": round(l, 3), "kind": "low"})
    return out


# ---------------------------------------------------------------- 支撑/阻力带
def levels(bars: List[tuple], pv: List[dict], atr: Optional[float], close: float) -> List[dict]:
    """摆动点价格聚类 → 支撑/阻力带（触碰次数、最近时间、力度）。"""
    if not pv:
        return []
    tol = max((atr or 0) * LEVEL_TOL_ATR, close * LEVEL_TOL_PCT)
    pools: List[dict] = []
    for p in pv:
        hit = None
        for pool in pools:
            if abs(pool["price"] - p["price"]) <= tol:
                hit = pool
                break
        if hit:
            n = hit["n"] + 1
            hit["price"] = (hit["price"] * hit["n"] + p["price"]) / n
            hit["n"] = n
            hit["last_i"] = p["i"]
            hit["last_date"] = p["date"]
            hit["kind"] = "both" if hit["kind"] != p["kind"] else hit["kind"]
        else:
            pools.append({"price": p["price"], "n": 1, "last_i": p["i"],
                          "last_date": p["date"], "kind": p["kind"]})
    # 力度：触碰次数 + 近期加权（越近越重要）
    n_bars = len(bars)
    for pool in pools:
        recency = 1.0 - (n_bars - 1 - pool["last_i"]) / max(1, n_bars)
        pool["strength"] = round(pool["n"] + recency * 1.5, 2)
        pool["price"] = round(pool["price"], 3)
        pool["dist_atr"] = round((pool["price"] - close) / atr, 2) if atr else None
        pool["role"] = "support" if pool["price"] < close else "resistance"
    # 太远的水平（>8×ATR）没有操作意义，不画；按 接近度×强度 排序取前 MAX_LEVELS 条
    pools = [p for p in pools if p["dist_atr"] is None or abs(p["dist_atr"]) <= 8]
    for p in pools:
        p["score"] = p["strength"] / (1 + abs(p["dist_atr"] or 0) * 0.6)
    pools.sort(key=lambda x: (-x["score"], -x["n"]))
    sup = [p for p in pools if p["role"] == "support"][:MAX_LEVELS]
    res = [p for p in pools if p["role"] == "resistance"][:MAX_LEVELS]
    for p in sup + res:
        p["label"] = f"{'支撑' if p['role'] == 'support' else '阻力'} {p['price']:.2f}（{p['n']} 次触碰）"
    return sup + res


# ---------------------------------------------------------------- 趋势线 / 通道 / 箱体
def _seg_violations(bars: List[tuple], i1: int, p1: float, i2: int, p2: float, atr: Optional[float],
                    side: str) -> int:
    """一段直线（两点式）后，有多少根 bar 有效穿透（超过容忍度）。side='below' 趋势线在下。"""
    if i2 <= i1:
        return 0
    slope = (p2 - p1) / (i2 - i1)
    tol = (atr or 0) * LINE_VIOL_TOL + p1 * 0.002
    bad = 0
    for i in range(i1 + 1, len(bars)):
        line_v = p1 + slope * (i - i1)
        c = bars[i][4]
        if side == "below" and c < line_v - tol:
            bad += 1
        elif side == "above" and c > line_v + tol:
            bad += 1
    return bad


def _line_current(bars: List[tuple], a: dict, b: dict) -> float:
    slope = (b["price"] - a["price"]) / max(1, b["i"] - a["i"])
    return round(b["price"] + slope * (len(bars) - 1 - b["i"]), 3)


def _parallel_channel(bars: List[tuple], pv: List[dict], tl: dict, want_kind: str,
                      label: str, side: str, atr: Optional[float]) -> Optional[dict]:
    """平行通道：过趋势线起点之后的同侧极值枢轴，斜率与趋势线一致（券商画法）。

    want_kind='high' → 上升通道上轨（过最高高点）；'low' → 下降通道下轨（过最低低点）。
    """
    i1 = tl.get("i1")
    i2 = tl.get("i2")
    if i1 is None or i2 is None:
        return None
    cands = [p for p in pv if p["kind"] == want_kind and p["i"] > i1]
    if not cands:
        return None
    e = max(cands, key=lambda p: p["price"]) if want_kind == "high"         else min(cands, key=lambda p: p["price"])
    slope = (tl["p2"]["price"] - tl["p1"]["price"]) / max(1, i2 - i1)
    if i2 <= e["i"]:
        return None
    p_at_i2 = round(e["price"] + slope * (i2 - e["i"]), 3)
    cur = round(e["price"] + slope * (len(bars) - 1 - e["i"]), 3)
    bad = _seg_violations(bars, e["i"], e["price"], i2, p_at_i2, atr, side)
    if bad > max(3, int(len(bars) * 0.08)):
        return None
    return {"label": label, "p1": {"time": e["date"], "price": e["price"]},
            "p2": {"time": tl["p2"]["time"], "price": p_at_i2},
            "current": cur, "violations": bad}


def trend_or_range(bars: List[tuple], pv: List[dict], atr: Optional[float]) -> Dict[str, object]:
    """结构判断 → 趋势线/通道（上升/下降）或箱体（区间）。

    趋势线必须同时满足：① 有效跌破根数 ≤ 2% 的 K 线（且 ≤4 根）；② 当前收盘仍在线的一侧。
    最近一对枢轴不成立时退一步用更长跨距（更稳健的斜率），都不成立 → 画箱体。
    """
    highs = [p for p in pv if p["kind"] == "high"]
    lows = [p for p in pv if p["kind"] == "low"]
    close = bars[-1][4]
    out: Dict[str, object] = {"kind": "range", "label": "区间箱体"}
    max_bad = min(4, max(1, int(len(bars) * 0.02)))

    def line_from(a: dict, b: dict, label: str, side: str, max_viol: int) -> Optional[dict]:
        bad = _seg_violations(bars, a["i"], a["price"], b["i"], b["price"], atr, side)
        if bad > max_viol:
            return None
        cur = _line_current(bars, a, b)
        tol = (atr or 0) * 0.5
        if side == "below" and close < cur - tol:      # 上升线：收盘要在线上方
            return None
        if side == "above" and close > cur + tol:      # 下降线：收盘要在线下方
            return None
        return {"label": label, "p1": {"time": a["date"], "price": a["price"]},
                "p2": {"time": b["date"], "price": b["price"]},
                "i1": a["i"], "i2": b["i"], "violations": bad, "current": cur}

    def try_trend(pts: List[dict], label: str, side: str, ch_kind: str, ch_label: str,
                  ch_side: str) -> Optional[dict]:
        """要求方向正确（上升线：低点抬高；下降线：高点降低），试最近一对/次近一对。"""
        pairs = []
        if len(pts) >= 2:
            pairs.append((pts[-2], pts[-1]))
        if len(pts) >= 3:
            pairs.append((pts[-3], pts[-1]))
        for a, b in pairs:
            d = b["price"] - a["price"]
            if side == "below" and d <= 0:
                continue
            if side == "above" and d >= 0:
                continue
            tl = line_from(a, b, label, side, max_bad)
            if tl:
                ch = _parallel_channel(bars, pv, tl, ch_kind, ch_label, ch_side, atr)
                return {"trend": tl, "channel": ch}
        return None

    if len(lows) >= 2 and len(highs) >= 2:
        up = try_trend(lows, "上升趋势线", "below", "high", "通道上轨", "above")
        if up:
            out = {"kind": "up", "label": "上升趋势（趋势线+平行通道上轨）",
                   "trend": up["trend"], "channel": up["channel"]}
            return out
        down = try_trend(highs, "下降趋势线", "above", "low", "通道下轨", "below")
        if down:
            out = {"kind": "down", "label": "下降趋势（趋势线+平行通道下轨）",
                   "trend": down["trend"], "channel": down["channel"]}
            return out
    # 区间箱体：近 BOX_LOOKBACK 根的包络
    win = bars[-BOX_LOOKBACK:] if len(bars) >= BOX_LOOKBACK else bars
    hi = max(b[2] for b in win)
    lo = min(b[3] for b in win)
    out["range"] = {"top": round(hi, 3), "bottom": round(lo, 3),
                    "from": _fmt_date(win[0][0]), "to": _fmt_date(win[-1][0]),
                    "width_atr": round((hi - lo) / atr, 2) if atr else None,
                    "label": f"箱体 {lo:.2f}~{hi:.2f}"}
    return out


# ---------------------------------------------------------------- 突破事件
def events(bars: List[tuple], atr: Optional[float], lookback: int = 120) -> List[dict]:
    """扫描「20 日新高/新低突破」是否被确认：突破后 3 根内收回 → 失败突破。"""
    out: List[dict] = []
    n = len(bars)
    start = max(21, n - lookback)
    for i in range(start, n):
        win = bars[i - 20:i]
        hh = max(b[2] for b in win)
        ll = min(b[3] for b in win)
        c = bars[i][4]
        if c > hh:
            held = all(bars[j][4] > hh - (atr or 0) * 0.3 for j in range(i + 1, min(n, i + 4)))
            if i + 3 <= n - 1 and not held:
                out.append({"time": _fmt_date(bars[i][0]), "price": round(c, 3),
                            "type": "failed_breakout", "text": "假突破（回落）"})
            elif i == n - 1:
                out.append({"time": _fmt_date(bars[i][0]), "price": round(c, 3),
                            "type": "breakout", "text": "向上突破（当日）"})
        elif c < ll:
            held = all(bars[j][4] < ll + (atr or 0) * 0.3 for j in range(i + 1, min(n, i + 4)))
            if i + 3 <= n - 1 and not held:
                out.append({"time": _fmt_date(bars[i][0]), "price": round(c, 3),
                            "type": "failed_breakout", "text": "假跌破（收复）"})
            elif i == n - 1:
                out.append({"time": _fmt_date(bars[i][0]), "price": round(c, 3),
                            "type": "breakdown", "text": "向下跌破（当日）"})
    return out[-6:]


# ---------------------------------------------------------------- 主入口
_CACHE: Dict[tuple, dict] = {}


def analyze(code: str, period: str = "daily", days: int = 250) -> dict:
    code = str(code).strip()
    bars = _bars(code, period, days)
    if len(bars) < 30:
        return {"ok": False, "reason": f"K线不足（{len(bars)} 根）"}
    last_date = bars[-1][0]
    key = (code, period, int(days), last_date)
    if key in _CACHE:
        return _CACHE[key]

    atr = _atr(bars)
    close = bars[-1][4]
    pv = pivots(bars)
    lv = levels(bars, pv, atr, close)
    tr = trend_or_range(bars, pv, atr)
    ev = events(bars, atr)

    # ---- 棒级信号（与 AI 操盘手同一套判定：trader.bars）----
    signals: List[dict] = []
    bars_info: Dict[str, object] = {}
    try:
        from backend.trader import bars as bars_mod
        raw = bars_mod.signals_for_series(bars, atr)
        # 画线口径：只看最近 SIGNAL_WINDOW 根；已判定跟随的信号棒 / 双底顶 / IOI
        win = max(0, len(bars) - SIGNAL_WINDOW)
        keep = []
        for x in raw:
            if x["i"] < win:
                continue
            if x["kind"] == "signal":
                # 信号失效（✗）全留；跟随成功（✓）只留带"对前5棒突破"上下文的强信号
                if x["follow"] == "failed":
                    keep.append(x)
                elif x["follow"] == "yes" and x["breakout_prev5"] in ("up", "down", "both"):
                    keep.append(x)
            elif x["kind"] in ("mdb", "mdt"):
                if x["breakout_prev5"] in ("up", "down", "both"):
                    keep.append(x)
            elif x["kind"] == "ioi":
                keep.append(x)
        for x in keep:                      # 日期统一 YYYY-MM-DD（前端按 Time 解析）
            x["date"] = _fmt_date(x["date"])
        signals = keep
        # 卡片统计用更长窗口（SIGNAL_STAT_WINDOW）
        stat_win = max(0, len(bars) - SIGNAL_STAT_WINDOW)
        cnt = {"signal_yes": 0, "signal_failed": 0, "mdb": 0, "mdt": 0, "ioi": 0}
        for x in raw:
            if x["i"] < stat_win:
                continue
            if x["kind"] == "signal" and x["follow"] in ("yes", "failed"):
                cnt["signal_yes" if x["follow"] == "yes" else "signal_failed"] += 1
            elif x["kind"] in ("mdb", "mdt", "ioi"):
                cnt[x["kind"]] += 1
        leg = bars_mod.leg_counts(bars)
        last_sig = next((x for x in reversed(raw) if x["kind"] == "signal"), None)
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
        bars_info = {"counts": cnt, "leg": leg, "window": SIGNAL_STAT_WINDOW,
                     "last_signal": ({"date": last_sig["date"], "text": last_sig["text"],
                                      "follow": last_sig["follow"]} if last_sig else None),
                     "streak": streak}
    except Exception as exc:  # noqa: BLE001
        bars_info = {"error": str(exc)[:120]}

    # 结构标签 + 突破质量：日线复用 AI 操盘手同一套（保证"图和操盘手看到的一致"）
    struct_info: Dict[str, object] = {}
    if period == "daily":
        try:
            from backend.trader import structure as st_mod, routing as rt_mod
            d = st_mod.compute(code, _fmt_date(last_date))
            if d.get("ok"):
                struct_info = {
                    "zone": d.get("zone"), "position": d.get("position"),
                    "dist_high_atr": d.get("dist_high_atr"), "dist_low_atr": d.get("dist_low_atr"),
                    "structure": d.get("swing_structure"), "breakout_quality": d.get("breakout_quality"),
                    "barbwire": d.get("barbwire"), "compact_zone": d.get("compact_zone"),
                    "range_high": d.get("range_high"), "range_low": d.get("range_low"),
                }
            rc = rt_mod.classify_code(code, _fmt_date(last_date))
            if rc.get("ok"):
                struct_info["route"] = rc.get("label")
                struct_info["route_note"] = rc.get("note")
        except Exception as exc:  # noqa: BLE001 —— 结构模块异常不应让画线整体失败
            struct_info["error"] = str(exc)[:120]

    # ---- 中文解读（"程序自己做技术分析"）----
    notes: List[str] = []
    if struct_info.get("route"):
        notes.append(f"结构判断：{struct_info['route']}")
    if struct_info.get("structure"):
        notes.append(f"波段结构：{struct_info['structure']}；"
                     f"位置 {struct_info.get('zone') or '—'}"
                     + (f"（{float(struct_info['position']):.0%}）" if struct_info.get("position") is not None else "")
                     + (f"，距上沿 {struct_info['dist_high_atr']}×ATR、距下沿 {struct_info['dist_low_atr']}×ATR"
                        if struct_info.get("dist_high_atr") is not None else ""))
    if tr.get("trend"):
        t = tr["trend"]  # type: ignore[index]
        notes.append(f"{t['label']}：{t['p1']['time']} {t['p1']['price']} → {t['p2']['time']} {t['p2']['price']}，"
                     f"当前值 {t['current']}（有效跌破计数 {t['violations']}）")
    if tr.get("channel"):
        c = tr["channel"]  # type: ignore[index]
        notes.append(f"{c['label']}：当前值 {c['current']}（触及未破次数由图上观察）")
    if tr.get("range"):
        r = tr["range"]  # type: ignore[index]
        notes.append(f"箱体：{r['bottom']} ~ {r['top']}（宽 {r.get('width_atr')}×ATR，{r['from']} 起）")
    sup = [x for x in lv if x["role"] == "support"]
    res = [x for x in lv if x["role"] == "resistance"]
    if sup:
        notes.append("程序认定的支撑：" + "、".join(f"{x['price']:.2f}（{x['n']} 次）" for x in sup))
    if res:
        notes.append("程序认定的阻力：" + "、".join(f"{x['price']:.2f}（{x['n']} 次）" for x in res))
    if struct_info.get("breakout_quality"):
        bq = struct_info["breakout_quality"]
        extra = ""
        if bq == "failed":
            extra = "——突破已失败，按结构破坏对待"
        elif bq == "testing":
            extra = "——突破尚在测试，未确认"
        elif bq == "close_breakout":
            extra = "——收盘价突破，需看跟随"
        notes.append(f"突破质量：{bq}{extra}")
    if struct_info.get("barbwire"):
        notes.append("铁丝网/粘滞区：实体重叠高，假突破概率大，等明确信号再动手")
    if ev:
        notes.append("近期事件：" + "、".join(f"{e['time']} {e['text']}" for e in ev[-3:]))
    bi = bars_info.get("counts") if isinstance(bars_info, dict) else None
    if bi:
        leg = bars_info.get("leg") or {}
        parts = [f"信号棒✓{bi.get('signal_yes', 0)}", f"✗{bi.get('signal_failed', 0)}",
                 f"双底{bi.get('mdb', 0)}", f"双顶{bi.get('mdt', 0)}", f"IOI{bi.get('ioi', 0)}"]
        tail = ""
        if leg.get("label"):
            tail = f"；当前计数 {leg['label']}"
        if bars_info.get("streak"):
            tail += f"；连{'阳' if int(bars_info['streak']) > 0 else '阴'} {abs(int(bars_info['streak']))} 根"
        notes.append(f"棒级信号（近 {bars_info.get('window')} 根）：" + " · ".join(parts) + tail)

    result = {
        "ok": True, "code": code, "period": period, "days": days,
        "as_of": _fmt_date(last_date), "close": round(close, 3),
        "atr14": round(atr, 3) if atr else None,
        "pivots": pv[-10:],
        "levels": lv,
        "trend": tr,
        "events": ev,
        "signals": signals,
        "bars_info": bars_info,
        "structure": struct_info,
        "notes": notes,
    }
    if len(_CACHE) > 500:
        _CACHE.clear()
    _CACHE[key] = result
    return result


if __name__ == "__main__":  # 自检：python -m backend.autodraw 600519
    import json
    import sys
    out = analyze(sys.argv[1] if len(sys.argv) > 1 else "600519")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
