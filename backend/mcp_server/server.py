# -*- coding: utf-8 -*-
"""stock-classroom MCP Server —— 把本项目的 Agent Gateway (/api/agent/v1) 暴露成 MCP。

设计参考 QuantDinger 的 mcp_server：**薄封装**，只做协议转换与鉴权转发，
真正的能力、分级（R/W/B/T）、审计、幂等、限流都在服务端网关里。

配置（环境变量）：
    SC_BASE_URL     后端地址，默认 http://127.0.0.1:5000
    SC_AGENT_TOKEN  Agent Token（必需；在「设置 → Agent 网关」或用
                    `python -m backend.agent.smoke_test --issue` 生成）
    SC_TIMEOUT_S    单次请求超时，默认 30

用法（stdio，供 Claude Desktop / Cursor / Proma 等 MCP 客户端拉起）：
    python -m backend.mcp_server.server
自检：
    python -m backend.mcp_server.smoke_test
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

DEFAULT_BASE = "http://127.0.0.1:5000"

#: 工具表：(MCP 工具名, 说明, HTTP 方法, 路径模板, 作用域, 参数定义)
#: 路径里的 {name} 会被参数替换；其余参数作为 query(body) 传给网关。
TOOLS: List[Dict[str, Any]] = [
    # ── 只读（R）──
    {"name": "sc_health", "desc": "后端与网关健康检查", "method": "GET",
     "path": "/api/agent/v1/health", "scope": "R", "params": {}},
    {"name": "sc_regime", "desc": "市场环境（牛/熊/震荡、系统性风险、评分明细）", "method": "GET",
     "path": "/api/agent/v1/macro/regime", "scope": "R", "params": {}},
    {"name": "sc_indicators", "desc": "宏观指标（指数/北向/情绪等）", "method": "GET",
     "path": "/api/agent/v1/macro/indicators", "scope": "R", "params": {}},
    {"name": "sc_market_stats", "desc": "全市场统计（涨跌家数、涨跌停、成交额）", "method": "GET",
     "path": "/api/agent/v1/catalog/stats", "scope": "R", "params": {}},
    {"name": "sc_sectors", "desc": "板块列表与涨跌", "method": "GET",
     "path": "/api/agent/v1/catalog/sectors", "scope": "R",
     "params": {"type": {"type": "string", "description": "industry|concept", "default": "industry"}}},
    {"name": "sc_select", "desc": "多因子选股（候选池与分项得分）", "method": "GET",
     "path": "/api/agent/v1/catalog/select", "scope": "R",
     "params": {"top": {"type": "integer", "description": "返回数量", "default": 20},
                "pool": {"type": "string", "description": "股票池（可选）"}}},
    {"name": "sc_describe", "desc": "个股详情（行情/基本面/所属板块）", "method": "GET",
     "path": "/api/agent/v1/catalog/describe/{code}", "scope": "R",
     "params": {"code": {"type": "string", "description": "6 位股票代码"}}},
    {"name": "sc_search_symbol", "desc": "按名称/代码搜索标的", "method": "GET",
     "path": "/api/agent/v1/catalog/search", "scope": "R",
     "params": {"q": {"type": "string", "description": "关键词"}}},
    {"name": "sc_leader_of", "desc": "板块龙头识别", "method": "GET",
     "path": "/api/agent/v1/catalog/leader-of", "scope": "R",
     "params": {"sector": {"type": "string", "description": "板块名"}}},
    {"name": "sc_factors", "desc": "因子/评分卡口径（有哪些因子、权重、窗口）", "method": "GET",
     "path": "/api/agent/v1/factors", "scope": "R", "params": {}},
    {"name": "sc_klines", "desc": "K 线数据（前复权）", "method": "GET",
     "path": "/api/agent/v1/klines", "scope": "R",
     "params": {"code": {"type": "string", "description": "股票代码"},
                "days": {"type": "integer", "description": "根数", "default": 120}}},
    {"name": "sc_positions", "desc": "模拟账户持仓与净值", "method": "GET",
     "path": "/api/agent/v1/positions", "scope": "R",
     "params": {"account_id": {"type": "integer", "description": "账户 ID（可选）"}}},
    {"name": "sc_strategies", "desc": "策略列表（声明式策略）", "method": "GET",
     "path": "/api/agent/v1/strategies", "scope": "R", "params": {}},
    {"name": "sc_strategy_get", "desc": "策略详情", "method": "GET",
     "path": "/api/agent/v1/strategies/{sid}", "scope": "R",
     "params": {"sid": {"type": "integer", "description": "策略 ID"}}},
    {"name": "sc_watchlist", "desc": "自选清单", "method": "GET",
     "path": "/api/agent/v1/watchlist", "scope": "R", "params": {}},
    {"name": "sc_jobs", "desc": "任务列表（回测/更新/挖掘等长任务）", "method": "GET",
     "path": "/api/agent/v1/jobs", "scope": "R", "params": {}},
    {"name": "sc_job_get", "desc": "任务详情与进度", "method": "GET",
     "path": "/api/agent/v1/jobs/{job_id}", "scope": "R",
     "params": {"job_id": {"type": "string", "description": "任务 ID"}}},

    # ── 写入（W）──
    {"name": "sc_strategy_create", "desc": "新建声明式策略", "method": "POST",
     "path": "/api/agent/v1/strategies", "scope": "W",
     "params": {"name": {"type": "string", "description": "策略名"},
                "spec": {"type": "object", "description": "策略声明（选股/买卖条件）"}}},
    {"name": "sc_strategy_update", "desc": "修改策略", "method": "PATCH",
     "path": "/api/agent/v1/strategies/{sid}", "scope": "W",
     "params": {"sid": {"type": "integer"}, "spec": {"type": "object"}}},
    {"name": "sc_watchlist_add", "desc": "加入自选", "method": "POST",
     "path": "/api/agent/v1/watchlist", "scope": "W",
     "params": {"code": {"type": "string"}}},
    {"name": "sc_watchlist_remove", "desc": "移出自选", "method": "DELETE",
     "path": "/api/agent/v1/watchlist/{code}", "scope": "W",
     "params": {"code": {"type": "string"}}},

    # ── 回测（B）──
    {"name": "sc_backtest_run", "desc": "提交回测任务（返回 job_id，配合 sc_job_get 查询）",
     "method": "POST", "path": "/api/agent/v1/backtest/run", "scope": "B",
     "params": {"strategy_id": {"type": "integer", "description": "策略 ID"},
                "start": {"type": "string", "description": "YYYY-MM-DD"},
                "end": {"type": "string", "description": "YYYY-MM-DD"}}},

    # ── 交易（T，paper-only）──
    {"name": "sc_paper_order", "desc": "模拟下单（paper-only，受限额约束）", "method": "POST",
     "path": "/api/agent/v1/paper/orders", "scope": "T",
     "params": {"code": {"type": "string"}, "side": {"type": "string", "description": "buy|sell"},
                "qty": {"type": "integer"}, "account_id": {"type": "integer"}}},
    {"name": "sc_kill_switch", "desc": "交易急停（撤单并冻结下单）", "method": "POST",
     "path": "/api/agent/v1/paper/kill-switch", "scope": "T", "params": {}},
]


def _base() -> str:
    return os.getenv("SC_BASE_URL", DEFAULT_BASE).rstrip("/")


def _token() -> str:
    return os.getenv("SC_AGENT_TOKEN", "").strip()


def _timeout() -> float:
    try:
        return float(os.getenv("SC_TIMEOUT_S", "30"))
    except ValueError:
        return 30.0


def _call_http(tool: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    path = tool["path"]
    params = dict(args or {})
    for key in list(params):
        if "{" + key + "}" in path:
            path = path.replace("{" + key + "}", str(params.pop(key)))
    url = _base() + path
    headers = {"X-Agent-Token": _token(), "Accept": "application/json"}
    body = None
    method = tool["method"]
    if method in ("POST", "PATCH", "PUT"):
        body = json.dumps(params, ensure_ascii=False).encode()
    elif params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return {"ok": False, "http_status": e.code, "body": raw[:4000]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        return {"ok": True, "data": json.loads(raw)}
    except Exception:
        return {"ok": True, "body": raw[:4000]}


def _tool_schema(t: Dict[str, Any]) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    for name, spec in (t.get("params") or {}).items():
        schema["properties"][name] = {k: v for k, v in spec.items() if k != "default"}
        if "default" in spec:
            schema["properties"][name]["default"] = spec["default"]
        if spec.get("type") != "object" and "default" not in spec and "{" + name + "}" in t["path"]:
            schema["required"].append(name)
    return schema


def _all_tools() -> List[types.Tool]:
    return [types.Tool(name=t["name"], description=f"[{t['scope']}] {t['desc']}",
                       inputSchema=_tool_schema(t)) for t in TOOLS]


def _missing_token_msg() -> str:
    return ("未配置 SC_AGENT_TOKEN。请在 MCP 客户端配置的 env 里提供 Agent Token"
            "（设置 → Agent 网关，或 python -m backend.agent.smoke_test --issue 生成）。")


async def _on_list_tools(ctx, params=None) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_all_tools())


async def _on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = str(getattr(params, "name", "") or "")
    args = dict(getattr(params, "arguments", None) or {})
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"未知工具：{name}")],
                                    is_error=True)
    if not _token():
        return types.CallToolResult(content=[types.TextContent(type="text", text=_missing_token_msg())],
                                    is_error=True)
    import asyncio
    res = await asyncio.to_thread(_call_http, tool, args)
    ok = bool(res.get("ok"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(res, ensure_ascii=False, indent=1))],
        is_error=not ok)


def build_server() -> Server:
    return Server("stock-classroom", version="0.1.0",
                  instructions=("stock-classroom A 股量化系统：行情/选股/回测/持仓/因子挖掘。"
                                "工具名前缀 sc_，方括号内是权限级别（R 只读 / W 写入 / B 回测 / T 交易）。"),
                  on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


async def amain() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    import asyncio
    asyncio.run(amain())


if __name__ == "__main__":
    main()
