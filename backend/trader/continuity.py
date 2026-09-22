# -*- coding: utf-8 -*-
"""决策连续性：上轮立场关系 + 挂单前提失效判定（借鉴 PA_Agent 的 decision_continuity）。

两个问题它解决得很好，我们也需要：

1. **挂单前提会不会已经变了**：限价单是"当时的想法"，几根 K 线之后前提可能已经不成立
   （想低吸的票已经涨走、支撑已经跌破）。PA_Agent 用"止损是否被触及 + 结构是否同一"
   判断方案失效；我们按 A 股日线口径改成：
     · 买单：市价高于挂单价 ≥3×ATR（低吸机会已走远）或结构跌破箱体下沿（前提转弱）；
     · 卖单：市价低于挂单价 ≥3×ATR（想卖的价已经够不着）。
   结论作为「G2b 挂单前提」闸门给出，模型据此决定"撤单 / 保留并说明理由"（不强制撤）。

2. **上轮立场是什么关系**：首单 / 同向 / 反手 / 延续等待 / 已失效。
   A 股不能做空，"反手"等价于"上轮清仓、这轮又买"这种来回横跳 —— 用于提示模型
   "你刚卖了又想买回"（与反手冷却规则配合）。
"""
from __future__ import annotations

from typing import Callable, Optional

FAR_ATR = 3.0        # 市价与挂单价相差多少个 ATR 视为"前提已走远"

REL_CN = {
    "first": "首单",
    "same": "同向",
    "flip": "反手（上轮卖/清、这轮买）",
    "wait": "延续等待（两轮都无操作）",
    "invalidated": "上轮前提已失效",
    "no_prev": "上轮无操作",
}


def _side_sign(plan: list) -> int:
    """上轮委托的净方向：买 +1 / 卖 -1 / 无 0。"""
    sig = 0
    for o in plan or []:
        s = str(o.get("side") or "").lower()
        if s == "buy":
            sig += 1
        elif s == "sell":
            sig -= 1
    return (sig > 0) - (sig < 0) if sig else 0


def relation_of(prev_decision: Optional[dict], prev_prev: Optional[dict] = None) -> dict:
    """上轮 vs 上上轮的立场关系（给模型看的"你最近在干什么"）。"""
    if not prev_decision:
        return {"relation": "no_prev", "label": REL_CN["no_prev"], "note": ""}
    cur_sig = _side_sign(prev_decision.get("plan") or [])
    if prev_prev is None:
        base = "first" if cur_sig else "no_prev"
        return {"relation": base, "label": REL_CN[base], "note": ""}
    base_sig = _side_sign(prev_prev.get("plan") or [])
    if base_sig == 0 and cur_sig == 0:
        rel = "wait"
    elif cur_sig != 0 and base_sig == 0:
        rel = "first"
    elif cur_sig == 0 and base_sig != 0:
        rel = "wait"
    elif cur_sig == base_sig:
        rel = "same"
    else:
        rel = "flip"
    return {"relation": rel, "label": REL_CN[rel],
            "note": ("上轮与上上轮方向相反（清仓后买回/加仓后清仓），注意别来回横跳"
                     if rel == "flip" else "")}


def assess_pending(pending: list, as_of: str, price_fn: Optional[Callable] = None) -> list:
    """逐笔评估挂单前提是否还成立。返回 [{order_id, code, side, price, ok_to_keep, note}]。"""
    out: list = []
    for o in pending or []:
        code = str(o.get("code") or "")
        side = str(o.get("side") or "").lower()
        limit = float(o.get("price") or 0)
        if not code or limit <= 0:
            continue
        px = None
        try:
            px = float(price_fn(code)) if price_fn else None
        except Exception:
            px = None
        if not px:
            continue
        struct = {}
        try:
            from . import structure as st_mod
            struct = st_mod.compute_cached(code, as_of)
        except Exception:
            struct = {}
        atr = float(struct.get("atr14") or 0) or None
        notes: list = []
        keep = True
        if atr:
            if side == "buy":
                gap = (px - limit) / atr
                if gap >= FAR_ATR:
                    keep = False
                    notes.append(f"市价已比挂单价高 {gap:.1f}×ATR（低吸机会走远）")
            elif side == "sell":
                gap = (limit - px) / atr
                if gap >= FAR_ATR:
                    keep = False
                    notes.append(f"市价已比挂单价低 {gap:.1f}×ATR（想卖的价够不着）")
        if side == "buy" and struct.get("ok"):
            if struct.get("breakout_quality") == "broke_down" or (struct.get("position") or 1) <= 0.12:
                keep = False
                notes.append(f"结构转弱（位置 {struct.get('position')}、"
                             f"{struct.get('swing_structure')}），低吸前提可能已失效")
        out.append({"order_id": o.get("id"), "code": code, "name": o.get("name") or code,
                    "side": side, "qty": o.get("qty"), "price": limit,
                    "市价": round(px, 3), "atr": round(atr, 3) if atr else None,
                    "建议保留": keep, "note": "；".join(notes)})
    return out
