# -*- coding: utf-8 -*-
"""Agent Gateway 的 MCP server —— 薄包 R+B(读/回测)，默认不暴露交易。

设计对齐 QuantDinger：MCP 是 /api/agent/v1 的可选附加层，不是平行实现。
- token 从环境变量 SC_AGENT_TOKEN 读取(绝不让模型提供凭据)
- 只暴露 R(读) + B(回测)，交易(T)默认不暴露给 MCP
- 走 stdio(默认，IDE/本地)或 streamable-http(远程代理)传输

启动(项目根)：
  SC_AGENT_TOKEN=sc_agent_xxx python -m backend.agent.mcp_server
  # 或 QUANTDINGER_MCP_TRANSPORT=sse / streamable-http 切换
"""
from __future__ import annotations

import os
from typing import Any, Optional

import requests
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("SC_AGENT_BASE_URL", "http://127.0.0.1:5000")
TOKEN = os.environ.get("SC_AGENT_TOKEN", "").strip()
TRANSPORT = os.environ.get("SC_MCP_TRANSPORT", "stdio").lower()

mcp = MCPServer("stock-classroom-agent")


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _call(method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
    """调用网关并解包 {code, data}。失败抛 RuntimeError。"""
    url = BASE_URL + path
    try:
        if method == "GET":
            r = requests.get(url, headers=_headers(), params=params, timeout=60)
        else:
            r = requests.post(url, headers=_headers(), json=body or {}, params=params, timeout=60)
        payload = r.json()
    except Exception as e:
        raise RuntimeError(f"网关调用失败({path}): {e}")
    if not r.ok or payload.get("code", 0) != 0:
        err = payload.get("error") or payload
        raise RuntimeError(f"{err.get('message', err)}")
    return payload.get("data")


def _wait_job(job_id: str, poll: int = 2, timeout: int = 120) -> dict:
    """轮询异步回测 job 直到结束。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = _call("GET", f"/api/agent/v1/jobs/{job_id}")
        if j and j.get("status") in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(poll)
    raise RuntimeError(f"job {job_id} 超时未完成")


# ── R：宏观 ───────────────────────────────────────────────────────────
@mcp.tool()
def macro_regime() -> dict:
    """全球宏观 regime(整体+类别+每指标最新/变化/趋势/新鲜度)，供生成/修订A股策略时读宏观语境。"""
    return _call("GET", "/api/agent/v1/macro/regime")


@mcp.tool()
def macro_indicators(category: Optional[str] = None) -> list:
    """列出影响A股的宏观指标目录(可选 category: equity/fx/rate/commodity/vol)。"""
    return _call("GET", "/api/agent/v1/macro/indicators", params={"category": category})


# ── R：目录 ───────────────────────────────────────────────────────────
@mcp.tool()
def catalog_stats() -> dict:
    """标的池统计(总数/活跃/板块数)。"""
    return _call("GET", "/api/agent/v1/catalog/stats")


@mcp.tool()
def catalog_sectors() -> list:
    """可用板块枚举(用于 select 校验)。"""
    return _call("GET", "/api/agent/v1/catalog/sectors")


@mcp.tool()
def catalog_select(sector: Optional[str] = None, board: Optional[str] = None,
                   status: Optional[str] = "active", name_kw: Optional[str] = None) -> list:
    """按条件筛标的池(sector/board=sh|sz/status=active|delisted/name_kw)。非法值报错并列出可用板块。"""
    return _call("GET", "/api/agent/v1/catalog/select",
                 params={"sector": sector, "board": board, "status": status, "name_kw": name_kw})


@mcp.tool()
def catalog_describe(code: str) -> dict:
    """单标的元数据(名称/板块/状态/所属粗赛道)。"""
    return _call("GET", f"/api/agent/v1/catalog/describe/{code}")


@mcp.tool()
def catalog_search(keyword: str, limit: int = 30) -> list:
    """按名称关键词搜股票。"""
    return _call("GET", "/api/agent/v1/catalog/search", params={"q": keyword, "limit": limit})


@mcp.tool()
def catalog_boards(limit: int = 20, board_type: Optional[str] = None) -> list:
    """东财行业/概念板块热力(含龙头/涨跌)。board_type: industry|concept。"""
    return _call("GET", "/api/agent/v1/catalog/boards", params={"limit": limit, "type": board_type})


@mcp.tool()
def catalog_leader_of(name: str) -> dict:
    """按板块名找东财板块龙头。"""
    return _call("GET", "/api/agent/v1/catalog/leader-of", params={"name": name})


# ── R：因子 / K线 ─────────────────────────────────────────────────────
@mcp.tool()
def factors(category: Optional[str] = None) -> list:
    """策略契约可用的因子 key(价格/均线/MACD/RSI/布林/派生/布尔/交叉)。"""
    return _call("GET", "/api/agent/v1/factors", params={"category": category})


@mcp.tool()
def klines(code: str, days: int = 180) -> dict:
    """单标的日K(含技术指标enriched)，供策略回测前的数据核查。"""
    return _call("GET", "/api/agent/v1/klines", params={"code": code, "days": days})


# ── R：策略 / 组合 ────────────────────────────────────────────────────
@mcp.tool()
def list_strategies() -> list:
    """列出本 agent 已保存的声明式策略。"""
    return _call("GET", "/api/agent/v1/strategies")


@mcp.tool()
def get_strategy(strategy_id: int) -> dict:
    """取单个声明式策略详情(含契约JSON)。"""
    return _call("GET", f"/api/agent/v1/strategies/{strategy_id}")


@mcp.tool()
def positions() -> dict:
    """模拟账户持仓(组合读数)。"""
    return _call("GET", "/api/agent/v1/positions")


# ── B：回测(异步 -> 轮询) ─────────────────────────────────────────────
@mcp.tool()
def submit_backtest(strategy_id: int, params: Optional[dict] = None) -> dict:
    """提交异步回测，立即返回 {job_id, status}。params 可覆盖 initial_balance/bars。"""
    return _call("POST", "/api/agent/v1/backtest/run",
                 body={"strategy_id": strategy_id, "params": params or {}})


@mcp.tool()
def run_backtest_and_wait(strategy_id: int, params: Optional[dict] = None) -> dict:
    """提交回测并阻塞等待完成，返回指标+最近成交+权益尾部。"""
    j = _call("POST", "/api/agent/v1/backtest/run",
              body={"strategy_id": strategy_id, "params": params or {}})
    return _wait_job(j["job_id"])


@mcp.tool()
def get_job(job_id: str) -> dict:
    """查异步 job 状态/结果。"""
    return _call("GET", f"/api/agent/v1/jobs/{job_id}")


@mcp.tool()
def cancel_job(job_id: str) -> dict:
    """取消未完成的回测 job。"""
    return _call("POST", f"/api/agent/v1/jobs/{job_id}/cancel")


def main():
    if not TOKEN:
        import sys
        print("ERROR: 请设置环境变量 SC_AGENT_TOKEN(用 backend.agent.cli issue 签发)", file=sys.stderr)
        return 1
    if TRANSPORT in ("sse", "streamable-http"):
        host = os.environ.get("SC_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("SC_MCP_PORT", "8765"))
        mcp.run(transport=TRANSPORT, host=host, port=port)
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
