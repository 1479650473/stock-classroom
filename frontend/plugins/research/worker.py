# -*- coding: utf-8 -*-
"""「研究/策略」插件的数据层 —— 后端研究能力接入前端的可复用计算.

共享函数(都复用同一份缓存帧, 各段可独立失败):
  build_snapshot(hp)   — 快照: ①研究代理信号 ②价值因子IC/ICIR ③多因子排名 ④组合纸面盘(研究面板用)
  study_factors()      — 仅 ② 价值因子研究 (AI助手工具 / 研究面板用)
  build_paper_only(hp) — 仅 ④ 组合纸面盘 forward vs 买持 (AI助手工具 / 交易伴侣用)
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

# 指数/非交易代码(000001=上证指数, 与个股撞码) —— 截面须排除
INDEX_CODES = {"000001", "399001", "399006", "000300", "000016", "000905"}
WARM = "2020-06-01"

_frames_cache = None
_cache_key = None


def _load_frames():
    """加载跨板块均衡池帧(点时间基本面), 进程内缓存(重入快)."""
    global _frames_cache, _cache_key
    now = datetime.now().strftime("%Y-%m-%d")
    if _frames_cache is not None and _cache_key == now:
        return _frames_cache
    try:
        codes = build_wide_pool()
        frames = load_universe_frames(codes, start=WARM, end=now,
                                      with_fundamentals=True, fetch_missing=False)
    except Exception as e:  # noqa: BLE001
        _frames_cache, _cache_key = {}, now
        return _frames_cache
    _frames_cache, _cache_key = frames, now
    return frames


def _as_of(close: pd.DataFrame, n_pool: int):
    """最近'宽覆盖'截面日(≥40%池有效), 避免并集最后日=指数新日导致截面塌到1只."""
    valid = close.notna().sum(axis=1)
    cutoff = max(30, int(n_pool * 0.4))
    wide = valid[valid >= cutoff]
    return wide.index[-1] if len(wide) else close.index[-1]


# ── ② 价值因子研究(IC/ICIR) ─────────────────────────────────────
def study_factors(study_start: str = "2022-01-01", progress=None) -> dict:
    """BP/EP/ROE 截面 IC·ICIR(板块中性化). 返回 {BP:{...},EP:{...},ROE:{...},as_of}."""
    frames = _load_frames()
    if not frames:
        return {"error": "无frames"}
    now = datetime.now().strftime("%Y-%m-%d")
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    as_of = _as_of(close, len(frames))

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

    out = {}
    for i, f in enumerate(("BP", "EP", "ROE")):
        if progress:
            progress(f"计算 {f} IC/ICIR...", round((i / 3) * 100, 0))
        out[f] = _icir(f)
    if progress:
        progress("汇总推荐因子...", 95.0)
    # 最强(非reject)
    best = None
    for f, v in out.items():
        if "icir" in v and v["icir"] is not None and abs(v["icir"]) >= 0.3:
            if best is None or abs(v["icir"]) > abs(best["icir"]):
                best = {"dsl_key": f, **v}
    out["recommended"] = best
    out["as_of"] = str(pd.Timestamp(as_of).date())
    out["pool_size"] = len(frames)
    return out


# ── ④ 组合纸面盘(重平衡NET vs 等权买持) ──────────────────────────
def build_paper_only(hp: int = 20, top_k_pct: float = 0.2,
                     fwd_start: str = "2024-01-01", progress=None) -> dict:
    """仅组合纸面盘(不跑信号/研究/排名). 返回 paper字典 + as_of(供交易伴侣/AI工具)."""
    frames = _load_frames()
    if not frames:
        return {"error": "无frames"}
    now = datetime.now().strftime("%Y-%m-%d")
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    as_of = _as_of(close, len(frames))
    contract = adaptive_config_for_hp(hp, top_k_pct=top_k_pct)
    paper = {}
    try:
        fwd_end = str(pd.Timestamp(as_of).date())
        if progress:
            progress("组合纸面盘前向推进...", 15.0)
        fw = forward_paper_run(frames, contract, fwd_start, fwd_end, initial_balance=1_000_000.0)
        if progress:
            progress("计算等权买持基准...", 75.0)
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
        paper = {"dates": fw["dates"], "nav": fw["nav_n"], "final_holdings": fw["final_holdings"],
                 "final_cash": fw["final_cash"], "turnover_avg": fw["turnover_avg"],
                 "cost_total": fw["cost_total"], "rebalances": fw["rebalances"],
                 "buyhold_dates": bh_dates, "buyhold_nav": bh_nav, "w_value": 1.0,
                 "daily_holdings": fw.get("daily_holdings", []),
                 "rebalance_log": fw.get("rebalance_log", [])}
    except Exception as e:  # noqa: BLE001
        paper = {"error": str(e)}
    # 持久化完整 paper(含每日持仓/每笔调仓), 供持仓面板读取
    try:
        import json as _json
        import numpy as _np
        def _conv(o):
            if isinstance(o, _np.integer):
                return int(o)
            if isinstance(o, _np.floating):
                return float(o)
            if isinstance(o, _np.bool_):
                return bool(o)
            return str(o)
        with open(os.path.join(os.path.dirname(_ROOT), 'data', 'paper_run.json'), 'w', encoding='utf-8') as _f:
            _json.dump({"paper": paper, "as_of": str(pd.Timestamp(as_of).date()),
                        "pool_size": len(frames), "hp": hp}, _f,
                       ensure_ascii=False, indent=1, default=_conv)
    except Exception as e:
        import logging; logging.getLogger('research').warning('paper 持久化失败: %s', repr(e)[:80])
    return {"paper": paper, "as_of": str(pd.Timestamp(as_of).date()), "pool_size": len(frames),
            "hp": hp}


# ── 单因子回测(AI助手工具用) ───────────────────────────────────
def run_backtest(factor: str = "BP", holding_period: int = 20,
                 start: str = "2022-01-01", progress=None) -> dict:
    """单因子截面回测(wide池, 板块中性化). 返回 {IC,ICIR,IC正率,单调,多空净,分组净值,coverage}."""
    frames = _load_frames()
    if not frames:
        return {"error": "无frames"}
    now = datetime.now().strftime("%Y-%m-%d")
    eng = FactorResearchEngine()
    try:
        if progress:
            progress("截面回测计算中...", 30.0)
        r = eng.run(frames=frames, factor_id=str(factor).lower(), start_date=start, end_date=now,
                    groups=5, holding_period=int(holding_period or 20),
                    neutralize_industry=True, compute_correlation=False)
        if progress:
            progress("汇总分组净值...", 90.0)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    curves = r.get("groupCurves", [])
    top = curves[0].get("group", 0) if curves else 0
    return {"factor": str(factor).upper(), "ic": round(float(r.get("rankIc", 0.0) or 0.0), 4),
            "icir": round(float(r.get("icir", 0.0) or 0.0), 3),
            "ic_positive": round(float(r.get("icPositiveRate", 0.0) or 0.0), 3),
            "monotonicity": round(float(r.get("monotonicity", 0.0) or 0.0), 3),
            "multi_long_short": round(float(r.get("netLongShortReturn", 0.0) or 0.0), 4),
            "coverage": round(float(r.get("coverage", 0.0) or 0.0), 3),
            "groups": [{"group": c["group"], "net": round(c["finalNet"], 4)}
                       for c in curves if "finalNet" in c]}


# ── ①+②+③+④ 完整快照(研究面板) ────────────────────────────────
def build_snapshot(hp: int = 20, use_tilt: bool = True, top_k_pct: float = 0.2,
                   fwd_start: str = "2024-01-01", study_start: str = "2022-01-01"):
    """计算研究快照(后台线程调用). hp=持有期(5/10/20/40). 返回 dict(各段可独立失败)."""
    now = datetime.now().strftime("%Y-%m-%d")
    codes = build_wide_pool()
    snap = {"hp": int(hp), "as_of": now, "pool_size": len(codes),
            "codes": codes, "signals": {}, "study": {}, "ranking": [], "paper": {}}

    frames = _load_frames()
    if not frames:
        snap["frames_error"] = "无可用frames"
        return snap
    snap["frames_loaded"] = len(frames)

    # ① 研究代理信号
    try:
        vt = value_tilt_state()
    except Exception as e:  # noqa: BLE001
        vt = {"state": "error", "value_tilt": "neutral", "reason": str(e)}
    try:
        br = market_breadth(close_panel=frames)
    except Exception as e:  # noqa: BLE001
        br = {"breadth": 0.5, "tilt": "value_neutral", "reason": str(e)}
    try:
        alloc = portfolio_value_alloc(index_tilt=vt, breadth=br, value_spread=None)
    except Exception as e:  # noqa: BLE001
        alloc = {"tilt_label": "value_neutral", "w_value": 1.0, "reason": str(e)}
    try:
        hard = value_hard_rule({"value_tilt": vt,
                                "strategy": {"entry": {"type": "gt", "args": ["BP", 0.0]}, "exit": None}})
        hard = hard.to_dict() if hard is not None else None
    except Exception as e:  # noqa: BLE001
        hard = {"error": str(e)}
    snap["signals"] = {"value_tilt": vt, "breadth": br, "alloc": alloc, "hard_rule": hard}

    # ② 价值因子研究
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    as_of = _as_of(close, len(codes))
    snap["as_of"] = str(pd.Timestamp(as_of).date())

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

    # ③ 多因子排名
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

    # ④ 组合纸面盘
    try:
        fwd_end = str(pd.Timestamp(as_of).date())
        fw = forward_paper_run(frames, contract, fwd_start, fwd_end, initial_balance=1_000_000.0)
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
