# -*- coding: utf-8 -*-
"""因子选择器 — 在个股池上跑截面 IC/ICIR，选出"被研究支撑"的因子。

研究→论证→生成：先对标的域候选因子做 IC/ICIR 论证，返回最强因子(dsl_key+方向)，
供策略生成引用。方向 direction: 1=因子值越高越好, -1=越低越好。

自动选参：ICIR 阈值参数化(门槛 = |IC|/|ICIR|/覆盖度)，并按 ICIR 分档给出 confidence
(high/medium/weak)与 strength，供下游(生成/决策门)决定采用程度。
"""
from __future__ import annotations

from typing import Optional, Sequence

from .factor_research import FactorResearchEngine
from .factor_data import load_universe_frames

# 候选截面因子(dsl_key)—— 必须都已在 factors.py 逐bar产出 + KNOWN_FACTORS (研究→生成桥)
CANDIDATES = [
    # 动量(多窗口)
    "MOMENTUM_5", "MOMENTUM_10", "MOMENTUM_20", "MOMENTUM_40", "MOMENTUM_60",
    # 反转(多窗口)
    "REVERSAL_5", "REVERSAL_10", "REVERSAL_20",
    # 波动(多窗口)
    "VOLATILITY_5", "VOLATILITY_10", "VOLATILITY_20", "VOLATILITY_60",
    # 超买超卖
    "RSI_14",
]

# 各因子"好方向"的落地阈值(供生成入口用; signed=True 表示以 0 分界)
FACTOR_HINTS = {
    "MOMENTUM_5": {"signed": True, "threshold": 0.0},
    "MOMENTUM_10": {"signed": True, "threshold": 0.0},
    "MOMENTUM_20": {"signed": True, "threshold": 0.0},
    "MOMENTUM_40": {"signed": True, "threshold": 0.0},
    "MOMENTUM_60": {"signed": True, "threshold": 0.0},
    "REVERSAL_5": {"signed": True, "threshold": 0.0},
    "REVERSAL_10": {"signed": True, "threshold": 0.0},
    "REVERSAL_20": {"signed": True, "threshold": 0.0},
    "VOLATILITY_5": {"signed": False, "threshold": 0.025},
    "VOLATILITY_10": {"signed": False, "threshold": 0.025},
    "VOLATILITY_20": {"signed": False, "threshold": 0.025},
    "VOLATILITY_60": {"signed": False, "threshold": 0.025},
    "RSI_14": {"signed": False, "threshold": 50.0},
}

# ICIR 分档 (阈值, 标签, strength 0~1) —— 从高到低; 低于最弱档 → reject
DEFAULT_BANDS: Sequence[tuple] = (
    (1.0, "high", 1.0),
    (0.5, "medium", 0.6),
    (0.3, "weak", 0.3),
)


def _band(abs_icir: float, bands: Sequence[tuple]) -> tuple:
    for gate, label, strength in bands:
        if abs_icir >= gate:
            return label, float(strength)
    return "reject", 0.0


def recommend(codes, start: str, end: str, engine: Optional[FactorResearchEngine] = None,
              min_universe: int = 5, min_ic: float = 0.005, min_icir: float = 0.3,
              min_coverage: float = 0.5, bands: Sequence[tuple] = DEFAULT_BANDS,
              holding_period: int = 5, candidates: Sequence[str] = CANDIDATES) -> Optional[dict]:
    """在 codes 池上跑候选因子 IC/ICIR，按阈值+分档自动选参，返回最优或 None(全被拒)。"""
    frames = load_universe_frames(codes, start=start, end=end)
    if len(frames) < min_universe:
        return None
    engine = engine or FactorResearchEngine()
    best = None
    for fid in candidates:
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date=start, end_date=end,
                           groups=5, holding_period=holding_period, compute_correlation=False)
        except Exception:
            continue
        ic = float(r.get("rankIc", 0.0) or 0.0)
        icir = float(r.get("icir", 0.0) or 0.0)
        cov = float(r.get("coverage", 0.0) or 0.0)
        mono = float(r.get("monotonicity", 0.0) or 0.0)
        if cov < min_coverage or abs(ic) < min_ic or abs(icir) < min_icir:
            continue
        label, strength = _band(abs(icir), bands)
        if label == "reject":
            continue
        direction = 1 if ic > 0 else -1
        hint = FACTOR_HINTS.get(fid, {"signed": True, "threshold": 0.0})
        score = abs(ic) * min(abs(icir), 3.0) + mono * 0.3 + strength * 0.25
        if best is None or score > best["score"]:
            best = {"dsl_key": fid, "direction": direction, "ic": ic, "icir": icir,
                    "abs_icir": abs(icir), "coverage": cov, "monotonicity": mono,
                    "score": score, "confidence": label, "strength": strength,
                    "threshold": hint.get("threshold", 0.0),
                    "net_long_short": float(r.get("netLongShortReturn", 0.0) or 0.0),
                    "icir_threshold": min_icir,
                    "bands": [list(b) for b in bands],
                    "research": r}
    return best


def entry_for_factor(rec: Optional[dict]) -> Optional[dict]:
    """给出引用所选因子的 DSL 入场条件(方向感知)；rec 为空则 None(调用方回退)。"""
    if not rec:
        return None
    key = rec["dsl_key"]
    direction = rec["direction"]
    threshold = rec.get("threshold", 0.0)
    op = "gt" if direction == 1 else "lt"
    return {"type": op, "args": [key, threshold]}


# ── 价值/质量因子(基本面) —— 研究诊断, 非 DSL 策略候选(需 with_fundamentals 附着) ──
VALUE_CANDIDATES = ["EP", "BP", "ROE"]


def study_value_factors(codes, start: str, end: str, engine: Optional[FactorResearchEngine] = None,
                        min_universe: int = 5) -> list:
    """研究价值/质量因子(EP/BP/ROE)的截面 IC/ICIR(点时间, 含披露滞后无前视)。

    扩展单日 K 线之外的研究维度: 用基本面对每只股在每交易日给出 盈利收益率EP/账面市值比BP/ROE。
    返回 [ {dsl_key, ic, icir, coverage, net_long_short, research}, ... ]。
    """
    frames = load_universe_frames(codes, start=start, end=end, with_fundamentals=True)
    if len(frames) < min_universe:
        return []
    engine = engine or FactorResearchEngine()
    out = []
    for fid in VALUE_CANDIDATES:
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date=start, end_date=end,
                           groups=5, holding_period=5, compute_correlation=False)
            out.append({
                "dsl_key": fid,
                "ic": float(r.get("rankIc", 0.0) or 0.0),
                "icir": float(r.get("icir", 0.0) or 0.0),
                "coverage": float(r.get("coverage", 0.0) or 0.0),
                "net_long_short": float(r.get("netLongShortReturn", 0.0) or 0.0),
                "research": r,
            })
        except Exception:
            continue
    return out
