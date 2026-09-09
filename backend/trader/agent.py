# -*- coding: utf-8 -*-
"""TraderAgent —— LLM 以工具调用方式扮演操盘手，产出当日决策。

流程：注入上下文(账户/持仓/市场/候选/新闻/历史记忆) → LLM 自主决定是否再查工具
(看个股新闻/价格/候选/大盘) → 调用 submit_decision 提交思考 + 多笔委托 + 复盘。
执行由 daily.py 统一完成（校验 + 下单 + 落记忆）。

与策略进化闭环的区别：这里 LLM 不写策略、不跑回测，它直接像人一样操作账户。
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from ..agent.llm_client import LLMClient, LLMError
from .tools import TOOL_SPECS, TraderTools

MAX_ROUNDS = 8

SYSTEM = (
    "你是一名独立管理自有资金的 A 股交易员（操盘手），今天要为自己的账户做一次决策。\n"
    "\n"
    "【硬性约束（仅此两类，必须严格遵守）】\n"
    "1. 本金固定：账户初始资金固定，不追加、不提取；你只能在这个资金范围内运作。\n"
    "2. A 股交易规则：T+1（当日买入不可当日卖出）；最小 100 股且必须是 100 的整数倍；"
    "不可做空；买入扣佣金、卖出扣佣金+印花税；只能用可用资金买入。"
    "任何违规委托都会被拒绝，下单前用 preview_order 校验。\n"
    "\n"
    "【风格完全由你自己决定】\n"
    "没有人给你设定交易风格、持仓数量、仓位上限或买卖纪律。你可以自由选择价值/趋势/事件/"
    "量化/择时/集中/分散……任何路径，并在长期实践中形成、检验、修正你自己的风格。\n"
    "你是一个长期存在的交易员：过去每一天的决策、持仓逻辑、复盘与你自己写下的自我认知，"
    "都会作为记忆给你；请把它们当作真实的经验，而不是一次性任务。\n"
    "\n"
    "【工作方式】\n"
    "1. 先通读已给你的账户、持仓、净值、市场环境、候选池、新闻与历史记忆。\n"
    "2. 需要更多信息就主动调用工具：查个股新闻、查价格、看候选、看大盘，不要凭空臆测。\n"
    "3. 下单前用 preview_order 校验资金/可卖数量/T+1，避免无效委托。\n"
    "4. 若上下文里有长期未成交的委托，可用 cancel_order 撤销以释放冻结资金。\n"
    "5. 买入时调用 remember(kind='thesis', code=..., content=买入逻辑)，记录该持仓的长期逻辑。\n"
    "6. 当你对自己的风格、偏好或方法论有新认识时，调用 remember(kind='style', content=...)，"
    "它会在后续决策中作为「你的自我认知」回给你；可以随时修正。\n"
    "7. 最后必须调用 submit_decision 提交：thinking(今日完整分析)、orders(可为多笔，空=不操作)、"
    "reflection(对上一交易日的复盘与经验)。\n"
    "\n"
    "全部用中文，数字用工具/上下文里的真实值。"
)


def _fmt_context(ctx: dict) -> str:
    """把上下文压成紧凑 JSON 文本（避免超长，截断长列表）。"""
    compact = {
        "日期": ctx.get("generated_at"),
        "账户": ctx.get("account"),
        "持仓": ctx.get("positions"),
        "待成交委托": ctx.get("pending_orders"),
        "最近净值": ctx.get("nav_history"),
        "市场": ctx.get("market"),
        "候选_多因子": (ctx.get("candidates") or {}).get("picks"),
        "候选_事件": (ctx.get("candidates") or {}).get("events"),
        "热点板块": (ctx.get("candidates") or {}).get("hot_sectors"),
        "市场快讯": (ctx.get("news") or {}).get("market"),
        "个股新闻": (ctx.get("news") or {}).get("stocks"),
        "你的自我风格": (ctx.get("memory") or {}).get("self_style"),
        "历史决策": (ctx.get("memory") or {}).get("recent_decisions"),
        "持仓逻辑": (ctx.get("memory") or {}).get("holding_theses"),
        "长期记忆": (ctx.get("memory") or {}).get("notes"),
    }
    return json.dumps(compact, ensure_ascii=False, default=str)


class TraderAgent:
    def __init__(self, account_id: int, profile_id: int, risk_rules: Optional[dict] = None,
                 llm: Optional[LLMClient] = None):
        self.tools = TraderTools(account_id, profile_id, risk_rules)
        self._llm = llm

    def _client(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    def decide(self, ctx: dict, progress: Optional[Callable] = None) -> dict:
        """跑一轮决策，返回 {thinking, orders, reflection, notes, trace, error?}。"""
        def emit(m):
            if progress:
                try:
                    progress(m)
                except Exception:
                    pass

        try:
            llm = self._client()
        except LLMError as e:
            return {"thinking": "", "orders": [], "reflection": "", "notes": [],
                    "trace": [], "error": f"LLM 未配置: {e}"}

        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "今日决策上下文（JSON）：\n" + _fmt_context(ctx)},
        ]
        emit("操盘手开始分析今日数据…")

        for rnd in range(1, MAX_ROUNDS + 1):
            try:
                result = llm.chat_with_tools(messages, TOOL_SPECS, max_tokens=2600)
            except Exception as e:
                return {"thinking": "", "orders": [], "reflection": "", "notes": [],
                        "trace": self.tools.log, "error": f"LLM 调用失败: {str(e)[:200]}"}

            tcs = result.get("tool_calls")
            if tcs:
                messages.append({"role": "assistant", "content": result.get("content") or "",
                                 "tool_calls": tcs})
                for tc in tcs:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except Exception:
                        args = {}
                    emit(_tool_msg(name, args))
                    res = self.tools.execute(name, args)
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(res, ensure_ascii=False, default=str)})
                if self.tools.decision is not None:
                    break
            else:
                text = (result.get("content") or "").strip()
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                                 "请现在调用 submit_decision 提交今日最终决策（含 thinking 与 orders）。"})
                emit("提示操盘手提交决策…")

        if self.tools.decision is None:
            # 强制最终提交
            emit("强制操盘手给出最终决策…")
            try:
                llm = self._client()
                spec = [t for t in TOOL_SPECS
                        if t["function"]["name"] == "submit_decision"]
                result = llm.chat_with_tools(
                    messages, spec, max_tokens=2000,
                    tool_choice={"type": "function",
                                 "function": {"name": "submit_decision"}})
                for tc in result.get("tool_calls") or []:
                    try:
                        self.tools.decision = json.loads(tc["function"]["arguments"] or "{}")
                    except Exception:
                        pass
            except Exception as e:
                emit(f"最终决策失败: {str(e)[:120]}")

        if self.tools.decision is None:
            return {"thinking": "", "orders": [], "reflection": "", "notes": self.tools.notes,
                    "trace": self.tools.log, "error": "操盘手未能给出决策"}

        d = self.tools.decision
        return {
            "thinking": d.get("thinking") or "",
            "orders": d.get("orders") or [],
            "reflection": d.get("reflection") or "",
            "notes": self.tools.notes,
            "trace": self.tools.log,
        }


_LABELS = {
    "get_account_summary": "查看账户",
    "get_positions": "查看持仓",
    "get_stock_price": "查询价格",
    "search_stock": "搜索股票",
    "get_market_news": "读取市场快讯",
    "get_stock_news": "读取个股新闻",
    "get_regime": "判断市场环境",
    "get_candidates": "查看候选股",
    "preview_order": "校验委托",
    "cancel_order": "撤销委托",
    "remember": "记录长期记忆",
    "submit_decision": "提交决策",
}


def _tool_msg(name: str, args: dict) -> str:
    label = _LABELS.get(name, name)
    if name in ("get_stock_price", "get_stock_news", "search_stock") and args.get("code"):
        return f"{label} → {args.get('code')}"
    if name == "submit_decision":
        n = len(args.get("orders") or [])
        return f"{label} → {'保持现状' if n == 0 else f'{n} 笔委托'}"
    return label
