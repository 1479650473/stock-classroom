# -*- coding: utf-8 -*-
"""单标的日线事件驱动回测器 — 完整 A 股建模。

建模约定（关键假设，保证结果可信、无前视偏差）：
- 信号在当日收盘计算 → 次日开盘成交（次开成交，杜绝未来函数）
- T+1：买入当日不可卖出；止损/止盈在开仓后的下一个 bar 才检查（跳过开仓当日）
- 涨跌停：按 board 计算 ±pct（ST 5% / 创业板·科创板 20% / 北交所 30% / 主板 10%），
  涨停价>=次日开盘则禁止买入，跌停价<=次日开盘则禁止卖出
- 整数手：买入数量必为 100 的整数倍，不足 1 手跳过
- 全费用：佣金(双边, 万2.5, 最低5元) + 印花税(卖出, 千0.5) + 过户费(双边, 万0.1)
- 仅做多：A 股 T+1 禁日内回转，默认不允许做空
"""

import math


# ── 费用模型 ──────────────────────────────────────────────────
FEES = {
    "commission_rate": 0.00025,   # 佣金率 (双边)
    "min_commission": 5.0,        # 单笔最低佣金
    "stamp_tax_rate": 0.0005,     # 印花税 (卖出单边)
    "transfer_fee_rate": 0.00001, # 过户费 (双边)
    "lot": 100,                   # 最小交易单位(手)
}


def _fee_buy(qty, price, f):
    amount = qty * price
    commission = max(amount * f["commission_rate"], f["min_commission"])
    transfer = amount * f["transfer_fee_rate"]
    return commission + transfer


def _fee_sell(qty, price, f):
    amount = qty * price
    commission = max(amount * f["commission_rate"], f["min_commission"])
    stamp = amount * f["stamp_tax_rate"]
    transfer = amount * f["transfer_fee_rate"]
    return commission + stamp + transfer


def limit_pct(code, name):
    """按证券类型给出涨跌停幅度。"""
    if name and "ST" in name.upper():
        return 0.05
    if code.startswith(("300", "301", "688", "689")):
        return 0.20
    if code.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


def _limit_prices(prev_close, pct):
    if not prev_close or prev_close <= 0:
        return None, None
    up = round(prev_close * (1 + pct), 2)
    down = round(prev_close * (1 - pct), 2)
    return up, down


class BacktestResult:
    def __init__(self):
        self.equity_curve = []   # [(date, equity)]
        self.trades = []         # [{entry_date, exit_date, side, qty, entry_price, exit_price, pnl, fees}]
        self.errors = []         # 记录被涨跌停拦截等导致未成交的事件(诊断用)

    @property
    def final_equity(self):
        return self.equity_curve[-1][1] if self.equity_curve else 0.0


def run_backtest(spec, klines):
    """spec: StrategySpec；klines: 按时间升序的 dict 列表(需含 date/open/high/low/close/volume)。"""
    from .factors import compute_factor_series
    from .metrics import compute_metrics, buy_hold_equity
    from .protection import ProtectionEngine, ProtectionSpec, ProtectionState
    from backend.factor_engine.dsl import evaluate as _eval_dsl

    f = dict(FEES)
    f.update(spec.params.get("fees", {}))

    res = BacktestResult()
    if not klines:
        res.errors.append("empty klines")
        return res

    code = spec.universe.get("code", "")
    # 注入点时间价值/质量因子(EP/BP/ROE)到 kline dict, 供 compute_factor_series 逐bar产出
    try:
        from ..fundamental import attach_kline_fundamentals
        klines = attach_kline_fundamentals(code, klines)
    except Exception:
        pass

    # 因子序列(逐 bar values)
    series = compute_factor_series(klines)
    n = len(klines)

    initial = spec.params.get("initial_balance", 100000.0)
    cash = initial
    pos = None            # {qty, cost, entry_price, entry_index, prot, name}
    pending = None        # 'buy' | 'sell'

    name = spec.universe.get("name", "")
    pct = limit_pct(code, name)
    stop_loss_pct = spec.risk.stop_loss_pct
    take_profit_pct = spec.risk.take_profit_pct
    prot_spec = ProtectionSpec.from_risk(spec.risk)
    prot_engine = ProtectionEngine(intrabar_mode=spec.risk.intrabar_mode)

    def eval_cond(cond, vals):
        if cond is None:
            return False
        try:
            return bool(_eval_dsl(cond, vals))
        except Exception:
            return False

    def position_sizing_qty(open_price, equity_now):
        if not open_price or open_price <= 0 or not equity_now:
            return 0
        sizing = spec.position_sizing
        if sizing.mode == "fixed_qty":
            want = int(sizing.value)
        elif sizing.mode == "fixed_capital":
            want = int(sizing.value / open_price)
        else:  # percent_of_equity
            want = int(equity_now * sizing.value / open_price)
        qty = (want // f["lot"]) * f["lot"]
        # 用现金约束收紧
        while qty > 0:
            need = qty * open_price + _fee_buy(qty, open_price, f)
            if need <= cash + 1e-9:
                break
            qty -= f["lot"]
        return qty

    def do_buy(bar, idx):
        nonlocal cash, pos
        open_price = bar["open"]
        equity_now = cash  # 空仓时权益=现金
        qty = position_sizing_qty(open_price, equity_now)
        if qty < f["lot"]:
            res.errors.append(f"{bar['date']} 买入量<1手, 跳过")
            return
        # 涨停拦截
        if idx > 0:
            prev_close = klines[idx - 1]["close"]
            up, _ = _limit_prices(prev_close, pct)
            if up is not None and open_price >= up - 1e-9:
                res.errors.append(f"{bar['date']} 涨停(open>=涨停价), 禁止买入")
                return
        fee = _fee_buy(qty, open_price, f)
        cost = qty * open_price + fee
        cash -= cost
        pos = {
            "qty": qty, "cost": cost, "entry_price": open_price,
            "entry_index": idx, "entry_date": bar["date"], "fees": fee,
            "prot": ProtectionState.open(open_price, idx, prot_spec, "long"),
        }

    def do_sell(bar, idx, price=None):
        nonlocal cash, pos
        qty = pos["qty"]
        sell_price = price if price is not None else bar["open"]
        # 跌停拦截(仅在非止损/止盈的次日开盘卖时考虑)
        if price is None and idx > 0:
            prev_close = klines[idx - 1]["close"]
            _, down = _limit_prices(prev_close, pct)
            if down is not None and sell_price <= down + 1e-9:
                res.errors.append(f"{bar['date']} 跌停(open<=跌停价), 禁止卖出")
                return
        fee = _fee_sell(qty, sell_price, f)
        proceeds = qty * sell_price - fee
        pnl = proceeds - pos["cost"]
        cash += proceeds
        res.trades.append({
            "entry_date": pos["entry_date"], "exit_date": bar["date"],
            "side": "long", "qty": qty,
            "entry_price": round(pos["entry_price"], 3), "exit_price": round(sell_price, 3),
            "pnl": round(pnl, 2), "fees": round(pos["fees"] + fee, 2),
        })
        pos = None

    # ── 主循环 ──────────────────────────────────────────────────
    for i in range(n):
        bar = klines[i]
        # 1) 执行上一根收盘延迟下来的动作(次开成交)
        if pending == "buy" and pos is None:
            do_buy(bar, i)
        elif pending == "sell" and pos is not None:
            do_sell(bar, i)
        pending = None

        # 2) 持仓中：保护引擎(止损/移动止损/止盈/时间止损，gap 感知成交价；跳过开仓当日 T+1)
        if pos is not None and i > pos["entry_index"]:
            decision = prot_engine.evaluate_bar(pos["prot"], bar=bar, bar_index=i)
            if decision is not None:
                if decision.reason == "stop_loss":
                    res.errors.append(f"{bar['date']} 止损 @{decision.price:.2f}")
                elif decision.reason == "trailing_stop":
                    res.errors.append(f"{bar['date']} 移动止损 @{decision.price:.2f}")
                elif decision.reason == "take_profit":
                    res.errors.append(f"{bar['date']} 止盈 @{decision.price:.2f}")
                elif decision.reason == "time_limit":
                    res.errors.append(f"{bar['date']} 时间止损 @{decision.price:.2f}")
                do_sell(bar, i, price=decision.price)

        # 3) 收盘信号 → 决定次日动作
        vals = series[i] if i < len(series) else {}
        if pos is None:
            if eval_cond(spec.entry, vals):
                pending = "buy"
        else:
            if eval_cond(spec.exit, vals):
                pending = "sell"

        # 4) 记录权益(收盘市值)
        eq = cash + (pos["qty"] * bar["close"] if pos else 0.0)
        res.equity_curve.append((bar["date"], round(eq, 2)))

    # 期末未平仓 → 按最后收盘强制平仓(不计费, 仅用于结算权益曲线, 不计入 trades)
    # (equity_curve 已使用收盘市值, 无需额外平仓, 只把 state 归零)

    # 基准
    bh_curve = buy_hold_equity(initial, klines)
    bh_ret = (bh_curve[-1][1] / initial - 1.0) if bh_curve and initial else None
    from .metrics import _max_drawdown
    bh_mdd = _max_drawdown(bh_curve) if bh_curve else None

    res.metrics = compute_metrics(res.equity_curve, initial, res.trades, bh_ret, bh_mdd)
    res.initial_balance = initial
    return res
