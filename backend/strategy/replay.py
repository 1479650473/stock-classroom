# -*- coding: utf-8 -*-
"""replay.py — 策略 K 线回放引擎 (Web「策略回放器」数据源) v2.

真实交易环境模拟:
  · 口径: 信号当日收盘计算 → 次日开盘成交(无未来函数); T+1 禁当日卖出
  · 涨跌停拦截(按 board ±pct); 整数手(100股); 全费用(佣金+最低佣金+印花税+过户费)
  · 滑点: 买入价上浮 / 卖出价下浮
  · 买入方式: percent_of_equity(仓位比例) / fixed_capital(固定金额) / fixed_qty(固定股数)
  · 三驱动卖出: 条件止损 + 移动止损 + 策略卖出(与 backtest/protection 同一判定器)
  · warmup_bars: 区间起点前的预热K线(算因子/均线), 回放输出从 warmup 之后开始,
    保证起止日期区间内因子/信号准确(如 BP_MA120 需要 60+ 根预热)

输出:
  bars: 区间内 [{date, open, high, low, close, volume}]
  daily: 逐日 [{i, date, close, signal_buy/sell, position, qty, entry_price, entry_index,
                 cash, market_value, equity, float_pnl, realized_pnl, cum_fee}]
  events: 买卖事件(含费用/净盈亏/持有bar数)
  holding_spans: 持仓区间(区间内索引)
  metrics: 收益/胜率/盈亏比/最大回撤/累计费用/期末现金
"""
from __future__ import annotations

from typing import Optional

from backend.strategy.backtest import limit_pct, _limit_prices, FEES
from backend.strategy.protection import ProtectionEngine, ProtectionState
from backend.factor_engine.dsl import evaluate as _eval_dsl


def _build_prot_spec(contract: dict):
    from backend.strategy.protection import ProtectionSpec
    risk = contract.get("risk") or {}
    return ProtectionSpec(
        stop_loss_pct=float(risk.get("stop_loss_pct") or 0.0),
        take_profit_pct=float(risk.get("take_profit_pct") or 0.0),
        trailing_stop_pct=float(risk.get("trailing_stop_pct") or 0.0),
        trailing_activation_pct=float(risk.get("trailing_activation_pct") or 0.0),
        intrabar_mode=str(risk.get("intrabar_mode") or "conservative"),
        time_limit_bars=int(risk.get("time_limit_bars") or 0),
    )


def _eval(cond, vals: dict) -> bool:
    if not cond:
        return False
    try:
        return bool(_eval_dsl(cond, vals))
    except Exception:
        return False


# ── 5 家族组合策略 → 单标的 DSL 近似契约(供回放器观察单股走势) ──
# 家族策略本质是截面选股(组合层), 回放到单标的时用其因子方向做时间序列近似:
#   价值(BP低) → BP 低于自身120日均线(相对便宜); 反转 → REVERSAL_20 高; 低波动 → VOLATILITY_20 低.
FAMILY_DSL = {
    "A价值": {
        "entry": {"type": "lt", "args": ["BP", "BP_MA120"]},
        "exit": {"type": "gt", "args": ["BP", "BP_MA20"]},
    },
    "B反转": {
        "entry": {"type": "gt", "args": ["REVERSAL_20", 0.05]},
        "exit": {"type": "lt", "args": ["REVERSAL_20", -0.02]},
    },
    "C低波动": {
        "entry": {"type": "lt", "args": ["VOLATILITY_20", 0.02]},
        "exit": {"type": "gt", "args": ["VOLATILITY_20", 0.03]},
    },
    "D多因子": {
        "entry": {"type": "and", "args": [
            {"type": "lt", "args": ["BP", "BP_MA120"]},
            {"type": "gt", "args": ["REVERSAL_20", -0.03]},
            {"type": "lt", "args": ["VOLATILITY_20", 0.03]},
        ]},
        "exit": {"type": "or", "args": [
            {"type": "gt", "args": ["BP", "BP_MA20"]},
            {"type": "gt", "args": ["VOLATILITY_20", 0.05]},
        ]},
    },
    "F价值Tilt": {
        "entry": {"type": "and", "args": [
            {"type": "lt", "args": ["BP", "BP_MA120"]},
            {"type": "gt", "args": ["REVERSAL_20", -0.03]},
            {"type": "lt", "args": ["VOLATILITY_20", 0.03]},
        ]},
        "exit": {"type": "or", "args": [
            {"type": "gt", "args": ["BP", "BP_MA20"]},
            {"type": "gt", "args": ["VOLATILITY_20", 0.05]},
        ]},
    },
}


def family_to_single_contract(name: str) -> Optional[dict]:
    dsl = FAMILY_DSL.get(name)
    if not dsl:
        return None
    return {
        "name": f"{name}(单标的回放近似)",
        "description": "5家族组合策略的单标的近似(观察单股买/卖点用, 非组合口径)",
        "universe": {"code": "", "name": name},
        "entry": dsl["entry"],
        "exit": dsl["exit"],
        "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
        "risk": {"stop_loss_pct": 0.08, "take_profit_pct": 0.0,
                 "trailing_stop_pct": 0.10, "trailing_activation_pct": 0.15,
                 "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
        "params": {"initial_balance": 100000.0},
    }


def _fee_buy(qty: float, price: float, f: dict) -> float:
    amount = qty * price
    commission = max(amount * f["commission_rate"], f.get("min_commission", 0.0))
    transfer = amount * f.get("transfer_fee_rate", 0.0)
    return commission + transfer


def _fee_sell(qty: float, price: float, f: dict) -> float:
    amount = qty * price
    commission = max(amount * f["commission_rate"], f.get("min_commission", 0.0))
    stamp = amount * f.get("stamp_tax_rate", 0.0)
    transfer = amount * f.get("transfer_fee_rate", 0.0)
    return commission + stamp + transfer


def replay_contract(klines: list, contract: dict, overrides: dict = None,
                    warmup_bars: int = 0) -> dict:
    """逐日回放, 输出区间内(从 warmup_bars 起)的展示数据.

    overrides: {initial_balance, fees:{commission_rate,min_commission,stamp_tax_rate},
                slippage, sizing_mode, sizing_value}
    """
    from backend.strategy.factors import compute_factor_series
    if not klines:
        return {"error": "无K线数据"}

    overrides = overrides or {}
    fees = dict(FEES)
    fees.update(overrides.get("fees") or {})
    slippage = float(overrides.get("slippage") or 0.0)
    initial = float(overrides.get("initial_balance")
                    or (contract.get("params") or {}).get("initial_balance") or 100000.0)

    sizing = dict(contract.get("position_sizing") or {})
    if overrides.get("sizing_mode"):
        sizing["mode"] = overrides["sizing_mode"]
    if overrides.get("sizing_value") is not None:
        sizing["value"] = float(overrides["sizing_value"])

    code = (contract.get("universe") or {}).get("code", "")
    try:
        from backend.fundamental import attach_kline_fundamentals
        klines = attach_kline_fundamentals(code, klines)
    except Exception:
        pass

    series = compute_factor_series(klines)
    n = len(klines)

    name = (contract.get("universe") or {}).get("name", "")
    pct = limit_pct(code, name)
    prot_spec = _build_prot_spec(contract)
    prot_engine = ProtectionEngine(intrabar_mode=prot_spec.intrabar_mode)

    sizing_mode = sizing.get("mode", "percent_of_equity")
    sizing_value = float(sizing.get("value", 0.95))

    cash = initial
    realized = 0.0
    cum_fee = 0.0
    pos = None          # {qty, entry_price_exec, entry_fee, entry_index, entry_date, prot}
    pending = None      # 'buy' | 'sell'

    bars_out: list = []
    daily: list = []
    events: list = []
    spans: list = []
    equity_hist: list = []

    def position_qty(open_price, equity_now):
        if not open_price or open_price <= 0 or not equity_now:
            return 0
        if sizing_mode == "fixed_qty":
            want = int(sizing_value)
        elif sizing_mode == "fixed_capital":
            want = int(sizing_value / open_price)
        else:
            want = int(equity_now * sizing_value / open_price)
        qty = (want // fees["lot"]) * fees["lot"]
        while qty > 0:
            need = qty * open_price * (1.0 + slippage) + _fee_buy(qty, open_price * (1.0 + slippage), fees)
            if need <= cash + 1e-9:
                break
            qty -= fees["lot"]
        return qty

    def do_buy(i):
        nonlocal cash, pos, cum_fee
        bar = klines[i]
        open_price = float(bar["open"])
        exec_price = open_price * (1.0 + slippage)
        qty = position_qty(open_price, cash)
        if qty < fees["lot"]:
            return None
        if i > 0:
            prev_close = float(klines[i - 1]["close"])
            up, _ = _limit_prices(prev_close, pct)
            if up is not None and open_price >= up - 1e-9:
                return None
        fee = _fee_buy(qty, exec_price, fees)
        cost = qty * exec_price + fee
        cash -= cost
        cum_fee += fee
        pos = {
            "qty": qty, "entry_price_exec": exec_price, "entry_fee": fee,
            "entry_index": i, "entry_date": str(bar["date"]),
            "prot": ProtectionState.open(exec_price, i, prot_spec, "long"),
        }
        return {"kind": "entry", "price": round(exec_price, 3), "qty": qty, "fee": round(fee, 2)}

    def do_sell(i, price=None, reason="exit_signal"):
        nonlocal cash, pos, realized, cum_fee
        bar = klines[i]
        base_price = float(price if price is not None else bar["open"])
        exec_price = base_price * (1.0 - slippage)
        if price is None and i > 0:
            prev_close = float(klines[i - 1]["close"])
            _, down = _limit_prices(prev_close, pct)
            if down is not None and base_price <= down + 1e-9:
                return None
        qty = pos["qty"]
        fee = _fee_sell(qty, exec_price, fees)
        proceeds = qty * exec_price - fee
        gross = (exec_price - pos["entry_price_exec"]) * qty
        net = gross - pos["entry_fee"] - fee
        cash += proceeds
        realized += net
        cum_fee += fee
        # 持仓区间裁剪到展示窗口: 建仓早于窗口起点 → 从0开始; 平仓早于窗口起点 → 丢弃
        exit_disp = i - warmup_bars
        if exit_disp < 0:
            pass  # 平仓在窗口外, 不显示
        else:
            entry_disp = pos["entry_index"] - warmup_bars
            spans.append([max(0, entry_disp), exit_disp])
        ev = {"kind": "exit", "price": round(exec_price, 3), "reason": reason,
              "qty": qty, "fee": round(fee, 2),
              "gross_pnl": round(gross, 2), "net_pnl": round(net, 2),
              "entry_date": pos["entry_date"],
              "entry_price": round(pos["entry_price_exec"], 3),
              "hold_bars": i - pos["entry_index"],
              "index": i - warmup_bars, "date": str(bar["date"])}
        pos = None
        return ev

    for i in range(n):
        bar = klines[i]
        close = float(bar["close"])

        # ① 执行昨收延迟信号(次开成交)
        if pending == "buy" and pos is None:
            ev = do_buy(i)
            if ev:
                ev["index"] = i - warmup_bars
                ev["date"] = str(bar["date"])
                events.append(ev)
        elif pending == "sell" and pos is not None:
            ev = do_sell(i, reason="exit_signal")
            if ev:
                events.append(ev)
        pending = None

        # ② 持仓中: 三驱动保护判定(T+1 跳过开仓当日)
        if pos is not None and i > pos["entry_index"]:
            decision = prot_engine.evaluate_bar(pos["prot"], bar=bar, bar_index=i)
            if decision is not None:
                ev = do_sell(i, price=decision.price, reason=decision.reason)
                if ev:
                    events.append(ev)

        # ③ 收盘信号(→ 次日开盘执行)
        vals = series[i] if i < len(series) else {}
        sig_buy = sig_sell = False
        if pos is None:
            if _eval(contract.get("entry"), vals):
                sig_buy = True
                pending = "buy"
        else:
            if _eval(contract.get("exit"), vals):
                sig_sell = True
                pending = "sell"

        # ④ 账户快照(收盘)
        if pos is not None:
            qty = pos["qty"]
            ep = pos["entry_price_exec"]
            mv = qty * close
            float_pnl = (close - ep) * qty
            entry_idx = pos["entry_index"]
            entry_price = ep
        else:
            qty, mv, float_pnl = 0, 0.0, 0.0
            entry_idx, entry_price = -1, 0.0
        equity = cash + mv
        equity_hist.append(equity)

        if i >= warmup_bars:
            bars_out.append({
                "date": str(bar["date"]),
                "open": float(bar["open"]), "high": float(bar["high"]),
                "low": float(bar["low"]), "close": close,
                "volume": float(bar.get("volume", 0) or 0),
                # 均线由 enrich_kline 在含预热段的完整序列上计算, 播放头第一根即有值
                "ma5": bar.get("ma5"), "ma10": bar.get("ma10"),
                "ma20": bar.get("ma20"), "ma60": bar.get("ma60"),
            })
            daily.append({
                "i": i - warmup_bars,
                "date": str(bar["date"]),
                "close": round(close, 3),
                "signal_buy": sig_buy,
                "signal_sell": sig_sell,
                "position": bool(pos),
                "qty": qty,
                "entry_price": round(entry_price, 3),
                "entry_index": entry_idx - warmup_bars if entry_idx >= 0 else -1,
                "cash": round(cash, 2),
                "market_value": round(mv, 2),
                "equity": round(equity, 2),
                "float_pnl": round(float_pnl, 2),
                "realized_pnl": round(realized, 2),
                "cum_fee": round(cum_fee, 2),
            })

    # 过滤/对齐事件到区间内
    events = [e for e in events if e.get("index", -1) >= 0]

    # 期末权益(按最后收盘)
    final_eq = cash
    if pos is not None:
        final_eq += pos["qty"] * float(klines[-1]["close"])

    # 最大回撤(区间内 equity 序列)
    peak, mdd = None, 0.0
    for v in equity_hist[warmup_bars:] if warmup_bars < len(equity_hist) else equity_hist:
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd

    # 统计(区间内平仓)
    exits = [e for e in events if e["kind"] == "exit"]
    wins = [e for e in exits if e.get("net_pnl", 0) > 0]
    losses = [e for e in exits if e.get("net_pnl", 0) <= 0]
    gp = sum(e.get("net_pnl", 0) for e in wins) or 0.0
    gl = abs(sum(e.get("net_pnl", 0) for e in losses)) or 0.0

    return {
        "code": code,
        "contract_name": contract.get("name", ""),
        "bars": bars_out,
        "daily": daily,
        "events": events,
        "holding_spans": [s for s in spans if s[1] >= 0],
        "metrics": {
            "total_return": round(final_eq / initial - 1.0, 4) if initial else 0.0,
            "final_equity": round(final_eq, 2),
            "final_cash": round(cash, 2),
            "initial_balance": round(initial, 2),
            "num_trades": len(exits),
            "win_rate": round(len(wins) / len(exits), 4) if exits else 0.0,
            "profit_factor": round(gp / gl, 3) if gl > 0 else (999.0 if gp > 0 else 0.0),
            "cum_fee": round(cum_fee, 2),
            "realized_pnl": round(realized, 2),
            "max_drawdown": round(mdd, 4),
        },
    }
