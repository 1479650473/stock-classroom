# -*- coding: utf-8 -*-
"""MCP 自检：列出工具清单，并可对某个工具发一次真实调用。

    python -m backend.mcp_server.smoke_test                 # 只列工具
    python -m backend.mcp_server.smoke_test sc_health       # 调用某工具（需 SC_AGENT_TOKEN）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.mcp_server.server import TOOLS, build_server  # noqa: E402


async def main() -> None:
    print(f"工具数量：{len(TOOLS)}")
    for t in TOOLS:
        req = [p for p in (t.get("params") or {}) if "{" + p + "}" in t["path"]]
        print(f"  [{t['scope']}] {t['name']:<22} {t['method']:<6} {t['path']}"
              + (f"  (必填: {', '.join(req)})" if req else ""))
    if len(sys.argv) > 1:
        from mcp.types import CallToolRequest, CallToolRequestParams
        name = sys.argv[1]
        res = await handler[CallToolRequest](CallToolRequest(
            method="tools/call", params=CallToolRequestParams(name=name, arguments={})))
        print("\n调用结果：", json.dumps(res.model_dump(), ensure_ascii=False)[:1200])


if __name__ == "__main__":
    asyncio.run(main())
