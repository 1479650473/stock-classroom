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


# ── 价值/质量因子(基本面) —— 跨截面选股因子(需 with_fundamentals 附着), 支持 value 选股 ──
VALUE_CANDIDATES = ["EP", "BP", "ROE"]

# 价值因子默认研究口径: 基本面 IC 量级通常小于价量因子(全市场 BP IC=0.041, EP=0.023),
#   故 min_ic 用更小的 0.004; min_icir 保持 0.3(R O E 的 |ICIR|=0.23 会被拒, 正是实证结论)。
VALUE_DEFAULTS = {"min_ic": 0.004, "min_icir": 0.3, "min_coverage": 0.5}

# ICIR 分档(阈值, 标签, strength 0~1) —— 用 **全市场 5149 只实证值标定**(2026-08):
#   BP  ICIR=1.54 → high;  EP ICIR=0.83 → medium;  ROE ICIR=-0.23 → reject(|·|<0.3, 跨行业不可比)。
#   与价量 DEFAULT_BANDS 数值相同, 但此处门槛依据的是全市场价值/质量实证而非启发式。
VALUE_BANDS: Sequence[tuple] = (
    (1.0, "high", 1.0),
    (0.5, "medium", 0.6),
    (0.3, "weak", 0.3),
)


def _classify_value_record(rec: dict, bands: Sequence[tuple], defaults: dict) -> dict:
    """给单个价值研究记录附加 direction/confidence/strength；不达门槛 → reject。"""
    r = dict(rec)
    ic, icir, cov = float(r.get("ic", 0.0) or 0.0), float(r.get("icir", 0.0) or 0.0), \
        float(r.get("coverage", 0.0) or 0.0)
    if cov < defaults["min_coverage"] or abs(ic) < defaults["min_ic"]:
        r["direction"], r["confidence"], r["strength"] = 0, "reject", 0.0
        return r
    label, strength = _band(abs(icir), bands)
    r["direction"] = 1 if ic > 0 else -1
    r["confidence"], r["strength"] = label, strength
    r["score"] = abs(ic) * min(abs(icir), 3.0) + strength * 0.5
    return r


def classify_value_records(vres: list, bands: Sequence[tuple] = VALUE_BANDS,
                           defaults: dict = VALUE_DEFAULTS) -> tuple[list, Optional[dict]]:
    """批量给价值研究记录附标签, 返回 (带标签列表, 最优[非reject]或None)。"""
    tagged, best = [], None
    for rec in vres:
        t = _classify_value_record(rec, bands, defaults)
        tagged.append(t)
        if t["confidence"] != "reject" and (best is None or t.get("score", 0.0) > best.get("score", 0.0)):
            best = t
    return tagged, best


def recommend_value(codes, start: str, end: str, engine: Optional[FactorResearchEngine] = None,
                    min_universe: int = 5, neutralize_industry: bool = True,
                    fetch_missing: bool = False, holding_period: int = 5,
                    candidates: Sequence[str] = VALUE_CANDIDATES,
                    defaults: dict = VALUE_DEFAULTS, bands: Sequence[tuple] = VALUE_BANDS) -> Optional[dict]:
    """全市场实证标定后: 选出最强的价值/质量因子(方向+置信度), 供价值选股策略生成引用。

    以全市场 BP(ICIR 1.54) 为最强基准; EP(0.83) 中等; ROE(-0.23) 被拒(跨行业不可比)。
    返回 {dsl_key, direction, ic, icir, confidence, strength, coverage, net_long_short, bands, ...}。
    """
    vres = study_value_factors(codes, start, end, engine=engine, min_universe=min_universe,
                               neutralize_industry=neutralize_industry, fetch_missing=fetch_missing,
                               candidates=candidates, holding_period=holding_period)
    _, best = classify_value_records(vres, bands, defaults)
    if best is not None:
        best = {**best, "bands": [list(b) for b in bands], "icir_threshold": defaults["min_icir"]}
    return best


def validate_value_selection(contract: dict) -> dict:
    """校验 LLM 生成的**价值选股**策略契约(跨截面选股, 非单标的 DSL 契约)。

    参考全市场实证: BP(ICIR 1.54) 最强 → 默认因子; EP(0.83) 中等; ROE(-0.23) 不作主导。
    Schema: {name, description, factor, direction, hold_top_k_pct, rebalance_bars, risk, initial_balance}。
    factor/方向白名单硬校验(防 LLM 引用未知因子或越界)。
    """
    allowed_factor = {"EP", "BP", "ROE"}
    c = dict(contract or {})
    f = str(c.get("factor", "BP")).strip().upper()
    if f not in allowed_factor:
        raise ValueError(f"未知价值因子 {f!r} (白名单: {sorted(allowed_factor)})")
    c["factor"] = f
    d = str(c.get("direction", "high")).strip().lower()
    if d not in ("high", "low"):
        raise ValueError("direction 必须为 high|low")
    c["direction"] = d
    try:
        k = float(c.get("hold_top_k_pct", 0.2))
    except (TypeError, ValueError):
        raise ValueError("hold_top_k_pct 必须为数值")
    if not (0.01 <= k <= 0.5):
        raise ValueError("hold_top_k_pct 必须在 0.01~0.5")
    c["hold_top_k_pct"] = k
    try:
        rb = int(c.get("rebalance_bars", 20))
    except (TypeError, ValueError):
        raise ValueError("rebalance_bars 必须为整数")
    if rb < 5:
        raise ValueError("rebalance_bars 至少 5")
    c["rebalance_bars"] = rb
    c.setdefault("name", f"value-选股[{c['factor']}]")
    c.setdefault("description", "")
    risk = dict(c.get("risk") or {})
    try:
        risk["stop_loss_pct"] = float(risk.get("stop_loss_pct") or 0.0)
    except (TypeError, ValueError):
        risk["stop_loss_pct"] = 0.0
    risk["max_hold_bars"] = int(risk.get("max_hold_bars") or 0)
    risk["avoid_st"] = bool(risk.get("avoid_st", True))
    c["risk"] = risk
    return c


def study_value_factors(codes, start: str, end: str, engine: Optional[FactorResearchEngine] = None,
                        min_universe: int = 5, neutralize_industry: bool = True,
                        fetch_missing: bool = False, candidates: Sequence[str] = VALUE_CANDIDATES,
                        holding_period: int = 5) -> list:
    """研究价值/质量因子(EP/BP/ROE)的截面 IC/ICIR(点时间, 无前视)。

    扩展单日 K 线之外的研究维度: 用基本面对每只股在每交易日给出 盈利收益率EP/账面市值比BP/ROE。
    neutralize_industry=True 时按板块中性化(去板块效应, 跨板块研究更可信)。
    fetch_missing=False(默认): **只读已缓存**基本面(本地化, 读路径不联网)。
    返回 [ {dsl_key, ic, icir, coverage, net_long_short, confidence, strength, direction, research}, ... ]。
    """
    frames = load_universe_frames(codes, start=start, end=end, with_fundamentals=True,
                                  fetch_missing=fetch_missing)
    if len(frames) < min_universe:
        return []
    engine = engine or FactorResearchEngine()
    out = []
    for fid in candidates:
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date=start, end_date=end,
                           groups=5, holding_period=holding_period,
                           neutralize_industry=neutralize_industry, compute_correlation=False)
            out.append(_classify_value_record({
                "dsl_key": fid,
                "ic": float(r.get("rankIc", 0.0) or 0.0),
                "icir": float(r.get("icir", 0.0) or 0.0),
                "coverage": float(r.get("coverage", 0.0) or 0.0),
                "net_long_short": float(r.get("netLongShortReturn", 0.0) or 0.0),
                "neutralized": bool(r.get("neutralized", False)),
                "research": r,
            }, VALUE_BANDS, VALUE_DEFAULTS))
        except Exception:
            continue
    return out


def build_wide_pool(per_sector: int = 12) -> list:
    """跨板块平衡研究池: 每板块前 per_sector 只活跃股(小板块全取) → ~25*per_sector 只。"""
    from . import catalog as _cat
    codes = []
    for s in _cat.sectors():
        try:
            items = _cat.select(sector=s, status="active")
        except Exception:
            items = []
        codes += [i["code"] for i in items][:per_sector]
    return sorted(set(codes))


def build_full_pool(min_bars: int = 120) -> list:
    """全市场研究池: 所有活跃且有 >=min_bars 根 K 线的股票(~5200 只)。

    注意: 该池多数股票无板块标注 → 只能做原始(不中性化)价值研究;
       行业中性化需用 build_wide_pool(有板块的)子集。
    """
    import sqlite3
    from .data import get_kline_db_path
    con = sqlite3.connect(get_kline_db_path())
    rows = con.execute(
        "SELECT c.code FROM stock_list c WHERE c.status='active' AND c.code IN "
        "(SELECT code FROM kline_daily GROUP BY code HAVING COUNT(*)>=?)", (min_bars,)).fetchall()
    con.close()
    return [r[0] for r in rows]
