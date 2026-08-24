# -*- coding: utf-8 -*-
"""保护引擎 — 移植自 QuantDinger 的 strategy_v2/protection.py，裁剪为日线单标的。

对每个持仓按确定性规则判断是否触发 止损/移动止损/止盈/时间止损，并给出**成交价**。
回测与实盘共用同一判定器，保证语义一致。

关键设计：
- 触发价 vs 成交价：若 bar 开盘已跳空越过触发价(gap) → **按开盘成交**(更真实，避免虚高/虚低)，
  否则按触发价成交。
- intrabar_mode 裁决同根 bar 内多个保护同时触发：
    conservative(默认)  stop_loss > trailing > time_limit > take_profit  (假设最坏)
    aggressive          take_profit > trailing > time_limit > stop_loss  (假设最好)
    balanced            取触发价最接近开盘者
- 移动止损: 盈利达 trailing_activation_pct 才启用；触发价 = 持仓期最高价 × (1 - trailing_stop_pct)。
- 时间止损: 持仓时间 >= time_limit_bars 强制按开盘退出。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

VALID_MODES = {"conservative", "balanced", "aggressive"}
_DEVICE = "backtest"


@dataclass(frozen=True)
class ProtectionSpec:
    """从 StrategySpec.risk 提取的保护参数。"""
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 0.0
    intrabar_mode: str = "conservative"
    time_limit_bars: int = 0

    @classmethod
    def from_risk(cls, risk) -> "ProtectionSpec":
        return cls(
            stop_loss_pct=float(risk.stop_loss_pct or 0.0),
            take_profit_pct=float(risk.take_profit_pct or 0.0),
            trailing_stop_pct=float(risk.trailing_stop_pct or 0.0),
            trailing_activation_pct=float(risk.trailing_activation_pct or 0.0),
            intrabar_mode=str(risk.intrabar_mode or "conservative"),
            time_limit_bars=int(risk.time_limit_bars or 0),
        )

    @property
    def enabled(self) -> bool:
        return any((self.stop_loss_pct > 0, self.take_profit_pct > 0,
                    self.trailing_stop_pct > 0, self.time_limit_bars > 0))


@dataclass
class ProtectionState:
    """单个持仓的保护状态(随 bar 演进)。"""
    spec: ProtectionSpec
    side: str = "long"
    entry_price: float = 0.0
    entry_index: int = 0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    trailing_active: bool = False

    @classmethod
    def open(cls, entry_price: float, entry_index: int, spec: ProtectionSpec, side: str = "long") -> "ProtectionState":
        return cls(spec=spec, side=side, entry_price=entry_price, entry_index=entry_index,
                   highest_price=entry_price, lowest_price=entry_price, trailing_active=False)


@dataclass(frozen=True)
class ProtectionDecision:
    reason: str            # stop_loss | trailing_stop | take_profit | time_limit
    price: float           # 成交价(gap 时=开盘)
    trigger_price: float   # 触发价
    bar_index: int = 0


class ProtectionEngine:
    def __init__(self, *, intrabar_mode: str = "conservative"):
        mode = str(intrabar_mode or "conservative").strip().lower()
        self.intrabar_mode = mode if mode in VALID_MODES else "conservative"

    # ── 主入口：给定一个已收盘 bar，返回保护决定(或 None)并更新 state ──
    def evaluate_bar(self, state: ProtectionState, *, bar: dict, bar_index: int) -> Optional[ProtectionDecision]:
        open_ = float(bar["open"])
        high = max(open_, float(bar["high"]))
        low = min(open_, float(bar["low"]))
        cands = self._bar_candidates(state, open_=open_, high=high, low=low, bar_index=bar_index)
        decision = self._choose(cands, open_)
        if decision is None:
            state.highest_price = max(state.highest_price, high)
            state.lowest_price = min(state.lowest_price, low)
        return decision

    # ── 取候选(止损/移动止损/止盈/时间)，gap 感知成交价 ───────────────
    def _bar_candidates(self, state: ProtectionState, *, open_: float, high: float, low: float, bar_index: int) -> list[ProtectionDecision]:
        spec = state.spec
        entry = state.entry_price
        is_long = state.side == "long"
        cands: list[ProtectionDecision] = []

        if spec.stop_loss_pct > 0:
            trigger = entry * (1.0 - spec.stop_loss_pct if is_long else 1.0 + spec.stop_loss_pct)
            touched = low <= trigger if is_long else high >= trigger
            gapped = open_ <= trigger if is_long else open_ >= trigger
            if touched:
                cands.append(ProtectionDecision("stop_loss", open_ if gapped else trigger, trigger, bar_index))

        trailing = self._trailing_trigger(state)
        if trailing is not None:
            touched = low <= trailing if is_long else high >= trailing
            gapped = open_ <= trailing if is_long else open_ >= trailing
            if touched:
                cands.append(ProtectionDecision("trailing_stop", open_ if gapped else trailing, trailing, bar_index))

        if spec.take_profit_pct > 0:
            trigger = entry * (1.0 + spec.take_profit_pct if is_long else 1.0 - spec.take_profit_pct)
            touched = high >= trigger if is_long else low <= trigger
            gapped = open_ >= trigger if is_long else open_ <= trigger
            if touched:
                cands.append(ProtectionDecision("take_profit", open_ if gapped else trigger, trigger, bar_index))

        if spec.time_limit_bars > 0 and (bar_index - state.entry_index) >= spec.time_limit_bars:
            cands.append(ProtectionDecision("time_limit", open_, open_, bar_index))

        return cands

    # ── 移动止损触发价(未启用/未激活返回 None) ─────────────────────────
    def _trailing_trigger(self, state: ProtectionState) -> Optional[float]:
        spec = state.spec
        if spec.trailing_stop_pct <= 0:
            return None
        is_long = state.side == "long"
        if is_long:
            if not state.trailing_active and state.highest_price >= state.entry_price * (1.0 + spec.trailing_activation_pct):
                state.trailing_active = True
            if not state.trailing_active:
                return None
            return state.highest_price * (1.0 - spec.trailing_stop_pct)
        if not state.trailing_active and state.lowest_price <= state.entry_price * (1.0 - spec.trailing_activation_pct):
            state.trailing_active = True
        if not state.trailing_active:
            return None
        return state.lowest_price * (1.0 + spec.trailing_stop_pct)

    # ── intrabar 裁决 ───────────────────────────────────────────────
    def _choose(self, cands: list[ProtectionDecision], reference_price: float) -> Optional[ProtectionDecision]:
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        if self.intrabar_mode == "aggressive":
            priority = {"take_profit": 0, "trailing_stop": 1, "time_limit": 2, "stop_loss": 3}
            return min(cands, key=lambda c: priority.get(c.reason, 9))
        if self.intrabar_mode == "balanced":
            return min(cands, key=lambda c: abs(c.trigger_price - reference_price))
        # conservative(默认): 假设最坏，止损优先
        priority = {"stop_loss": 0, "trailing_stop": 1, "time_limit": 2, "take_profit": 3}
        return min(cands, key=lambda c: priority.get(c.reason, 9))
