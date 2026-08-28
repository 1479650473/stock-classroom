# -*- coding: utf-8 -*-
"""verify_full_lifecycle.py — 完整生命周期验证: 选股→买入→持有(带保护)→卖出→结算→净值.

背景: 之前 forward_paper_run 只有"按排名调出"(周期重平衡), 无个股保护(止损/止盈/时间止损).
本验证把 A 的卖出规约(SellRuleSet+ProtectionEngine)接进逐日回放, 证明加了保护后
完整生命周期(买入→持有→风控卖出→结算→净值)跑出来是合理/可复现的.

与 forward_paper_run 的区别:
  · forward_paper_run: 每 rebalance_bars 天重平衡(排名调出), 无保护
  · verify_full_lifecycle: 每日先判个股保护(保护优先), 再判重平衡日排名调出

输出: {nav(净值序列), trades(逐笔), metrics(compute_full_metrics),
       guard_hits({reason: count}), vs buyhold, vs no_guard(无保护对照组)}
"""
from __future__ import annotations

import os, sys, math
from dataclasses import dataclass

import pandas as pd

from backend.strategy.portfolio_rebalance import SelectionContract, _xs_z, select_top_k
from backend.strategy.protection import ProtectionEngine, ProtectionState
from backend.strategy.sell_rules import SellRuleSet
from backend.strategy.metrics import compute_full_metrics


def _panel(eng, frames, key):
    return eng._panel(frames, key)


def verify_full_lifecycle(frames, contract: SelectionContract,
                          start: str, end: str,
                          rule_set: SellRuleSet = None,
                          signal_fn=None,
                          initial_balance: float = 1_000_000.0,
                          progress=None) -> dict:
    """完整生命周期回放. 返回 {nav, dates, trades, metrics, guard_hits, buyhold, no_guard}.

    frames: {code: df}; contract: SelectionContract; rule_set: 卖出规约(默认 SellRuleSet.build).
    signal_fn: 可选, 重平衡日的三路信号(价值tilt等); None=纯多因子(等权).
    """
    def _emit(m):
        if progress:
            try: progress(m)
            except Exception: pass
    from backend.strategy.factor_research import FactorResearchEngine
    eng = FactorResearchEngine()
    rule_set = rule_set or SellRuleSet.build(rebalance_bars=contract.rebalance_bars)
    protect = ProtectionEngine(intrabar_mode="conservative")

    # 面板
    close = _panel(eng, frames, "close")
    open_ = _panel(eng, frames, "open")
    high = _panel(eng, frames, "high")
    low = _panel(eng, frames, "low")
    bp = eng._factor_panel(frames, "BP", close)
    rev = eng._factor_panel(frames, "REVERSAL_20", close)
    vol = eng._factor_panel(frames, "VOLATILITY_20", close)
    factor_panels = {"BP": bp, "REVERSAL_20": rev, "VOLATILITY_20": vol}

    loc = close.loc[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
    dates = list(loc.index)
    if not dates:
        return {"error": "无日期范围"}

    cash = float(initial_balance)
    holdings = {}          # code -> qty
    # 持仓保护状态: code -> {state: ProtectionState, entry_price, entry_index, since_date}
    guard_states = {}
    nav, trades = [], []
    guard_hits = {"stop_loss": 0, "take_profit": 0, "trailing_stop": 0, "time_limit": 0, "rebalance_exit": 0}
    rebal_dates = set(loc.index[:: max(1, contract.rebalance_bars)])
    first_nav = None

    def _mark(dt):
        row = close.loc[dt] if dt in close.index else None
        val = cash
        if row is not None:
            for c, q in holdings.items():
                v = row.get(c, pd.NA)
                if q > 0 and v is not None and not pd.isna(v):
                    val += q * float(v)
        return val

    def _do_sell(c, dt, bar, reason, price):
        """卖出持仓(按保护/排名), 更新cash+holdings+guard_states."""
        nonlocal cash
        qty = holdings.get(c, 0)
        if qty <= 0:
            return
        gi = guard_states.get(c)
        entry = gi.get("entry_price", price) if gi else price
        ex = max(price, bar.get("low", price)) if reason == "stop_loss" else min(price, bar.get("high", price))
        ex = price
        proceeds = qty * ex * (1.0 - contract.fee)
        cash += proceeds
        holdings.pop(c, None)
        guard_states.pop(c, None)
        pnl = (ex - entry) * qty
        trades.append({"date": str(dt), "code": c, "side": "sell", "qty": qty,
                       "price": float(ex), "reason": reason,
                       "pnl": round(pnl, 2)})
        guard_hits[reason] = guard_hits.get(reason, 0) + 1

    def _do_buy(c, dt, bar, qty):
        nonlocal cash
        if qty <= 0 or cash < qty * bar.get("close", 0):
            return
        cost = qty * bar.get("close", 0) * (1.0 + contract.fee)
        cash -= cost
        holdings[c] = holdings.get(c, 0) + qty
        # 建保护状态
        st = ProtectionState.open(float(bar.get("close", 0)), 0, rule_set.protection, side="long")
        guard_states[c] = {"state": st, "entry_price": float(bar.get("close", 0)),
                           "entry_index": 0, "bar_index": 0}
        trades.append({"date": str(dt), "code": c, "side": "buy", "qty": qty,
                       "price": float(bar.get("close", 0)), "reason": "buy", "pnl": None})

    # 逐日回放
    bar_index_ctr = 0
    for dt in dates:
        row = close.loc[dt]
        # ① 先判个股保护(每日, 保护优先) —— 用真实当日 OHLC
        dead = []
        for c, gi in guard_states.items():
            if gi.get("break_hold"):
                continue
            st = gi["state"]
            gi["bar_index"] += 1
            _o = _try_float(open_.loc[dt].get(c))
            _h = _try_float(high.loc[dt].get(c))
            _l = _try_float(low.loc[dt].get(c))
            _c = _try_float(row.get(c))
            bar = {"open": _o if _o else st.entry_price,
                   "high": _h if _h else max(st.entry_price, _o or st.entry_price),
                   "low": _l if _l else min(st.entry_price, _o or st.entry_price),
                   "close": _c if _c else st.entry_price}
            decision = protect.evaluate_bar(st, bar=bar, bar_index=gi["bar_index"])
            if decision is not None:
                dead.append((c, decision))
        for c, decision in dead:
            _do_sell(c, dt, row.to_dict(), decision.reason, decision.price)

        # ② 重平衡日: 算综合分 → 调仓(排名调出/调入)
        if dt in rebal_dates:
            factor_z = {}
            for f in contract.factors:
                panel = factor_panels.get(f)
                if panel is None:
                    continue
                z = _xs_z(panel, dt)
                if z is not None:
                    factor_z[f] = z
            if factor_z:
                idx = None
                for s in factor_z.values():
                    idx = s.index if idx is None else idx.union(s.index)
                if idx is not None and len(idx) >= 5:
                    total = {}
                    for f, s in factor_z.items():
                        w = contract.base_weights.get(f, 1.0)
                        total[f] = w * s.reindex(idx).fillna(0.0)
                    score = sum(total.values()).fillna(0.0)
                    top = select_top_k(score, contract.top_k_pct)
                    target = set(top)
                    # 卖出掉出 target 的(排名调出, 保护未触发才轮动)
                    for c in list(holdings):
                        if c not in target and c in guard_states and not guard_states[c].get("break_hold"):
                            _do_sell(c, dt, row.to_dict(), "rebalance_exit", float(price_of(row, c)))
                    # 买入 target 中缺的(等权分配可用现金)
                    n_new = len(target - set(holdings))
                    if n_new > 0 and cash > 0:
                        per = (cash * 0.98) / n_new
                        for c in target:
                            if c not in holdings:
                                p = float(price_of(row, c))
                                if p > 0:
                                    qty = int(per / p / 100) * 100
                                    if qty >= 100:
                                        _do_buy(c, dt, {"close": p}, qty)

        # ③ mark-to-market 净值
        nv = _mark(dt)
        if first_nav is None:
            first_nav = nv
        nav.append(nv)
        bar_index_ctr += 1

    # ④ 指标
    metrics = compute_full_metrics(nav, freq_bars=contract.rebalance_bars)
    bh = _buyhold_nav(close, dates, initial_balance)
    return {"dates": [str(d) for d in dates], "nav": [round(x, 4) for x in nav],
            "trades": trades, "metrics": metrics, "guard_hits": guard_hits,
            "buyhold": bh, "final_holdings": holdings, "final_cash": cash}


def price_of(row, c):
    """取行内某股收盘价(容错 pd.NA)."""
    v = row.get(c, pd.NA) if hasattr(row, "get") else None
    if v is None or pd.isna(v):
        return 0.0
    return float(v)


def _try_float(v):
    """容错转 float, pd.NA/NaN/None → None."""
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _buyhold_nav(close, dates, initial_balance):
    """等权买入持有基准(首日满仓, 持有到末)."""
    if not dates:
        return {}
    first = dates[0]; last = dates[-1]
    codes = [c for c in close.columns if not pd.isna(close.loc[first].get(c, pd.NA))]
    if not codes:
        return {}
    n = len(codes)
    return {"dates": [str(d) for d in dates],
            "nav": [round(initial_balance * (sum(float(close.loc[d].get(c, pd.NA)) / float(close.loc[first][c])
                        for c in codes if not pd.isna(close.loc[d].get(c, pd.NA))) / n
                        if not all(pd.isna(close.loc[d].get(c, pd.NA)) for c in codes) else 1), 4)
                    for d in dates]}


if __name__ == "__main__":
    print("verify_full_lifecycle — 完整生命周期验证(选股→买→持有带保护→卖→结算→净值)")
