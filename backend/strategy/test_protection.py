# -*- coding: utf-8 -*-
"""保护引擎单元测试 — 验证 gap 感知成交价 / 移动止损激活与触发 / intrabar 裁决 / 时间止损。

运行:  python backend/strategy/test_protection.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.protection import ProtectionEngine, ProtectionSpec, ProtectionState  # noqa: E402


def bar(open_, high, low, close=None, date="d"):
    return {"date": date, "open": open_, "high": high, "low": low,
            "close": close if close is not None else high}


def spec(**kw):
    defaults = {"stop_loss_pct": 0.0, "take_profit_pct": 0.0, "trailing_stop_pct": 0.0,
                "trailing_activation_pct": 0.0, "intrabar_mode": "conservative", "time_limit_bars": 0}
    defaults.update(kw)
    return ProtectionSpec(**defaults)


def run():
    res = []
    def chk(label, got, want):
        ok = abs(float(got) - float(want)) < 1e-9
        res.append((label, ok, got, want))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")

    def chk_str(label, got, want):
        ok = str(got) == str(want)
        res.append((label, ok, got, want))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")

    # 1) 止损 gap → 按开盘成交(open 已跌破止损价)
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05))
    d = e.evaluate_bar(s, bar=bar(9.0, 9.0, 8.5), bar_index=1)
    chk("止损gap按开盘价成交", d.price, 9.0)

    # 2) 止损无gap → 按触发价
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05))
    d = e.evaluate_bar(s, bar=bar(9.6, 9.7, 9.4), bar_index=1)
    chk("止损无gap按触发价", d.price, 9.5)

    # 3) 止盈 gap → 按开盘
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(12.3, 12.5, 12.0), bar_index=1)
    chk("止盈gap按开盘价", d.price, 12.3)

    # 4) 止盈无gap → 按触发价
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(11.9, 12.1, 11.8), bar_index=1)
    chk("止盈无gap按触发价", d.price, 12.0)

    # 5) 移动止损: bar1 创新高11.2(>=11.0激活阈), bar2 回到10.5 触发10.64
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(trailing_stop_pct=0.05, trailing_activation_pct=0.10))
    e.evaluate_bar(s, bar=bar(10.5, 11.2, 10.4), bar_index=1)   # 无决定, high->11.2
    d = e.evaluate_bar(s, bar=bar(11.0, 11.3, 10.5), bar_index=2)
    chk("移动止损激活后按触发价", d.price, 11.2 * 0.95)

    # 6) intrabar 同bar止损+止盈同时触发 → conservative 取止损
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05, take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(10.0, 12.5, 9.0), bar_index=1)
    chk_str("conservative同bar取止损", d.reason, "stop_loss")

    # 7) intrabar 同bar → aggressive 取止盈
    e = ProtectionEngine(intrabar_mode="aggressive")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05, take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(10.0, 12.5, 9.0), bar_index=1)
    chk_str("aggressive同bar取止盈", d.reason, "take_profit")

    # 8) intrabar balanced → 取触发价更接近开盘者
    e = ProtectionEngine(intrabar_mode="balanced")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05, take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(10.0, 12.5, 9.0), bar_index=1)
    # stop trigger 9.5 vs take trigger 12.0, ref=open 10.0 → |9.5-10|=0.5 < |12-10|=2 → stop
    chk_str("balanced同bar取最接近开盘", d.reason, "stop_loss")

    # 9) 时间止损: time_limit_bars=2, bar_index-0>=2 → 按开盘退出
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(time_limit_bars=2))
    d = e.evaluate_bar(s, bar=bar(10.6, 10.8, 10.2), bar_index=2)
    chk("时间止损按开盘退出", d.price, 10.6)

    # 10) 止盈gap(短) vs 止损无gap：只止盈触发 → 不误判
    e = ProtectionEngine(intrabar_mode="conservative")
    s = ProtectionState.open(10.0, 0, spec(stop_loss_pct=0.05, take_profit_pct=0.20))
    d = e.evaluate_bar(s, bar=bar(11.0, 12.1, 10.9), bar_index=1)
    chk_str("只止盈触发(非止损)", d.reason, "take_profit")

    ok = all(x[1] for x in res)
    print(f"\n保护引擎自检: {sum(1 for x in res if x[1])}/{len(res)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
