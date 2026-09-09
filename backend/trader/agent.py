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

MAX_ROUNDS = 10

SYSTEM = (
    "你是一名独立管理自有资金的 A 股交易员（操盘手），今天要为自己的账户做一次决策。\n"
    "\n"
    "你通过下面的工具操作自己的账户，就像用券商软件炒股一样：查账户、看持仓、查行情与新闻、"
    "下单、撤单。所有委托都由交易系统（模拟券商）真实执行：不符合规则或超出可用资金的委托"
    "会被系统直接拒绝并返回原因，你按返回信息调整即可。\n"
    "\n"
    "风格完全由你自己决定：没有人给你设定交易风格、持仓数量、仓位上限或买卖纪律。你可以自由选择"
    "价值/趋势/事件/量化/择时/集中/分散……任何路径，并在长期实践中形成、检验、修正你自己的风格。\n"
    "你是一个长期存在的交易员：过去每一天的决策、持仓逻辑、复盘与你自己写下的自我认知，"
    "都会作为记忆给你；请把它们当作真实的经验，而不是一次性任务。\n"
    "\n"
    "【工作方式】\n"
    "1. 先通读已给你的账户、持仓、待成交委托、净值、市场环境、候选池、新闻与历史记忆。\n"
    "2. 需要更多信息就主动调用工具：查个股新闻、查价格、看候选、看大盘，不要凭空臆测。\n"
    "3. 要买卖就直接调用 place_order（可多次，支持多笔委托）；下单前可用 preview_order 预检。\n"
    "4. 未成交的限价单会冻结资金，可用 cancel_order 撤销。\n"
    "5. 买入的 reason 会被系统记为该持仓的长期逻辑，请写清理由。\n"
    "6. 当你对自己的风格、偏好或方法论有新认识时，调用 remember(kind='style', content=...)，"
    "它会在后续决策中作为「你的自我认知」回给你；可以随时修正。\n"
    "7. 最后调用 submit_decision 提交 thinking 与 reflection，结束今日决策（不操作时也要调用）。\n"
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
                 llm: Optional[LLMClient] = None, decision_id: Optional[int] = None,
                 dry_run: bool = False, model: Optional[str] = None,
                 trade_date: Optional[str] = None, price_fn=None):
        self.tools = TraderTools(account_id, profile_id, risk_rules,
                                 decision_id=decision_id, dry_run=dry_run,
                                 trade_date=trade_date, price_fn=price_fn)
        self._llm = llm
        self._model = model or None

    def _client(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(model=self._model)
        return self._llm

    def decide(self, ctx: dict, progress: Optional[Callable] = None,
               on_event: Optional[Callable] = None) -> dict:
        """跑一轮决策。on_event 非空时用流式，实时回调：
        {event:'agent_text',delta} / {event:'tool_call',name,args} /
        {event:'tool_result',name,ok,summary}。"""
        def emit(m):
            if progress:
                try:
                    progress(m)
                except Exception:
                    pass

        def event(payload: dict):
            if on_event:
                try:
                    on_event(payload)
                except Exception:
                    pass

        try:
            llm = self._client()
        except LLMError as e:
            return {"thinking": "", "reflection": "", "notes": [],
                    "trace": [], "error": f"LLM 未配置: {e}"}

        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "今日决策上下文（JSON）：\n" + _fmt_context(ctx)},
        ]
        emit("操盘手开始分析今日数据…")

        for rnd in range(1, MAX_ROUNDS + 1):
            if on_event is not None:
                text, tcs = "", None
                try:
                    for ev in llm.chat_with_tools_stream(messages, TOOL_SPECS, max_tokens=2600):
                        t = ev.get("type")
                        if t == "text":
                            event({"event": "agent_text", "delta": ev.get("delta") or ""})
                        elif t == "tool_calls":
                            tcs = ev.get("tool_calls")
                        elif t == "content":
                            text = ev.get("content") or ""
                except Exception as e:
                    return {"thinking": "", "reflection": "", "notes": [],
                            "trace": self.tools.log, "error": f"LLM 调用失败: {str(e)[:200]}"}
                result = {"tool_calls": tcs} if tcs else {"content": text}
            else:
                try:
                    result = llm.chat_with_tools(messages, TOOL_SPECS, max_tokens=2600)
                except Exception as e:
                    return {"thinking": "", "reflection": "", "notes": [],
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
                    event({"event": "tool_call", "name": name, "args": args})
                    res = self.tools.execute(name, args)
                    event({"event": "tool_result", "name": name,
                           "ok": "error" not in res, "summary": _summarize_result(name, res)})
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(res, ensure_ascii=False, default=str)})
                if self.tools.decision is not None:
                    break
            else:
                text = (result.get("content") or "").strip()
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                                 "请现在调用 submit_decision 提交今日最终决策（含 thinking）。"})
                emit("提示操盘手提交决策…")

        if self.tools.decision is None:
            # 强制结束（无 LLM 回复时也要留下记录），失败重试一次
            emit("强制操盘手给出最终决策…")
            spec = [t for t in TOOL_SPECS if t["function"]["name"] == "submit_decision"]
            for _try in range(2):
                try:
                    llm = self._client()
                    result = llm.chat_with_tools(
                        messages, spec, max_tokens=2000,
                        tool_choice={"type": "function",
                                     "function": {"name": "submit_decision"}})
                    for tc in result.get("tool_calls") or []:
                        try:
                            self.tools.decision = json.loads(tc["function"]["arguments"] or "{}")
                        except Exception:
                            pass
                    if self.tools.decision is not None:
                        break
                except Exception as e:
                    emit(f"最终决策失败({_try + 1}/2): {str(e)[:120]}")

        if self.tools.decision is None:
            return {"thinking": "", "reflection": "", "notes": self.tools.notes,
                    "trace": self.tools.log, "error": "操盘手未能给出决策"}

        d = self.tools.decision
        event({"event": "decision", "thinking": d.get("thinking") or "",
               "reflection": d.get("reflection") or ""})
        return {
            "thinking": d.get("thinking") or "",
            "reflection": d.get("reflection") or "",
            "notes": self.tools.notes,
            "trace": self.tools.log,
        }


def _summarize_result(name: str, res) -> str:
    """把工具结果压成一行，用于 SSE 流展示。"""
    if not isinstance(res, dict):
        return str(res)[:120]
    if "error" in res:
        return str(res["error"])[:120]
    if name == "get_account_summary":
        return f"总资产 {res.get('总资产')} · 可用 {res.get('可用资金')} · 持仓 {res.get('持仓数')}"
    if name == "get_positions":
        return f"{len(res)} 只持仓" if isinstance(res, list) else str(res)[:80]
    if name == "get_stock_price":
        return f"{res.get('代码')} {res.get('现价')}"
    if name == "get_candidates":
        return f"候选 {len(res.get('picks') or [])} 只"
    if name in ("get_market_news", "get_stock_news"):
        if isinstance(res, list):
            return f"{len(res)} 条"
        return str(res.get("note") or res.get("message") or "无")[:80]
    if name == "preview_order":
        return str(res.get("原因") or res.get("可执行"))
    if name == "place_order":
        return str(res.get("状态") or res.get("error"))[:80]
    if name == "cancel_order":
        return str(res.get("状态") or res.get("error"))[:80]
    if name == "remember":
        return "已记录"
    if name == "submit_decision":
        return "已提交"
    return str(res)[:100]


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
    "place_order": "下单",
    "cancel_order": "撤销委托",
    "remember": "记录长期记忆",
    "submit_decision": "提交决策",
}


def _tool_msg(name: str, args: dict) -> str:
    label = _LABELS.get(name, name)
    if name in ("get_stock_price", "get_stock_news", "search_stock") and args.get("code"):
        return f"{label} → {args.get('code')}"
    if name == "place_order":
        side = "买入" if args.get("side") == "buy" else "卖出"
        return f"{label} → {side} {args.get('code')} {args.get('qty')}"
    if name == "submit_decision":
        return label
    return label
