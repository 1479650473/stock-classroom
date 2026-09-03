# -*- coding: utf-8 -*-
"""Agent chat blueprint — SSE 流式 tool-calling 循环 (AI 操盘台).

POST /api/agent/chat  body: {messages: [{role, content}...]}
返回 text/event-stream, 每个事件一行 JSON:
  {type:"text", delta: str}                     文本增量
  {type:"tool_call", id, name, args}            LLM 请求执行工具
  {type:"tool_result", id, name, ok, summary}   工具执行完成(摘要)
  {type:"done"} / {type:"error", message}
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from flask import Blueprint, Response, request

from ..envelope import ok, err
from ..paths import PROJECT_DIR
from ...agent import toolkit

bp = Blueprint("agent_chat", __name__, url_prefix="/api/agent")

_SYSTEM = (
    "你是「A股量化教室」的内置 AI 操盘手，可以直接调用软件工具操作软件：查账户持仓、看行情、搜索股票、"
    "下单交易(AI账户模拟盘)、因子研究、单因子回测、组合纸面盘、读取/回测/描述策略、选股、判断市场环境。\n"
    "规则:\n"
    "1. 工具能答的一律用工具，不要编造数据；工具结果失败时如实说明并建议下一步。\n"
    "2. 回测/研究类工具耗时数十秒，属正常，工具返回前不要重复发起。\n"
    "3. 下单前先 get_stock_price / get_account_summary 核实，下单后复述成交结果。\n"
    "4. 用户说「写策略/调策略」时：先 get_strategies 列出现有5家族 → backtest_strategy 或 describe_strategy。"
    " 如需自定义契约，用 backtest_strategy 的 contract 参数(JSON: factors/weights/top_k_pct/rebalance_bars)。\n"
    "5. 用中文回答问题，重要数字用真实返回值，不用占位符。"
)

_MAX_ROUNDS = 6

_SLOW_MSG = {
    "research_value_factors": "因子研究(数十秒)…",
    "run_factor_backtest": "单因子回测(数十秒)…",
    "get_portfolio_paper": "构建组合纸面盘(数十秒)…",
    "get_research_snapshot": "构建研究快照(可能1分钟)…",
    "backtest_strategy": "策略回测(数十秒)…",
    "run_picks": "全市场选股(可能1分钟)…",
}


def _sse(obj: dict) -> str:
    return "data: %s\n\n" % json.dumps(obj, ensure_ascii=False, default=str)


@bp.route("/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True, silent=True) or {}
    client_msgs = body.get("messages") or []
    if not client_msgs:
        return err(400, "missing_messages", "messages required", retriable=False)
    from ...agent.llm_client import LLMClient, LLMError
    try:
        llm = LLMClient()
    except LLMError as e:
        return err(400, "llm_not_configured", str(e), retriable=False)
    except Exception as e:
        return err(500, "llm_init_failed", str(e), retriable=False)

    def generate():
        yield _sse({"type": "hello", "ts": time.time()})
        history = [_m for _m in client_msgs if _m.get("role") in ("user", "assistant")]
        messages: list = [{"role": "system", "content": _SYSTEM}] + history
        started = False
        try:
            for _round in range(_MAX_ROUNDS):
                result = llm.chat_with_tools(messages, toolkit._TOOLS)
                tcs = result.get("tool_calls")
                if not tcs:
                    text = result.get("content", "")
                    if text:
                        started = True
                        for ch in _chunks(text, 24):
                            yield _sse({"type": "text", "delta": ch})
                    break
                # 有工具调用: 先声明, 再执行
                assistant_side = "assistant"
                messages.append({
                    "role": assistant_side,
                    "content": None,
                    "tool_calls": [{"id": tc["id"], "type": "function",
                                    "function": tc["function"]} for tc in tcs],
                })
                for tc in tcs:
                    name = tc["function"]["name"]
                    args_json = tc["function"]["arguments"] or ""
                    try:
                        args = json.loads(args_json) if args_json.strip() else {}
                    except Exception:
                        args = {"_raw": args_json}
                    yield _sse({"type": "tool_call", "id": tc["id"], "name": name,
                                "args": args, "ts": time.time()})
                    slow_hint = _SLOW_MSG.get(name)
                    if slow_hint:
                        yield _sse({"type": "tool_progress", "id": tc["id"],
                                    "name": name, "message": slow_hint})
                    res = toolkit.execute_tool(name, args)
                    summary = _summarize(res)
                    yield _sse({"type": "tool_result", "id": tc["id"], "name": name,
                                "ok": not summary.startswith("[错误]"),
                                "summary": summary, "ts": time.time()})
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": json.dumps(res, ensure_ascii=False, default=str)[:6000],
                    })
            if not started:
                yield _sse({"type": "text", "delta": "本轮处理完成，请继续提问。"})
            yield _sse({"type": "done", "ts": time.time()})
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Content-Type": "text/event-stream"}
    return Response(generate(), mimetype="text/event-stream", headers=headers)


@bp.route("/tools", methods=["GET"])
def list_tools():
    """工具清单(前端展示/调试)."""
    return ok({"tools": [t["function"]["name"] for t in toolkit._TOOLS]})


def _chunks(text: str, n: int):
    for i in range(0, len(text), n):
        yield text[i:i + n]


def _summarize(res) -> str:
    """把工具结果压成一段命中要点的中文摘要(喂界面/上下文)。"""
    if isinstance(res, dict):
        if "error" in res:
            return "[错误] " + str(res["error"])
        if "message" in res and len(res) == 1:
            return str(res["message"])
        parts = []
        for k, v in res.items():
            if isinstance(v, list):
                txt = "、".join(str(x).strip() for x in v[:6] if x not in (None, ""))
                parts.append(f"{k}: {txt}" + ("…" if len(v) > 6 else ""))
            elif isinstance(v, dict):
                inner = "、".join(f"{ik}={iv}" for ik, iv in list(v.items())[:5])
                parts.append(f"{k}: {{{inner}}}")
            else:
                parts.append(f"{k}: {v}")
        return "; ".join(str(p) for p in parts[:8])
    return str(res)


# ------------------------------------------------------------------
# 健康/状态辅助(前端开工检查)
@bp.route("/health", methods=["GET"])
def agent_health():
    try:
        from ...agent.llm_client import get_agent_config
        cfg = get_agent_config()
        return ok({
            "llm_configured": bool(cfg.get("api_key") and cfg.get("api_base")),
            "model": cfg.get("model", ""),
            "tools": len(toolkit._TOOLS),
            "time": datetime.now().isoformat(),
        })
    except Exception as e:
        return ok({"llm_configured": False, "error": str(e), "tools": len(toolkit._TOOLS)})
