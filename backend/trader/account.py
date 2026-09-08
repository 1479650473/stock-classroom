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

DEFAULT_PERSONA = (
    "你是一位独立管理自有资金的 A 股交易员，风格稳健但不僵化："
    "重视本金安全与回撤控制，愿意在逻辑成立时让利润奔跑；"
    "不追涨杀跌，不频繁交易，没有机会时宁可空仓等待。"
)

DEFAULT_RISK_RULES = {
    "max_position_pct": 30,      # 单票上限（与引擎 POSITION_LIMIT 一致）
    "max_positions": 8,          # 最多同时持有只数
    "min_cash_pct": 5,           # 保留现金比例下限
    "max_new_buys_per_day": 2,   # 单日最多新开仓
    "note": "T+1 不可当日卖出；最小 100 股；不融资融券、不做空。",
}


def ensure_account(initial_capital: float = 100000.0) -> int:
    """返回「AI操盘手」账户 id；不存在则创建。"""
    engine = TradeEngine()
    for a in engine.list_accounts():
        if a["name"] == TRADER_ACCOUNT_NAME:
            return int(a["id"])
    return int(engine.create_account(TRADER_ACCOUNT_NAME, initial_capital))


def ensure_profile(initial_capital: float = 100000.0,
                   persona: Optional[str] = None) -> dict:
    """返回操盘手档案；不存在则创建账户 + 档案。"""
    store.ensure_schema()
    prof = store.get_profile()
    if prof is not None:
        # 校验绑定账户仍存在，否则重新绑定
        engine = TradeEngine()
        if engine.get_account(int(prof["account_id"])) is not None:
            return prof
        aid = ensure_account(initial_capital)
        return store.update_profile(prof["id"], account_id=aid, initial_capital=initial_capital)
    aid = ensure_account(initial_capital)
    return store.create_profile(
        account_id=aid, name=TRADER_ACCOUNT_NAME, initial_capital=initial_capital,
        persona=persona or DEFAULT_PERSONA, risk_rules=DEFAULT_RISK_RULES)
