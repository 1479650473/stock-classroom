# -*- coding: utf-8 -*-
"""AI 操盘手 (Trader Agent) —— 长期自主的 LLM 交易员。

与「策略进化闭环」(backend/strategy/optimize_loop.py, LLM 写策略契约→回测→裁决) 完全分离：
- 策略进化：AI 产出可复现的规则型策略，交给回测验证。
- AI 操盘手：LLM 直接扮演交易员，看自己的账户/持仓/行情/新闻，每天做一次交易决策
  (买/卖/保持)，并写长期记忆。它不产出策略，只做仓位操作。

模块：
  store.py    长期记忆库 data/ai_trader.db (profile / decision / memory)
  account.py  专属「AI操盘手」账户的创建与绑定
  news.py     行情新闻采集 (东财全球财经 + 个股新闻，豆包可选)
  context.py  每日决策上下文 (账户/持仓/净值/市场/候选/新闻/历史记忆)
  tools.py    操盘手工具 (只读查询 + 下单预览 + 决策提交)
  agent.py    TraderAgent: LLM tool-calling 决策循环
  daily.py    run_daily_decision(): 每日一次决策的编排入口
"""
from .store import ensure_schema, get_profile, get_conn  # noqa: F401
from .daily import run_daily_decision  # noqa: F401

__all__ = ["ensure_schema", "get_profile", "get_conn", "run_daily_decision"]
