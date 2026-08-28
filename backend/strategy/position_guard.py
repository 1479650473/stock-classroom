# -*- coding: utf-8 -*-
"""position_guard.py — 每日持仓守护: 用卖出规约对模拟账户持仓逐日判定卖出.

目的: 补齐自动策略闭环里"独立于排名的风险卖出" —— 买后暴跌→止损, 涨到位→止盈,
      持有超期→时间止损; 没触发→继续持有到重平衡日(再按排名调出).

与 portfolio_paper(重平衡调仓) 分工:
  · portfolio_paper: 重平衡日"掉出 top_k% 调出"(周期轮动, 排名兜底)
  · position_guard:  每日"保护触发立即卖出"(硬风控, 优先于排名)
  · 两者共用 sell_rules.SellRuleSet(单一事实来源), 保证优先/参数一致

用法 (每日收盘后):
  guard = PositionGuard(rule_set)
  for pos in engine.get_positions(account_id):
      bar = 读该股当日K线(open/high/low)
      state = 重建/维护持仓保护状态(entry_price, entry_index, highest, lowest)
      decision = guard.evaluate(state, bar, bar_index)
      if decision: 卖出(code, reason=REASON_CN[decision.reason])
      否则: 更新 state 的 highest/lowest(供移动止损), 继续持有

隔离: 只作用于模拟账户持仓, 不改策略契约/因子权重.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.strategy.protection import ProtectionEngine, ProtectionState, ProtectionDecision
from backend.strategy.sell_rules import SellRuleSet, reason_cn


@dataclass
class GuardSignal:
    """一份持仓的卖出守护信号."""
    code: str
    name: str = ""
    reason: str = ""          # stop_loss/take_profit/trailing_stop/time_limit/rebalance_exit
    reason_cn: str = ""       # 中文
    trigger_price: float = 0.0
    exec_price: float = 0.0   # gap时=开盘
    bar_index: int = 0

    def __repr__(self):
        return f"<GuardSignal {self.code} {self.reason_cn} @{self.exec_price:.2f}>"


class PositionGuard:
    """持仓守护器: 持一份卖出规则集, 对单只持仓做逐日保护判定."""

    def __init__(self, rule_set: Optional[SellRuleSet] = None):
        self.rules = rule_set or SellRuleSet.build()
        self._engine = ProtectionEngine(intrabar_mode="conservative")

    def evaluate(self, state: ProtectionState, bar: dict, bar_index: int) -> Optional[GuardSignal]:
        """对单个持仓用当日 bar 判定保护卖出. 触发返回 GuardSignal, 否则 None.

        bar: {open, high, low, close(可省), ...}; bar_index: 从建仓日起计(0=建仓bar).
        与 ProtectionEngine 语义一致: gap 越过触发价→按开盘成交, 否则按触发价; 保守裁决.
        """
        decision = self._engine.evaluate_bar(state, bar=bar, bar_index=bar_index)
        if decision is None:
            return None
        return GuardSignal(
            code=state.code if hasattr(state, "code") else "",
            reason=decision.reason, reason_cn=reason_cn(decision.reason),
            trigger_price=decision.trigger_price, exec_price=decision.price,
            bar_index=decision.bar_index,
        )

    def new_state(self, code: str, entry_price: float, entry_index: int = 0,
                  side: str = "long") -> ProtectionState:
        """为新开仓建一个保护状态."""
        st = ProtectionState.open(entry_price, entry_index, self.rules.protection, side=side)
        st.code = code   # 附加 code 供信号引用
        return st


if __name__ == "__main__":
    # 冒烟: 买后连续下跌触发止损
    rs = SellRuleSet.build(rebalance_bars=20, stop_loss_pct=0.05)
    g = PositionGuard(rs)
    st = g.new_state("600000", entry_price=10.0, entry_index=0)
    # 建仓后第 3 根 bar 跌 7%
    bar = {"open": 9.9, "high": 9.95, "low": 9.30, "close": 9.35}
    sig = g.evaluate(st, bar, bar_index=3)
    print("触发信号:", sig)
    if sig:
        print(f"  原因={sig.reason_cn} 触发价={sig.trigger_price:.2f} 成交价={sig.exec_price:.2f}")
    else:
        print("  未触发(跌破5%应触发止损), 检查")
    # 未触发时 state 更新最高/最低价
    st2 = g.new_state("600001", entry_price=10.0)
    sig2 = g.evaluate(st2, {"open": 10.1, "high": 10.3, "low": 9.95, "close": 10.2}, bar_index=1)
    print("小幅波动:", sig2, "| state 已更新 highest=", round(st2.highest_price, 2), "lowest=", round(st2.lowest_price, 2))
