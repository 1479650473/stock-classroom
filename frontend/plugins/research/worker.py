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
    SelectionContract, RebalancePlanner,
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
def _kline_db_path():
    """kline.db 绝对路径(项目根 /data/kline.db)."""
    import os as _os
    return _os.path.join(_os.path.dirname(_ROOT), 'data', 'kline.db')


def _kline_last_close(code):
    """kline_daily 最新收盘价(做'模拟买入'的当日现价)."""
    import sqlite3 as _sq
    try:
        con = _sq.connect(_kline_db_path())
        r = con.execute("SELECT close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1", (code,)).fetchone()
        con.close()
        return float(r[0]) if r and r[0] else None
    except Exception:
        return None


def sim_buy_picks(codes, account_id=None, budget_percent=1.0, db_path=None):
    """把选出的股票**一键模拟买入**(等权分配当前账户可用资金, 市价单按最新收盘价).

    codes: [{code,name,price}, ...] 或 [code, ...]. 未指定账户→首个活跃账户.
    db_path: 覆盖 TradeEngine 默认 DB(测试用, 默认 None=真实 sim_trade.db).
    返回 {account_id, bought:[{code,name,qty,price}], skipped:[{code,reason}], total_cost}.
    口径: 模拟盘(真实 TradeEngine, sim_trade.db); 单票30%仓位上限/资金不足会被跳过并说明.
    """
    from trade_engine.engine import TradeEngine
    eng = TradeEngine(db_path=db_path)
    if account_id is None:
        accs = eng.list_accounts()
        if not accs:
            return {"error": "无模拟账户(请先在交易页创建)"}
        account_id = accs[0]['id']
    if codes and isinstance(codes[0], str):
        codes = [{"code": c, "name": "", "price": _kline_last_close(c)} for c in codes]
    codes = [c for c in codes if c.get("code")]
    if not codes:
        return {"error": "无选股结果"}
    # 等权分配账户可用资金
    acc = eng.get_account(account_id)
    bal = float(acc["balance"]) if acc else 0.0
    if bal <= 0:
        return {"error": "账户可用资金为 0"}
    n = len(codes)
    budget_each = bal * float(budget_percent) / n
    bought, skipped, total_cost = [], [], 0.0
    for c in codes:
        code = c["code"]
        name = c.get("name") or code
        px = c.get("price") or _kline_last_close(code)
        if not px or px <= 0:
            skipped.append({"code": code, "reason": "无有效价格"}); continue
        qty = int(budget_each / px / eng.LOT_SIZE) * eng.LOT_SIZE
        if qty < eng.LOT_SIZE:
            skipped.append({"code": code, "reason": "资金不足一手"}); continue
        order, err = eng.place_order(account_id, code, name, 'buy', 'market',
                                     price=px, qty=qty, current_price=px)
        if order is None:
            skipped.append({"code": code, "reason": err}); continue
        bought.append({"code": code, "name": name, "qty": qty, "price": px})
        total_cost += qty * px
    return {"account_id": account_id, "bought": bought, "skipped": skipped, "total_cost": total_cost}


def pick_at(strategy: str = "D多因子", date: str = None, hp: int = 20,
            top_k_pct: float = 0.2) -> dict:
    """按策略+日期做**该日截面**选股(回测选股快照). 供研究面板'选股历史某日'操作.

    strategy: 策略名(见 STRATEGY_LABELS / _strategy_contracts). date: 'YYYY-MM-DD',
              默认 as_of(最近宽覆盖截面日). 该日因子z-score重算 → composite → top-K,
              返回 {date, strategy, codes:[{code,name,price,chg,comp}], pool_size}.
    口径: 平台因子z于 date 截面(同 forward_paper_run 的单日快照), 宽池, 无前视.
    """
    if strategy not in STRATEGY_LABELS:
        return {"error": f"未知策略 {strategy}"}
    frames = _load_frames()
    if not frames:
        return {"error": "无frames"}
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    as_of = _as_of(close, len(frames))
    if date is None:
        date = str(pd.Timestamp(as_of).date())
    try:
        target = pd.Timestamp(date)
    except Exception:
        return {"error": f"日期无效 {date}"}
    # 快照到<=该日最近交易日(该日无覆盖→取前一日, 避免 None)
    valid = close.index[close.index <= target]
    if len(valid) == 0:
        return {"error": f"{date} 早于数据起点"}
    d = valid[-1]
    contract = _strategy_contracts(hp, top_k_pct=top_k_pct)[strategy]
    # w_value: 该日真实三路信号(与回测一致): RebalancePlanner.plan_at 负责
    planner = RebalancePlanner(contract)
    plan = planner.plan_at(d, frames, holdings={}, cash=contract.initial_balance)
    score = plan.get("score")
    top = plan.get("top", [])
    codes = []
    if score is not None:
        s = score.loc[~score.index.isin(INDEX_CODES)]
        # 该日截面价为 close.loc[d] (不是最新bar), chg 用 d 对前一交易日 —— 诚实反映'该日选股'的价格
        drow = close.loc[d] if d in close.index else None
        d_prev = None
        if d in close.index:
            pi = close.index.get_loc(d)
            if pi > 0:
                d_prev = close.index[pi - 1]
        for c in top:
            if c not in s.index:
                continue
            px = None
            if drow is not None:
                v = drow.get(c)
                if v is not None and not pd.isna(v):
                    px = float(v)
            if px is None:
                last = frames[c]
                px = float(last["close"].iloc[-1])
            chg = 0.0
            if d_prev is not None:
                vp = close.loc[d_prev].get(c)
                if vp is not None and not pd.isna(vp) and float(vp) > 0:
                    chg = (px / float(vp) - 1.0) * 100.0
            codes.append({"code": c, "name": "", "price": round(px, 2),
                          "chg": round(chg, 2), "comp": round(float(score[c]), 3)})
    return {"date": str(pd.Timestamp(d).date()), "strategy": strategy,
            "codes": codes, "pool_size": len(frames), "top_k_pct": top_k_pct}


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


# ── 多策略纸面盘账本(持仓面板数据源) ───────────────────────────
STRATEGY_LABELS = ["F价值Tilt", "D多因子", "A价值", "B反转", "C低波动"]


def _strategy_contracts(hp, top_k_pct=0.2, initial_balance=1_000_000.0):
    """5 个策略家族契约(与 verify 权威组合口径一致). 价值/反转/低波动单因子 + 多因子/tilt."""
    base = dict(top_k_pct=top_k_pct, rebalance_bars=max(1, int(hp)), initial_balance=initial_balance)
    return {
        'F价值Tilt': SelectionContract(factors=["BP", "REVERSAL_20", "VOLATILITY_20"],
                       base_weights={"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}, use_tilt=True, **base),
        'D多因子': SelectionContract(factors=["BP", "REVERSAL_20", "VOLATILITY_20"],
                       base_weights={"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}, use_tilt=False, **base),
        'A价值': SelectionContract(factors=["BP"], base_weights={"BP": 1.0}, use_tilt=True, **base),
        'B反转': SelectionContract(factors=["REVERSAL_20"], base_weights={"REVERSAL_20": 1.0}, use_tilt=False, **base),
        'C低波动': SelectionContract(factors=["VOLATILITY_20"], base_weights={"VOLATILITY_20": -1.0}, use_tilt=False, **base),
    }


def _build_buyhold(close, fwd_start, as_of, grid=None):
    """等权买持基准, 返回 {dates, nav}(nav=相对起点倍数).

    grid: 可选重平衡日列表(与策略同采样), 以便与策略**公平对比**(同为重平衡日快照, 而非日频抖动)."""
    loc = close.loc[(close.index >= pd.Timestamp(fwd_start)) & (close.index <= as_of)]
    if len(loc) < 2:
        return {"dates": [], "nav": []}
    bh = {}
    start_row = loc.iloc[0]
    for c in start_row.index:
        v = start_row.get(c)
        if v is not None and not pd.isna(v) and float(v) > 0:
            bh[c] = float(v)
    dates = list(grid) if grid else [str(ts) for ts in loc.index]
    out_d, nav = [], []
    for ts in dates:
        ts = pd.Timestamp(ts)
        if ts not in close.index:
            continue
        row = close.loc[ts]
        vals, cnt = 0.0, 0
        for c, p0 in bh.items():
            v = row.get(c)
            if v is not None and not pd.isna(v) and float(v) > 0:
                vals += float(v) / p0
                cnt += 1
        if cnt:
            out_d.append(str(ts))
            nav.append(vals / cnt)
    return {"dates": out_d, "nav": nav}


def _persist_paper_runs(as_of, pool_size, hp, fwd_start, selected, runs, buyhold):
    import json as _json
    import numpy as _np
    def _conv(o):
        if isinstance(o, _np.integer): return int(o)
        if isinstance(o, _np.floating): return float(o)
        if isinstance(o, _np.bool_): return bool(o)
        return str(o)
    try:
        with open(os.path.join(os.path.dirname(_ROOT), 'data', 'paper_runs.json'), 'w', encoding='utf-8') as f:
            _json.dump({"as_of": str(pd.Timestamp(as_of).date()), "pool_size": pool_size, "hp": hp,
                        "fwd_start": fwd_start, "selected": selected, "runs": runs, "buyhold": buyhold},
                       f, ensure_ascii=False, indent=1, default=_conv)
    except Exception as e:
        import logging; logging.getLogger('research').warning('paper_runs 持久化失败: %s', repr(e)[:80])


def run_paper_multi(hp=20, top_k_pct=0.2, fwd_start="2024-01-01",
                    strategies=None, selected=None, progress=None) -> dict:
    """跑一组策略契约 → 每策略收益曲线/每日持仓/每笔调仓 → 持久化 data/paper_runs.json(供持仓面板).

    strategies: {name: SelectionContract}; None → 5 策略家族. selected: 默认选中策略名.
    返回 {runs:{name->{dates,nav,daily_holdings,rebalance_log,...}}, buyhold, selected, as_of, pool_size, hp}."""
    frames = _load_frames()
    if not frames:
        return {"error": "无frames"}
    now = datetime.now().strftime("%Y-%m-%d")
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    as_of = _as_of(close, len(frames))
    fwd_end = str(pd.Timestamp(as_of).date())
    contracts = strategies if strategies is not None else _strategy_contracts(hp, top_k_pct)
    names = list(contracts)
    sel = selected if selected in contracts else names[0]
    runs = {}
    for i, name in enumerate(names):
        if progress:
            progress(f"纸面盘 {i+1}/{len(names)} · {name}", round(12 + (i / len(names)) * 56, 0))
        try:
            fw = forward_paper_run(frames, contracts[name], fwd_start, fwd_end, initial_balance=1_000_000.0)
            runs[name] = {
                "dates": fw["dates"], "nav": fw["nav_n"],
                "final_holdings": fw["final_holdings"], "final_cash": fw["final_cash"],
                "turnover_avg": fw["turnover_avg"], "cost_total": fw["cost_total"],
                "rebalances": fw["rebalances"],
                "daily_holdings": fw.get("daily_holdings", []),
                "rebalance_log": fw.get("rebalance_log", []),
            }
        except Exception as e:
            runs[name] = {"error": str(e)}
    if progress:
        progress("计算等权买持基准...", 78.0)
    grid = next((r['dates'] for r in runs.values()
                 if isinstance(r, dict) and not r.get('error') and r.get('dates')), None)
    buyhold = _build_buyhold(close, fwd_start, as_of, grid) if grid else _build_buyhold(close, fwd_start, as_of)
    _persist_paper_runs(as_of, len(frames), hp, fwd_start, sel, runs, buyhold)
    if progress:
        progress("完成", 100.0)
    return {"runs": runs, "buyhold": buyhold, "selected": sel,
            "as_of": str(pd.Timestamp(as_of).date()), "pool_size": len(frames), "hp": hp}


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
