# -*- coding: utf-8 -*-
"""因子选择器 — 在个股池上跑截面 IC/ICIR，选出"被研究支撑"的因子。

研究→论证→生成：先对标的域候选因子做 IC/ICIR 论证，返回最强因子(dsl_key+方向)，
供策略生成引用。方向 direction: 1=因子值越高越好, -1=越低越好。
"""
from __future__ import annotations

from typing import Optional

from .factor_research import FactorResearchEngine
from .factor_data import load_universe_frames

# 候选截面因子(dsl_key)；与 factor_research 内部 lowercase id 对应
CANDIDATES = ["MOMENTUM_20", "MOMENTUM_60", "REVERSAL_5", "VOLATILITY_20"]

# 各因子"好方向"的落地阈值(供生成入口用; 比率因子以 0 分界, 波动率以典型值分界)
# threshold=0 表示有符号因子
FACTOR_HINTS = {
    "MOMENTUM_20": {"signed": True, "threshold": 0.0},
    "MOMENTUM_60": {"signed": True, "threshold": 0.0},
    "REVERSAL_5": {"signed": True, "threshold": 0.0},
    "VOLATILITY_20": {"signed": False, "threshold": 0.025},
}


def recommend(codes, start: str, end: str, engine: Optional[FactorResearchEngine] = None,
              min_universe: int = 5) -> Optional[dict]:
    """在 codes 池上跑候选因子 IC/ICIR，返回最优或 None(信号太弱/池太小)。"""
    frames = load_universe_frames(codes, start=start, end=end)
    if len(frames) < min_universe:
        return None
    engine = engine or FactorResearchEngine()
    best = None
    for fid in CANDIDATES:
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date=start, end_date=end,
                           groups=5, holding_period=5)
        except Exception:
            continue
        ic = float(r.get("rankIc", 0.0) or 0.0)
        icir = float(r.get("icir", 0.0) or 0.0)
        cov = float(r.get("coverage", 0.0) or 0.0)
        mono = float(r.get("monotonicity", 0.0) or 0.0)
        # 信号太弱/覆盖不足 → 跳过
        if cov < 0.5 or abs(ic) < 0.005 or abs(icir) < 0.15:
            continue
        direction = 1 if ic > 0 else -1
        score = abs(ic) * min(abs(icir), 3.0) + mono * 0.3
        if best is None or score > best["score"]:
            best = {"dsl_key": fid, "direction": direction, "ic": ic, "icir": icir,
                    "coverage": cov, "monotonicity": mono, "score": score,
                    "net_long_short": float(r.get("netLongShortReturn", 0.0) or 0.0),
                    "research": r}
    return best


def entry_for_factor(rec: Optional[dict]) -> Optional[dict]:
    """给出引用所选因子的 DSL 入场条件(方向感知)；rec 为空则 None(调用方回退)。"""
    if not rec:
        return None
    key = rec["dsl_key"]
    direction = rec["direction"]
    hint = FACTOR_HINTS.get(key, {"signed": True, "threshold": 0.0})
    threshold = hint.get("threshold", 0.0)
    op = "gt" if direction == 1 else "lt"
    return {"type": op, "args": [key, threshold]}
