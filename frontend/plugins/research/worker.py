# -*- coding: utf-8 -*-
"""「研究/策略」插件的数据层 —— 后端研究能力接入前端的快照计算.

build_snapshot(hp) -> dict:
  ① 研究代理信号: value_tilt_state / market_breadth / portfolio_value_alloc / value_hard_rule
  ② 价值因子研究: BP/EP/ROE 截面 IC·ICIR(复用 frames, 不重复加载)
  ③ 多因子排名: composite z(BP)+z(REV20)-z(VOL20) 在 as-of 截面 top-N
  ④ 组合纸面盘: forward_paper_run(重平衡器 NET) vs 等权买持 净值曲线

口径诚实: 池=build_wide_pool(≈287跨板块); 权威口径(全市场/2500池)另跑 backend verify_*.py。
导入规约: 用 `backend.` 前缀(项目根在 sys.path) —— agent 包内 `from ..strategy` 需 backend 为命名空间父包。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.strategy.factor_selector import build_wide_pool  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.portfolio_rebalance import (  # noqa: E402
    adaptive_config_for_hp, forward_paper_run, composite_score, _xs_z, select_top_k,
)
from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.agent.decision_gate import (  # noqa: E402
    value_tilt_state, market_breadth, portfolio_value_alloc, value_hard_rule,
)


def build_snapshot(hp: int = 20, use_tilt: bool = True, top_k_pct: float = 0.2,
                   fwd_start: str = "2024-01-01", study_start: str = "2022-01-01"):
    """计算研究快照(后台线程调用). hp=持有期(5/10/20/40). 返回 dict(各段可独立失败)."""
    now = datetime.now().strftime("%Y-%m-%d")
    codes = build_wide_pool()
    snap = {"hp": int(hp), "as_of": now, "pool_size": len(codes),
            "codes": codes, "signals": {}, "study": {}, "ranking": [], "paper": {}}

    # ── 加载帧(一次, 供研究/排名/纸面盘复用) ──
    WARM = "2020-06-01"
    try:
        frames = load_universe_frames(codes, start=WARM, end=now,
                                      with_fundamentals=True, fetch_missing=False)
        snap["frames_loaded"] = len(frames)
    except Exception as e:  # noqa: BLE001
        snap["frames_error"] = str(e)
        return snap
    if not frames:
        snap["frames_error"] = "无可用frames"
        return snap

    # ── ① 研究代理信号(诊断卡) ──
    try:
        vt = value_tilt_state()
    except Exception as e:  # noqa: BLE001
        vt = {"state": "error", "value_tilt": "neutral", "reason": str(e)}
    try:
        br = market_breadth(close_panel=frames)   # 复用已加载帧, 不重复加载
    except Exception as e:  # noqa: BLE001
        br = {"breadth": 0.5, "tilt": "value_neutral", "reason": str(e)}
    try:
        alloc = portfolio_value_alloc(index_tilt=vt, breadth=br, value_spread=None)
    except Exception as e:  # noqa: BLE001
        alloc = {"tilt_label": "value_neutral", "w_value": 1.0, "reason": str(e)}
    try:
        # 价值策略契约(引用价值因子)在 headwind 下 → 决策门 hold(演示 value_hard_rule)
        hard = value_hard_rule({"value_tilt": vt,
                                "strategy": {"entry": {"type": "gt", "args": ["BP", 0.0]}, "exit": None}})
        hard = hard.to_dict() if hard is not None else None
    except Exception as e:  # noqa: BLE001
        hard = {"error": str(e)}
    snap["signals"] = {"value_tilt": vt, "breadth": br, "alloc": alloc, "hard_rule": hard}

    # ── ② 价值因子研究(IC/ICIR, 复用 frames) ──
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    # as_of = 最近"宽覆盖"截面日(≥40%池有数据的最近日) —— 避免并集最后日=指数新日, 截面塌到1只
    valid = close.notna().sum(axis=1)
    cutoff = max(30, int(len(codes) * 0.4))
    wide = valid[valid >= cutoff]
    as_of = wide.index[-1] if len(wide) else close.index[-1]
    snap["as_of"] = str(pd.Timestamp(as_of).date())
    # 排除指数/非交易代码(000001=上证指数, 与个股撞码; 其有指数级新数据, 会污染截面)
    INDEX_CODES = {"000001", "399001", "399006", "000300", "000016", "000905"}

    def _icir(fid):
        try:
            r = eng.run(frames=frames, factor_id=fid, start_date=study_start, end_date=now,
                        groups=5, holding_period=5, neutralize_industry=True, compute_correlation=False)
            return {"ic": round(float(r.get("rankIc", 0.0) or 0.0), 4),
                    "icir": round(float(r.get("icir", 0.0) or 0.0), 3),
                    "ic_positive": round(float(r.get("icPositiveRate", 0.0) or 0.0), 3),
                    "monotonicity": round(float(r.get("monotonicity", 0.0) or 0.0), 3),
                    "long_short_net": round(float(r.get("netLongShortReturn", 0.0) or 0.0), 4),
                    "coverage": round(float(r.get("coverage", 0.0) or 0.0), 3)}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    study = {}
    for f in ("BP", "EP", "ROE"):
        study[f] = _icir(f)
    snap["study"] = study

    # ── ③ 多因子排名(as-of 宽覆盖截面) ──
    try:
        contract = adaptive_config_for_hp(hp, top_k_pct=top_k_pct)
        w_value = alloc.get("w_value", 1.0) if use_tilt else 1.0
        factor_z = {}
        for f in ("BP", "REVERSAL_20", "VOLATILITY_20"):
            panel = eng._factor_panel(frames, f, close)
            z = _xs_z(panel, as_of)
            if z is not None:
                factor_z[f] = z
        score = composite_score(factor_z, contract, w_value)
        ranking = []
        if score is not None:
            # 截面排除指数代码(非交易标的)
            score = score.loc[~score.index.isin(INDEX_CODES)]
            top_ids = select_top_k(score, top_k_pct)
            for c in top_ids[:25]:
                last = frames[c]
                chg = 0.0
                if len(last) >= 2:
                    chg = (float(last["close"].iloc[-1]) / float(last["close"].iloc[-2]) - 1.0) * 100.0
                ranking.append({
                    "code": c, "name": "", "price": round(float(last["close"].iloc[-1]), 2),
                    "chg": round(chg, 2), "comp": round(float(score[c]), 3),
                })
        snap["ranking"] = ranking
    except Exception as e:  # noqa: BLE001
        snap["ranking_error"] = str(e)

    # ── ④ 组合纸面盘(重平衡NET vs 等权买持) ──
    try:
        fwd_end = str(pd.Timestamp(as_of).date())
        fw = forward_paper_run(frames, contract, fwd_start, fwd_end, initial_balance=1_000_000.0)
        # 等权买持(同窗口, 逐日等权平均价格比)
        bh_dates, bh_nav = [], []
        loc = close.loc[(close.index >= pd.Timestamp(fwd_start)) & (close.index <= as_of)]
        if len(loc) >= 2:
            bh = {}
            start_row = loc.iloc[0]
            for c in start_row.index:
                v = start_row.get(c)
                if v is not None and not pd.isna(v) and float(v) > 0:
                    bh[c] = float(v)
            for ts in loc.index:
                row = loc.loc[ts]
                vals, cnt = 0.0, 0
                for c, p0 in bh.items():
                    v = row.get(c)
                    if v is not None and not pd.isna(v) and float(v) > 0:
                        vals += float(v) / p0
                        cnt += 1
                if cnt:
                    bh_dates.append(str(ts))
                    bh_nav.append(vals / cnt)
        snap["paper"] = {"dates": fw["dates"], "nav": fw["nav_n"], "final_holdings": fw["final_holdings"],
                         "final_cash": fw["final_cash"], "turnover_avg": fw["turnover_avg"],
                         "cost_total": fw["cost_total"], "rebalances": fw["rebalances"],
                         "buyhold_dates": bh_dates, "buyhold_nav": bh_nav, "w_value": w_value}
    except Exception as e:  # noqa: BLE001
        snap["paper_error"] = str(e)

    return snap
