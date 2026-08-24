# -*- coding: utf-8 -*-
"""agent — Agent Gateway(M1)：能力分级 + 异步job + paper-only安全 + 宏观/目录R接口。

设计参照 QuantDinger 的 Agent Gateway(/api/agent/v1)，按本项目(单用户桌面+SQLite)裁剪：
- 能力分级 R/W/B/T (去掉 N 通知、C 凭据——本应用无凭据流转)
- token 前缀 sc_agent_，只存 sha256 哈希；进程内限流(无 Redis)
- 回测等变更类走异步 job(ThreadPoolExecutor) → 轮询/SSE 流
- 所有调用写 agent_audit；变更类支持 Idempotency-Key
- 交易仅 paper(经 TradeEngine 模拟撮合)

启动路由：from backend.agent.routes import register; register(app)
"""
from . import store, gateway, jobs, services  # noqa: F401

__all__ = ["store", "gateway", "jobs", "services"]
