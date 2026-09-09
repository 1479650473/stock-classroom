# -*- coding: utf-8 -*-
"""AI 操盘手专属账户的创建与绑定。

与聊天/手工操作用的「AI账户」分离：操盘手账户只由本模块的每日决策循环下单，
历史干净，决策记忆不会混入手工单。
"""
from __future__ import annotations

from typing import Optional

from ..trade_engine.engine import TradeEngine
from . import store

TRADER_ACCOUNT_NAME = "AI操盘手"

# 不预设人设：风格完全由 AI 在长期决策中自行形成，并写入长期记忆（kind=style）。
DEFAULT_PERSONA = ""

# 仅两条硬约束：① 本金固定（不追加/不提取） ② 严格按 A 股交易规则。
# 不再有持仓只数/现金下限/单日新开仓/单票占比等自由裁量限制。
DEFAULT_RISK_RULES = {
    "capital_fixed": True,
    "note": (
        "本金固定，不追加也不提取；只能在该资金范围内运作。"
        "严格按 A 股规则：T+1（当日买入不可当日卖出）、最小 100 股且为 100 的整数倍、"
        "不可做空、买入扣佣金、卖出扣佣金+印花税、只能用可用资金买入。"
    ),
}

# 旧版本遗留的自由裁量约束，遇到就清除
_LEGACY_RULE_KEYS = ("max_position_pct", "max_positions", "min_cash_pct", "max_new_buys_per_day")
_LEGACY_PERSONA = (
    "你是一位独立管理自有资金的 A 股交易员，风格稳健但不僵化："
    "重视本金安全与回撤控制，愿意在逻辑成立时让利润奔跑；"
    "不追涨杀跌，不频繁交易，没有机会时宁可空仓等待。"
)


def normalize_profile(prof: dict) -> dict:
    """把旧版固定人设/自由裁量约束清掉，只保留本金固定 + A 股规则。"""
    if prof is None:
        return prof
    fields = {}
    if (prof.get("persona") or "").strip() == _LEGACY_PERSONA:
        fields["persona"] = ""
    rules = dict(prof.get("risk_rules") or {})
    if any(k in rules for k in _LEGACY_RULE_KEYS) or not rules.get("capital_fixed"):
        for k in _LEGACY_RULE_KEYS:
            rules.pop(k, None)
        rules["capital_fixed"] = True
        rules["note"] = DEFAULT_RISK_RULES["note"]
        fields["risk_rules"] = rules
    if fields:
        prof = store.update_profile(int(prof["id"]), **fields) or prof
    return prof


def ensure_account(initial_capital: float = 100000.0) -> int:
    """返回「AI操盘手」账户 id；不存在则创建。"""
    engine = TradeEngine()
    for a in engine.list_accounts():
        if a["name"] == TRADER_ACCOUNT_NAME:
            return int(a["id"])
    return int(engine.create_account(TRADER_ACCOUNT_NAME, initial_capital))


def trader_engine() -> TradeEngine:
    """操盘手专用引擎：解除项目级单票 30% 限制，只受可用资金/A 股规则约束。"""
    engine = TradeEngine()
    engine.POSITION_LIMIT = 1.0
    return engine


def ensure_profile(initial_capital: float = 100000.0,
                   persona: Optional[str] = None) -> dict:
    """返回操盘手档案；不存在则创建账户 + 档案。"""
    store.ensure_schema()
    prof = store.get_profile()
    if prof is not None:
        # 校验绑定账户仍存在，否则重新绑定
        engine = TradeEngine()
        if engine.get_account(int(prof["account_id"])) is not None:
            return normalize_profile(prof)
        aid = ensure_account(initial_capital)
        return store.update_profile(prof["id"], account_id=aid, initial_capital=initial_capital)
    aid = ensure_account(initial_capital)
    return store.create_profile(
        account_id=aid, name=TRADER_ACCOUNT_NAME, initial_capital=initial_capital,
        persona=persona or DEFAULT_PERSONA, risk_rules=DEFAULT_RISK_RULES)
