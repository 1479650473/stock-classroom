# -*- coding: utf-8 -*-
"""replay.py — 策略 K 线回放引擎 (Web「策略回放器」数据源).

复用 backtest.py 的完整交易模拟口径(次开成交 / T+1 / 三驱动卖出 / 涨跌停拦截 / 全费用),
但为**逐日回放可视化**输出:
  每日信号(signal_buy/signal_sell) + 建仓/平仓事件(entry_price/exit_price/exit_reason)
  + 持仓区间(holding_spans) —— 前端用这些画 K 线高亮与买/卖点标记.

口径与 verify_full_lifecycle 一致: 信号在当日收盘后计算, 次日开盘成交(无未来函数)。
"""
from __future__ import annotations

from typing import Optional

from backend.strategy.backtest import limit_pct, _limit_prices, _fee_buy, _fee_sell, FEES
from backend.strategy.protection import ProtectionEngine, ProtectionState
from backend.factor_engine.dsl import evaluate as _eval_dsl


def _build_prot_spec(contract: dict) -> object:
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
    """DSL 条件求值; 空/None 条件=False(不触发)."""
    if not cond:
        return False
    try:
        return bool(_eval_dsl(cond, vals))
    except Exception:
        return False


# ── 5 家族组合策略 → 单标的 DSL 近似契约(供回放器观察单股走势) ──
# 家族策略本质是截面选股(组合层), 回放到单标的时用其因子方向做时间序列近似:
#   价值(BP低) → BP < 阈值; 反转 → REVERSAL_20 高; 低波动 → VOLATILITY_20 低.
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
    """家族策略名 → 单标的 DSL 契约(回放观察用). 未知家族返回 None."""
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


def replay_contract(klines: list, contract: dict) -> dict:
    """按策略契约逐日回放单标的 K 线, 输出回放数据.

    klines: [{date, open, high, low, close, volume, ...}] 时间升序
    contract: StrategySpec.to_dict() 结构 {entry, exit, position_sizing, risk, params, universe}
    returns:
      {
        dates: [...],            # 日期轴
        daily: [{i, date, close, signal_buy, signal_sell, position}],  # 逐日信号/持仓
        events: [{index, date, kind: entry|exit, price, reason, qty, pnl}],
        holding_spans: [[start_i, end_i], ...],   # 半开区间 end_i 为平仓日
        metrics: {total_return, num_trades, win_rate, profit_factor, final_equity},
        contract_name
      }
    """
    from backend.strategy.factors import compute_factor_series
    if not klines:
        return {"error": "无K线数据"}

    # 注入基本面点时间因子(EP/BP/ROE)
    code = (contract.get("universe") or {}).get("code", "")
    try:
        from backend.fundamental import attach_kline_fundamentals
        klines = attach_kline_fundamentals(code, klines)
    except Exception:
        pass

    series = compute_factor_series(klines)
    n = len(klines)

    fees = dict(FEES)
    fees.update((contract.get("params") or {}).get("fees", {}))
    initial = float((contract.get("params") or {}).get("initial_balance", 100000.0))

    name = (contract.get("universe") or {}).get("name", "")
    pct = limit_pct(code, name)
    prot_spec = _build_prot_spec(contract)
    prot_engine = ProtectionEngine(intrabar_mode=prot_spec.intrabar_mode)

    sizing = contract.get("position_sizing") or {}
    sizing_mode = sizing.get("mode", "percent_of_equity")
    sizing_value = float(sizing.get("value", 0.95))

    cash = initial
    pos = None          # {qty, cost, entry_price, entry_index, entry_date, prot, name}
    pending = None      # 'buy' | 'sell'

    daily = []
    events = []
    spans = []

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
            need = qty * open_price + _fee_buy(qty, open_price, fees)
            if need <= cash + 1e-9:
                break
            qty -= fees["lot"]
        return qty

    def do_buy(i):
        nonlocal cash, pos
        bar = klines[i]
        open_price = float(bar["open"])
        qty = position_qty(open_price, cash)
        if qty < fees["lot"]:
            return None
        if i > 0:
            prev_close = float(klines[i - 1]["close"])
            up, _ = _limit_prices(prev_close, pct)
            if up is not None and open_price >= up - 1e-9:
                return None
        fee = _fee_buy(qty, open_price, fees)
        cost = qty * open_price + fee
        cash -= cost
        pos = {
            "qty": qty, "cost": cost, "entry_price": open_price,
            "entry_index": i, "entry_date": str(bar["date"]),
            "prot": ProtectionState.open(open_price, i, prot_spec, "long"),
        }
        return {"kind": "entry", "price": open_price, "qty": qty}

    def do_sell(i, price=None, reason="exit"):
        nonlocal cash, pos
        bar = klines[i]
        sell_price = float(price if price is not None else bar["open"])
        if price is None and i > 0:
            prev_close = float(klines[i - 1]["close"])
            _, down = _limit_prices(prev_close, pct)
            if down is not None and sell_price <= down + 1e-9:
                return None
        qty = pos["qty"]
        fee = _fee_sell(qty, sell_price, fees)
        proceeds = qty * sell_price - fee
        pnl = proceeds - pos["cost"]
        cash += proceeds
        spans.append([pos["entry_index"], i])
        ev = {"kind": "exit", "price": round(sell_price, 3), "reason": reason,
              "qty": qty, "pnl": round(pnl, 2),
              "entry_date": pos["entry_date"],
              "entry_price": pos["entry_price"]}
        pos = None
        return ev

    for i in range(n):
        bar = klines[i]
        close = float(bar["close"])

        # ① 执行昨收延迟信号(次开成交)
        if pending == "buy" and pos is None:
            ev = do_buy(i)
            if ev:
                ev["index"], ev["date"] = i, str(bar["date"])
                events.append(ev)
        elif pending == "sell" and pos is not None:
            ev = do_sell(i, reason="exit_signal")
            if ev:
                ev["index"], ev["date"] = i, str(bar["date"])
                events.append(ev)
        pending = None

        # ② 持仓中: 三驱动保护判定(T+1 跳过开仓当日)
        if pos is not None and i > pos["entry_index"]:
            decision = prot_engine.evaluate_bar(pos["prot"], bar=bar, bar_index=i)
            if decision is not None:
                ev = do_sell(i, price=decision.price, reason=decision.reason)
                if ev:
                    ev["index"], ev["date"] = i, str(bar["date"])
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

        # ④ 当日记录
        daily.append({
            "i": i,
            "date": str(bar["date"]),
            "close": round(close, 3),
            "signal_buy": sig_buy,
            "signal_sell": sig_sell,
            "position": bool(pos),
        })

    # 期末未平仓(按收盘市值计净值, 不计 events)
    final_eq = cash
    if pos is not None:
        final_eq += pos["qty"] * float(klines[-1]["close"])

    # 统计
    exits = [e for e in events if e["kind"] == "exit"]
    wins = [e for e in exits if e.get("pnl", 0) > 0]
    losses = [e for e in exits if e.get("pnl", 0) <= 0]
    gp = sum(e.get("pnl", 0) for e in wins) or 0.0
    gl = abs(sum(e.get("pnl", 0) for e in losses)) or 0.0

    return {
        "code": code,
        "contract_name": contract.get("name", ""),
        "dates": [d["date"] for d in daily],
        "daily": daily,
        "events": events,
        "holding_spans": spans,
        "metrics": {
            "total_return": round(final_eq / initial - 1.0, 4) if initial else 0.0,
            "final_equity": round(final_eq, 2),
            "initial_balance": round(initial, 2),
            "num_trades": len(exits),
            "win_rate": round(len(wins) / len(exits), 4) if exits else 0.0,
            "profit_factor": round(gp / gl, 3) if gl > 0 else (999.0 if gp > 0 else 0.0),
        },
    }
