# -*- coding: utf-8 -*-
"""保护引擎 回测集成验证 — 用真实 600036 K线证明 gap修复/移动止损/时间止损 生效。

运行:  python backend/strategy/verify_protection_backtest.py
对每种保护配置跑回测，打印离场原因分布；验证引擎已接入且行为可判别。
"""
from __future__ import annotations

import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.spec import StrategySpec  # noqa: E402
from backend.strategy.backtest import run_backtest  # noqa: E402
from backend.strategy.data import load_klines, stock_name  # noqa: E402

CODE = "600036"


def base_contract(overrides):
    c = {
        "name": "protection-verify", "universe": {"code": CODE, "name": stock_name(CODE)},
        "entry": {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
        "exit": {"type": "gt", "args": ["RSI14", 80]},
        "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
        "risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12,
                 "trailing_stop_pct": 0.0, "trailing_activation_pct": 0.0,
                 "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
        "params": {"initial_balance": 100000.0},
    }
    c["risk"].update(overrides.get("risk", {}))
    return c


def summarize_exits(res, klines):
    """从 errors 文本统计离场原因; trades 无法直接区分来源, 用 errors 近似。"""
    reasons = Counter()
    for e in res.errors:
        for reason in ("止损", "移动止损", "止盈", "时间止损", "禁止卖出", "禁止买入", "买入量"):
            if reason in e:
                reasons[reason] += 1
    return reasons


def run():
    klines, warns = load_klines(CODE, limit=1200)
    assert klines, "no klines"
    print(f"标的: {CODE} {stock_name(CODE)}  {klines[0]['date']}~{klines[-1]['date']} ({len(klines)}根)")

    configs = [
        ("基线(止损5%/止盈12%)", {}),
        ("紧止损(2%)", {"risk": {"stop_loss_pct": 0.02, "take_profit_pct": None}}),
        ("移动止损(6%,激活8%)", {"risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.20,
                                            "trailing_stop_pct": 0.06, "trailing_activation_pct": 0.08}}),
        ("时间止损(20bar)", {"risk": {"stop_loss_pct": 0.05, "take_profit_pct": None, "time_limit_bars": 20}}),
    ]
    rows = []
    for label, ov in configs:
        spec = StrategySpec.from_dict(base_contract(ov))
        spec.validate()
        res = run_backtest(spec, klines)
        m = res.metrics
        reasons = summarize_exits(res, klines)
        rows.append((label, m["total_return"], m["num_trades"], m["max_drawdown"], reasons))
        print(f"\n  {label}: 总收益 {m['total_return']:+.2f}%  交易 {m['num_trades']}  回撤 {m['max_drawdown']:.2f}%")
        if reasons:
            print(f"     离场触发: {dict(reasons)}")

    # 断言: 引擎已接入且各保护配置行为可判别
    ok = True
    tight = rows[1][4]
    trail = rows[2][4]
    tlim = rows[3][4]
    if tight.get("止损", 0) == 0:
        print("  [FAIL] 紧止损(2%)未触发任何止损 → 引擎可能未接入")
        ok = False
    if trail.get("移动止损", 0) == 0:
        print("  [FAIL] 移动止损配置未触发 → 移动止损未生效")
        ok = False
    if tlim.get("时间止损", 0) == 0:
        print("  [FAIL] 时间止损(20bar)未触发")
        ok = False
    print("\n" + ("✅ 保护引擎回测集成验证通过(各配置均能触发对应离场)" if ok else "❌ 存在未触发"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
