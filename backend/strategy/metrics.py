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
        # ── 统一口径: 收益/回撤/胜率均为【小数】(0.05=5%)；×100 得百分比 ──
        "total_return": round(total_return, 4),              # 小数, 如 0.5373 = +53.73%
        "cagr": round(cagr, 4),                              # 小数
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(mdd, 4),                       # 小数(负值), 如 -0.2510 = -25.10%
        "num_trades": num,
        "win_rate": round(win_rate, 4),                      # 小数, 如 0.2857 = 28.57%
        "profit_factor": round(profit_factor, 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "buy_hold_return": round(buy_hold_return, 4) if buy_hold_return is not None else None,
        "buy_hold_max_drawdown": round(buy_hold_mdd, 4) if buy_hold_mdd is not None else None,
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


# ══════════════════════════════════════════════════════════════
#  精确多维权衡指标 (供 LLM / 持仓页 / 回测输出) —— 纯函数, 可单测
#  支持: α / β / 年化 / 总收益 / 夏普 / 索提诺 / Calmar / 最大回撤 /
#        胜率 / 盈亏比 / 波动 / 基准对比
#  nav: List[float] 或 pd.Series (策略绝对市值或相对倍数)
#  bench: List[float] (可选, 基准同序列长度)
# ══════════════════════════════════════════════════════════════
def _year_frac(n_bars):
    return n_bars / TRADING_DAYS if n_bars > 0 else 0.0


def full_metrics(nav, bench=None, freq_bars=1, annual_period=TRADING_DAYS):
    """从 nav 序列算全维绩效指标(year-over-year 归一化).

    nav: 权益/净值序列(升序). 若为相对倍数(起点=1)则 total_return 由末值直接给.
    bench: 可选基准序列(同长度), 用于 α/β/超额. 需与 nav 同长度(简化).
    freq_bars: nav 每点间隔 bar 数(重平衡日采样时>1, 用于年化). 默认1(日频).
    Returns dict(小数口径: 0.05=5%), 与 compute_metrics 兼容的键总是一致.
    """
    import math as _m
    n = len(nav)
    if n < 2:
        return {"error": "nav 太短", "n": n}
    first, last = float(nav[0]), float(nav[-1])
    total_return = last / first - 1.0 if first else 0.0
    # 年化: 用实际 bar 间隔数算 (n-1)*freq_bars 个交易日
    n_bars = max(1, (n - 1) * freq_bars)
    years = _year_frac(n_bars)
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0 if (years > 0 and total_return > -1.0) else 0.0

    # 日度/期度收益
    rets = []
    for a, b in zip(nav, nav[1:]):
        if float(a) > 0:
            rets.append(float(b) / float(a) - 1.0)
    if not rets:
        return {"error": "无可算收益", "n": n}
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    std = _m.sqrt(var)
    ann_vol = std * _m.sqrt(annual_period / freq_bars) if std > 0 else 0.0
    sharpe = (mean / std) * _m.sqrt(annual_period / freq_bars) if std > 0 else 0.0
    # 索提诺(下行偏差)
    downside = [r for r in rets if r < 0]
    dstd = _m.sqrt(sum(r ** 2 for r in downside) / (len(downside) or 1))
    sortino = (mean / dstd) * _m.sqrt(annual_period / freq_bars) if dstd > 0 else 0.0
    # 最大回撤
    peak, mdd = None, 0.0
    for v in nav:
        v = float(v)
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd
    calmar = cagr / abs(mdd) if mdd != 0 else (cagr if cagr > 0 else 0.0)

    out = {
        "n_bars": n_bars, "freq_bars": freq_bars,
        "final_equity": round(last, 4),
        "total_return": round(total_return, 4),            # 小数 0.5373=+53.73%
        "cagr": round(cagr, 4),                            # 年化 小数
        "annualized_return": round(cagr, 4),               # 别名(与 cagr 同)
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "max_drawdown": round(mdd, 4),                     # 小数(负)
        "volatility": round(ann_vol, 4),                   # 年化波动
        "start": float(nav[0]), "end": float(nav[-1]),
    }

    # 胜率/盈亏比(需逐笔成交明细; 有则填, 无则 None)
    if bench is not None and len(bench) == n and float(bench[0]) > 0:
        b_ret = float(bench[-1]) / float(bench[0]) - 1.0
        # 日度对齐的 β/α(简化: 用同期收益回归)
        bret = [float(b) / float(a) - 1.0 for a, b in zip(bench, bench[1:]) if float(a) > 0]
        m = min(len(rets), len(bret))
        if m >= 2:
            mu_r, mu_b = sum(rets[:m]) / m, sum(bret[:m]) / m
            covr = sum((rets[i] - mu_r) * (bret[i] - mu_b) for i in range(m)) / (m - 1)
            varb = sum((x - mu_b) ** 2 for x in bret[:m]) / (m - 1)
            beta = covr / varb if varb > 0 else 0.0
            alpha_daily = mu_r - beta * mu_b
            alpha_ann = alpha_daily * (annual_period / freq_bars)
            out["beta"] = round(beta, 3)
            out["alpha"] = round(alpha_ann, 4)             # 年化 α 小数(超额)
            out["excess_return"] = round(total_return - b_ret, 4)
            out["bench_return"] = round(b_ret, 4)
        else:
            out["beta"] = None; out["alpha"] = None
            out["excess_return"] = round(total_return - b_ret, 4) if float(bench[0]) else None
            out["bench_return"] = round(b_ret, 4)
    else:
        out["bench_return"] = None; out["alpha"] = None; out["beta"] = None; out["excess_return"] = None
    return out


def compute_full_metrics(nav, bench=None, dates=None, freq_bars=1):
    """兼容 compute_metrics 键名 + 新增精确维度. nav/bench 为 List[float] 或 Series."""
    import pandas as _pd
    if not hasattr(nav, "__len__") or len(nav) < 2:
        return {"error": "nav 太短"}
    if isinstance(nav, _pd.Series):
        nav = [float(x) for x in nav.tolist()]
    else:
        nav = [float(x) for x in nav]
    if bench is not None:
        if isinstance(bench, _pd.Series):
            bench = [float(x) for x in bench.tolist()]
        else:
            bench = [float(x) for x in bench]
    fm = full_metrics(nav, bench, freq_bars=freq_bars)
    # 复用 compute_metrics 的口径补 win_rate/profit_factor/trades(无明细时 None)
    if "error" in fm:
        return fm
    fm.update({"num_trades": None, "win_rate": None, "profit_factor": None,
               "buy_hold_return": fm.get("bench_return"),
               "buy_hold_max_drawdown": None})
    return fm
