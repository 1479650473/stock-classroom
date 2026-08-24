# -*- coding: utf-8 -*-
"""回测绩效指标 — 从权益曲线 & 成交明细计算年化/夏普/最大回撤/胜率/盈亏比。"""

import math

TRADING_DAYS = 252


def _annualized_sharpe(equity_curve):
    """基于日度收益的年化夏普比(无风险利率按 0)。"""
    if len(equity_curve) < 3:
        return 0.0
    rets = []
    prev = equity_curve[0][1]   # equity 值，不是 (date, equity) 元组
    for _, eq in equity_curve[1:]:
        if prev and prev > 0:
            rets.append(eq / prev - 1.0)
        prev = eq
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS)


def _max_drawdown(equity_curve):
    peak = None
    mdd = 0.0
    for _, eq in equity_curve:
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (eq - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd


def compute_metrics(equity_curve, initial_balance, trades,
                    buy_hold_return=None, buy_hold_mdd=None):
    """equity_curve: [(date, equity), ...]; trades: [{pnl, side, ...}]。"""
    if not equity_curve:
        return {"error": "no equity curve"}

    final = equity_curve[-1][1]
    total_return = final / initial_balance - 1.0 if initial_balance else 0.0

    n_bars = len(equity_curve)
    # 年化收益: (1+R)^(252/n) - 1；用实际 bar 数近似年化
    cagr = 0.0
    if total_return > -1.0 and n_bars > 0:
        years = n_bars / TRADING_DAYS
        if years > 0:
            cagr = (1.0 + total_return) ** (1.0 / years) - 1.0

    sharpe = _annualized_sharpe(equity_curve)
    mdd = _max_drawdown(equity_curve)

    closed = [t for t in trades if t.get("pnl") is not None]
    num = len(closed)
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    win_rate = (len(wins) / num) if num else 0.0

    gross_profit = sum(t["pnl"] for t in wins) or 0.0
    gross_loss = abs(sum(t["pnl"] for t in losses)) or 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0)

    return {
        "bars": n_bars,
        "initial_balance": round(initial_balance, 2),
        "final_equity": round(final, 2),
        "total_return": round(total_return * 100, 2),         # %
        "cagr": round(cagr * 100, 2),                          # %
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(mdd * 100, 2),                   # %(负值)
        "num_trades": num,
        "win_rate": round(win_rate * 100, 2),                  # %
        "profit_factor": round(profit_factor, 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "buy_hold_return": round(buy_hold_return * 100, 2) if buy_hold_return is not None else None,
        "buy_hold_max_drawdown": round(buy_hold_mdd * 100, 2) if buy_hold_mdd is not None else None,
    }


def buy_hold_equity(initial_balance, klines):
    """买入并持有基准权益曲线：首根开盘满仓买入，持有到末根收盘。"""
    if not klines:
        return []
    first_open = klines[0]["open"]
    curve = []
    if not first_open or first_open <= 0:
        return []
    for k in klines:
        curve.append((k["date"], round(initial_balance * k["close"] / first_open, 2)))
    return curve
