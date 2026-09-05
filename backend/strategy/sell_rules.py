# -*- coding: utf-8 -*-
"""sell_rules.py — 自动策略持仓的卖出条件规约 (单一事实来源).

背景: 你的质疑"卖出条件没确定" —— 原组合重平衡(portfolio_paper)只有"按排名调出",
      没有独立于排名的风险卖出(止损/止盈/时间止损), 导致买后暴跌可能死扛到下一次重平衡.

本模块统一定义"什么条件下卖" + 优先级, 供:
  · portfolio_paper / 每日持有期检查 (A2): 对模拟账户持仓逐日判定卖出
  · verify_full_lifecycle (B): 完整生命周期验证复用同一套卖出规则(保证可复现)
  · 前端展示 (A3): 交易页/持仓页显示每只票的卖出条件与状态

优先级 (用户确认): **个股保护(硬规则) > 重平衡调出(排名兜底)**.
  日内某票同时触发多个卖出信号时:
    ① 止损/止盈/时间止损 优先(硬风控, 立即止损/锁盈/了结)
    ② 重平衡日"掉出 top_k%"才调出(正常周期轮动, 排在保护之后)
  即: 买了暴跌→止损立即卖; 涨到目标→止盈锁盈; 持有超期→时间止损; 正常票→按周期轮动调出.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from backend.strategy.protection import ProtectionSpec   # 复用成熟保护引擎的参数载体

# 默认保护参数 —— 与 build() 默认值完全一致(三驱动: 8%止损 + 移动止损10%/15%激活 + 无止盈)
# 唯一事实来源: 直接构造 SellRuleSet() 与 SellRuleSet.build() 语义相同, 杜绝双默认值漂移.
DEFAULT_PROTECTION = dict(
    stop_loss_pct=0.08,          # 条件止损 8% (兜底防大亏)
    take_profit_pct=0.0,         # 无固定止盈(让利润奔跑)
    trailing_stop_pct=0.10,      # 移动止损 10% 回撤
    trailing_activation_pct=0.15,  # +15% 激活
    time_limit_bars=0,           # 时间止损: 0=不设(与重平衡周期同长会致 rebalance_exit 永不触发)
)


@dataclass
class SellRuleSet:
    """一份卖出规则集: 个股保护 + 重平衡调出 + 优先级."""
    protection: ProtectionSpec = field(default_factory=lambda: ProtectionSpec(**DEFAULT_PROTECTION))
    # 重平衡调出: 综合分掉出 top_k_pct 后调出(排名兜底)
    enable_rebalance_exit: bool = True
    # 时间止损默认绑定持有期: 0 表示用 rebalance_bars
    time_limit_bars: int = 0

    @classmethod
    def build(cls, rebalance_bars: int = 20, top_k_pct: float = 0.2,
              stop_loss_pct: float = 0.08, take_profit_pct: float = 0.0,
              trailing_stop_pct: float = 0.10, trailing_activation_pct: float = 0.15,
              enable_rebalance_exit: bool = True) -> "SellRuleSet":
        """按策略参数构造一份卖出规则集. 时间止损缺省 = 持有期(重平衡周期).

        用户策略哲学: **不加固定止盈(让利润奔跑)**, 用三驱动:
          · 条件止损(stop_loss): 兜底防大亏(跌破止损即走)
          · 移动止损(trailing): 利润奔跑后锁利(创新高则止损线随之上移, 回撤触发即走)
          · 策略卖出/重平衡调出(rebalance_exit): 信号/排名失效才兑现
        take_profit_pct 默认 0(不设固定止盈); trailing 默认 10%回撤/15%激活.
        time_limit_bars 默认 0(不设时间止损): 用户策略坚持"条件止损+策略卖出"双驱动,
        时间止损会与重平衡周期同长导致每期持仓被提前清掉(实测 rebalance_exit 永远不触发).
        """
        tl = 0
        prot = ProtectionSpec(
            stop_loss_pct=float(stop_loss_pct),
            take_profit_pct=float(take_profit_pct),
            trailing_stop_pct=float(trailing_stop_pct),
            trailing_activation_pct=float(trailing_activation_pct),
            intrabar_mode="conservative",
            time_limit_bars=tl,
        )
        return cls(protection=prot, enable_rebalance_exit=enable_rebalance_exit, time_limit_bars=tl)


# 卖出原因 → 中文/权重(供前端展示 & 比较)
REASON_CN = {
    "stop_loss": "止损", "take_profit": "止盈", "trailing_stop": "移动止损",
    "time_limit": "时间止损", "rebalance_exit": "重平衡调出", "manual": "手动",
}
# 优先级: 数值越小越先卖
PRIORITY = {"stop_loss": 0, "trailing_stop": 1, "take_profit": 2, "time_limit": 3, "rebalance_exit": 4}


def rank_sell_reasons(reasons: list) -> list:
    """一组卖出原因按优先级排序(小→大), 同优先级保序."""
    return sorted(reasons, key=lambda r: PRIORITY.get(r, 99))


def reason_cn(reason: str) -> str:
    return REASON_CN.get(reason, reason)


if __name__ == "__main__":
    # 冒烟: 看一份默认卖出规则集
    rs = SellRuleSet.build(rebalance_bars=20)
    print("默认卖出规则集:")
    print(f"  止损 {rs.protection.stop_loss_pct:.0%} / 止盈 {rs.protection.take_profit_pct:.0%} / "
          f"时间止损 {rs.protection.time_limit_bars}根K线")
    print(f"  重平衡调出: {rs.enable_rebalance_exit}")
    print("  优先级顺序:", " > ".join(reason_cn(r) for r in rank_sell_reasons(['rebalance_exit','stop_loss','take_profit','time_limit'])))
