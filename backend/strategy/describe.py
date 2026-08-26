# -*- coding: utf-8 -*-
"""describe.py — 把策略契约渲染成人类可读的"买入/持有/卖出"条件原理.

支撑两类策略:
 ① 单标的 DSL 契约 (dict: entry/exit/risk/position_sizing) —— LLM 生成的策略;
 ② 组合多因子 SelectionContract (factors/base_weights/top_k_pct/rebalance_bars/use_tilt)
    —— F价值Tilt/D多因子/A价值/B反转/C低波动 等因子家族.

纯函数, 供持仓页/研究面板/LLM 反馈/回测输出复用.
"""

# 因子 → 中文名(单标的 DSL 与截面因子共用)
FACTOR_CN = {
    "CLOSE": "收盘价", "OPEN": "开盘价", "HIGH": "最高价", "LOW": "最低价",
    "VOLUME": "成交量", "AMOUNT": "成交额", "TURNOVER": "换手率",
    "MA5": "5日均线", "MA10": "10日均线", "MA20": "20日均线", "MA40": "40日均线",
    "MA60": "60日均线", "RSI14": "RSI(14)", "RSI_14": "RSI(14)",
}

FACTOR_CN.update({
    "MOMENTUM_5": "5日动量", "MOMENTUM_10": "10日动量", "MOMENTUM_20": "20日动量",
    "MOMENTUM_40": "40日动量", "MOMENTUM_60": "60日动量",
    "REVERSAL_5": "5日反转", "REVERSAL_10": "10日反转", "REVERSAL_20": "20日反转",
    "VOLATILITY_5": "5日波动", "VOLATILITY_10": "10日波动", "VOLATILITY_20": "20日波动",
    "VOLATILITY_60": "60日波动",
    "EP": "盈利收益率(EP=1/PE)", "BP": "账面市值比(BP=1/PB)", "ROE": "净资产收益率(ROE)",
    "MA5_GT_MA10": "5日均线在10日均线上", "MA10_GT_MA20": "10日均线在20日均线上",
    "CLOSE_GT_MA20": "收盘价高于20日均线",
    "MA5_CROSS_UP_MA10": "5日均线上穿10日线", "MA5_CROSS_DOWN_MA10": "5日均线下穿10日线",
    "MACD_CROSS_UP": "MACD金叉", "MACD_CROSS_DOWN": "MACD死叉",
    "MACD_DIF": "MACD-DIF", "MACD_DEA": "MACD-DEA", "VOL_RATIO_5": "5日量比",
})

FACTOR_DIR_CN = {"BP": "价值(账面市值比)", "REVERSAL_20": "20日反转", "VOLATILITY_20": "20日低波动"}


def _fact(f):
    return FACTOR_CN.get(f, f)


def _op_cn(op):
    return {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "neq": "≠",
            "between": "介于", "cross_above": "上穿", "cross_below": "下穿"}.get(op, op)


def _fmt_num(x):
    try:
        v = float(x)
    except Exception:
        return str(x)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}"


def render_dsl(cond, depth=0) -> str:
    """把 DSL 条件树渲染成中文句子."""
    if not cond:
        return "无"
    t = cond.get("type")
    args = cond.get("args", [])
    if t == "and":
        return "且 ".join(render_dsl(a, depth + 1) for a in args)
    if t == "or":
        return "或 ".join(render_dsl(a, depth + 1) for a in args)
    if t == "not":
        return "非(" + render_dsl(args[0], depth + 1) + ")"
    if t == "true":
        return "总是"
    if t in ("gt", "gte", "lt", "lte", "eq", "neq"):
        return f"{_fact(str(args[0]))} {_op_cn(t)} {_fmt_num(args[1])}"
    if t == "between":
        return f"{_fact(str(args[0]))} 介于 {_fmt_num(args[1])} ~ {_fmt_num(args[2])}"
    if t == "cross_above":
        return f"{_fact(str(args[0]))} 上穿 {_fact(str(args[1]))}"
    if t == "cross_below":
        return f"{_fact(str(args[0]))} 下穿 {_fact(str(args[1]))}"
    return f"{t}({', '.join(str(a) for a in args)})"


def describe_single_stock(contract: dict) -> dict:
    """单标的 DSL 策略 → 买入/持有/卖出中文条件."""
    entry = contract.get("entry")
    exit_c = contract.get("exit")
    risk = contract.get("risk") or {}
    pos = contract.get("position_sizing") or {}
    slot = contract.get("universe") or {}
    code = slot.get("code", "")
    name = slot.get("name", code)
    buy = render_dsl(entry) if entry else "无明确进场条件"
    sell_parts = []
    if exit_c:
        sell_parts.append("信号离场: " + render_dsl(exit_c))
    sl = risk.get("stop_loss_pct")
    tp = risk.get("take_profit_pct")
    if sl:
        sell_parts.append(f"止损 {float(sl)*100:.0f}%")
    if tp:
        sell_parts.append(f"止盈 {float(tp)*100:.0f}%")
    ts = risk.get("trailing_stop_pct")
    if ts:
        sell_parts.append(f"移动止损 {float(ts)*100:.0f}%")
    if not sell_parts:
        sell_parts.append("无明确卖出条件(仅按进场信号持有)")
    how_many = pos.get("value")
    holding = f"满仓 {float(how_many)*100:.0f}%" if how_many else "按仓位规则"
    return {
        "kind": "单标的",
        "universe": f"{name} ({code})",
        "buy_condition": buy,
        "position_sizing": holding,
        "sell_conditions": "；".join(sell_parts),
        "has_sell_condition": bool(sell_parts and "无明确" not in "；".join(sell_parts)),
        "strategy_name": contract.get("name", ""),
        "description": contract.get("description", ""),
    }


def describe_multi_factor(contract) -> dict:
    """组合多因子 SelectionContract → 买入/持有/卖出中文条件."""
    facs = contract.factors
    w = contract.base_weights
    factor_str = ""
    for f in facs:
        wv = w.get(f, 1.0)
        label = FACTOR_DIR_CN.get(f, _fact(f))
        if not factor_str:
            factor_str = ("- " + label) if wv < 0 else label
        else:
            factor_str += (" - " + label) if wv < 0 else (" + " + label)
    k = contract.top_k_pct
    slot = round(k * 100) if k < 1 else int(k)
    hold_bars = contract.rebalance_bars
    buy = (f"截面综合分 = {factor_str}; 每 {hold_bars} 交易日重平衡, "
           f"取综合分前 {slot}% 作为目标组合等权买入")
    tilt = ""
    if getattr(contract, "use_tilt", False):
        tilt = "; 价值层权重随组合价值信号调节(收缩/顺风增配价值, 扩张/逆风减配)"
    sell = (f"下个重平衡日(每 {hold_bars} 交易日)综合分跌出前 {slot}% 的个股被卖出调出; "
            f"无独立止损/止盈, 只按因子分定期轮动调仓")
    return {
        "kind": "组合因子",
        "strategy_name": getattr(contract, "name", ""),
        "factors": facs,
        "base_weights": {f: w.get(f, 1.0) for f in facs},
        "top_k_pct": k,
        "rebalance_bars": hold_bars,
        "use_tilt": getattr(contract, "use_tilt", False),
        "buy_condition": buy,
        "hold_period": f"每 {hold_bars} 交易日(约 {hold_bars:.0f} 个交易日)重平衡一次",
        "sell_conditions": sell + tilt,
        "has_sell_condition": True,
    }


def describe_contract(contract) -> dict:
    """入口: 自动识别单标的 DSL vs 组合多因子."""
    if isinstance(contract, dict) and ("entry" in contract or "factors" in contract):
        if "entry" in contract:
            return describe_single_stock(contract)
        # dict 形式的 factor contract
        return describe_multi_factor(_to_sel(contract))
    # SelectionContract dataclass
    return describe_multi_factor(contract)


def _to_sel(d: dict):
    try:
        from backend.strategy.portfolio_rebalance import SelectionContract
        return SelectionContract(**d)
    except Exception:
        return d
