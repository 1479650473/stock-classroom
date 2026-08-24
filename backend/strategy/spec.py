# -*- coding: utf-8 -*-
"""策略契约 — LLM 生成的声明式 JSON，安全、可版本化、可回测。

字段说明：
- universe: 单标的 {code, name}
- entry/exit: 复用 factor_engine/dsl 的 JSON 条件树（因子 key 见 strategy/factors.py）
- position_sizing: 仓位模式 (percent_of_equity | fixed_qty | fixed_capital)
- risk: 止损/止盈百分比(相对开仓价) + 是否允许做空(A股默认 False)
- params: 策略参数(备用，保留给未来窗口/阈值调优)
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PositionSizing:
    mode: str = "percent_of_equity"   # percent_of_equity | fixed_qty | fixed_capital
    value: float = 0.95               # percent_of_equity: 0~1; fixed_qty: 股数; fixed_capital: 金额


@dataclass
class Risk:
    """风控/保护参数(相对开仓价)。支持移动止损、同bar Intrabar 裁决、时间止损(禁做空 T+1)。"""
    stop_loss_pct: Optional[float] = 0.05      # 止损, 相对开仓价, None=不启用
    take_profit_pct: Optional[float] = 0.12    # 止盈, 相对开仓价, None=不启用
    trailing_stop_pct: Optional[float] = 0.0      # 移动止损幅度(0=禁用)
    trailing_activation_pct: Optional[float] = 0.0  # 盈利达该比例才激活移动止损
    intrabar_mode: str = "conservative"  # conservative|balanced|aggressive(同bar多保护裁决)
    time_limit_bars: int = 0             # 持仓超过 N 根bar 强制退出(0=禁用)
    allow_short: bool = False            # A股散户默认做多, T+1 禁日内


@dataclass
class StrategySpec:
    name: str = "未命名策略"
    description: str = ""
    universe: dict = field(default_factory=lambda: {"code": "", "name": ""})
    entry: Optional[dict] = None               # DSL 条件树(进场)
    exit: Optional[dict] = None                # DSL 条件树(离场, 与止盈止损并行触发)
    position_sizing: PositionSizing = field(default_factory=PositionSizing)
    risk: Risk = field(default_factory=Risk)
    params: dict = field(default_factory=dict)
    created_at: str = ""

    # ── serialization ─────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "universe": self.universe,
            "entry": self.entry,
            "exit": self.exit,
            "position_sizing": {
                "mode": self.position_sizing.mode,
                "value": self.position_sizing.value,
            },
            "risk": {
                "stop_loss_pct": self.risk.stop_loss_pct,
                "take_profit_pct": self.risk.take_profit_pct,
                "trailing_stop_pct": self.risk.trailing_stop_pct,
                "trailing_activation_pct": self.risk.trailing_activation_pct,
                "intrabar_mode": self.risk.intrabar_mode,
                "time_limit_bars": self.risk.time_limit_bars,
                "allow_short": self.risk.allow_short,
            },
            "params": self.params,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategySpec":
        ps = d.get("position_sizing", {}) or {}
        rk = d.get("risk", {}) or {}
        return cls(
            name=d.get("name", "未命名策略"),
            description=d.get("description", ""),
            universe=d.get("universe", {}) or {"code": "", "name": ""},
            entry=d.get("entry"),
            exit=d.get("exit"),
            position_sizing=PositionSizing(ps.get("mode", "percent_of_equity"),
                                           float(ps.get("value", 0.95))),
            risk=Risk(rk.get("stop_loss_pct"), rk.get("take_profit_pct"),
                      rk.get("trailing_stop_pct", 0.0), rk.get("trailing_activation_pct", 0.0),
                      rk.get("intrabar_mode", "conservative"), rk.get("time_limit_bars", 0),
                      bool(rk.get("allow_short", False))),
            params=d.get("params", {}) or {},
            created_at=d.get("created_at", ""),
        )

    def validate(self) -> None:
        """校验契约基本完整性，缺失必填项时抛 ValueError。"""
        if not self.universe.get("code") and not self.universe.get("selector"):
            raise ValueError("策略契约缺 universe.code 或 universe.selector")
        if self.entry is None and self.exit is None and \
                self.risk.stop_loss_pct is None and self.risk.take_profit_pct is None:
            raise ValueError("策略契约既无 entry/exit 条件，也无止盈止损，无法交易")
        if self.risk.allow_short:
            # 当前回测器仅支持做多(T+1 禁日内回转)；契约层面先拦截
            raise ValueError("A股 T+1 场景暂不支持做空")

    def resolve_universe(self) -> dict:
        """把 universe(单码 或 目录selector) 解析成具体代码列表。
        返回 {'codes':[...], 'name':str, 'selector':bool}。"""
        from .catalog import resolve_universe as _ru
        return _ru(self.universe)

    def __repr__(self):
        return f"<StrategySpec {self.name} code={self.universe.get('code')}>"
