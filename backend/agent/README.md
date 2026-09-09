# Agent Gateway (M1) — `/api/agent/v1`

stock-classroom 的 **LLM 研究代理**基础设施：把现有 `strategy/`(回测)、`macro/`(全球宏观)、
`catalog/`(A股目录)、`trade_engine/`(模拟撮合) 通过一个**能力分级、可审计、paper-only** 的
网关暴露给 agent 调用。设计参照 QuantDinger 的 Agent Gateway，按本项目(单用户桌面 + SQLite)裁剪。

## 能力分级(scope)

| 级 | 含义 | 端点示例 |
|--|--|--|
| **R** 读 | 宏观/目录/因子/K线/策略列表/组合/作业 | `GET /macro/regime` `GET /catalog/select` `GET /klines` |
| **W** 工作区写 | 建/改声明式策略、watchlist | `POST /strategies` `POST /watchlist` |
| **B** 回测 | 提交异步回测 | `POST /backtest/run` |
| **T** 交易 | paper 下单(默认仅 paper) | `POST /paper/orders` |

- token 前缀 `sc_agent_`，**只存 sha256 哈希**，明文仅签发时显示一次。
- **process-local 限流**(per-token + per-tenant)，无需 Redis。
- 所有调用(成功/拒绝)写 `data/agent.db` 的 `agent_audit`。
- 变更类(W/B/T)支持 `Idempotency-Key` 头(原子保留，重放已完成)。
- **交易仅 paper**(经 `TradeEngine` 模拟撮合)；本部署无实盘路径，`/paper/kill-switch` 一键熔断。

## 铸 token(操作员动作，agent 绝不能自签)

```bash
C:/Python314/python.exe -m backend.agent.cli issue --scopes "R,W,B,T" --paper-only --agent-id mybot
# 输出一次性 full_token，立即保存
C:/Python314/python.exe -m backend.agent.cli list
C:/Python314/python.exe -m backend.agent.cli revoke <token_id>
```

调用时用 `Authorization: Bearer <token>` 或 `X-Agent-Token` 头。

## 启动

```bash
# 1) Web API(含网关)跑在 127.0.0.1:5000 — 网关已挂载进 backend/api/server.py
C:/Python314/python.exe run_web.py

# 2) MCP server(薄包 R+B，默认不暴露交易) — 给 Cursor/Claude Code/Hermes 用
SC_AGENT_TOKEN=sc_agent_xxx C:/Python314/python.exe -m backend.agent.mcp_server
#   SC_MCP_TRANSPORT=sse|streamable-http 可切远程传输; SC_AGENT_BASE_URL 默认 http://127.0.0.1:5000
#   远程代理用 HTTP 时: SC_MCP_TRANSPORT=streamable-http SC_MCP_PORT=8765
```

## 端点清单(全部挂 `/api/agent/v1`)

- **R**: `health` · `me/tokens` · `macro/regime` · `macro/indicators` · `catalog/{stats,sectors,select,describe/<code>,search,boards,leader-of}` · `factors` · `klines?code=&days=` · `positions` · `strategies` · `strategies/<id>` · `jobs/<id>` · `jobs` · `watchlist`
- **W**: `POST strategies` · `PATCH strategies/<id>` · `DELETE strategies/<id>` · `POST watchlist` · `DELETE watchlist/<code>`
- **B**: `POST backtest/run`(异步→job_id) · `jobs/<id>/stream`(SSE) · `jobs/<id>/cancel`
- **T**: `POST paper/orders`(paper-only) · `POST paper/kill-switch`

## 声明式策略契约

POST `/strategies`，body 即 `StrategySpec` JSON(v 见 `backend/strategy/spec.py`)，复用 `factor_engine/dsl`
条件树。示例见 `backend/agent/smoke_test.py` 的 `STRATEGY`。

## 验证

```bash
C:/Python314/python.exe backend/agent/smoke_test.py   # 36 项端到端自检，自清理
```

## 上层研究闭环 (M1/M2)

网关之上是 **LLM 研究闭环**：`research_loop.py`(Runner) 完成
`宏观 → 选板块 → 因子研究(IC/ICIR) → 生成(声明式契约) → 回测 → LLM复盘 → 多轮择优 → AI决策门 → paper`。
含双维度因子研究：技术因子(动/反转/波动/RSI 多窗口) + 价值/质量因子(EP/BP/ROE，东财每日估值，点时间)。
因子选择器 `factor_selector.recommend()` 按 ICIR 阈值**自动选参**。
完整说明见 **`docs/RESEARCH_AGENT.md`**；任务进度见 **`docs/TASK_LOG.md`**。

研究闭环验证：
```bash
C:/Python314/python.exe backend/agent/verify_research_loop.py  # 11/11
C:/Python314/python.exe backend/agent/verify_m2.py             # 34/34
C:/Python314/python.exe backend/agent/verify_llm_run.py        # 真LLM端到端(需 key)
```

## 安全红线

- 不要给 agent `C`(凭据)级能力——本应用无凭据流转，未启用。
- 实盘默认关闭；即使 token 不 `paper_only`，本部署也走模拟撮合(无真实 broker)。
- 网关不自行签发 token(只能经 CLI/管理员)，防止 agent 无限提权。
- `data/agent.db` 含网关状态，已 gitignore，不入库。
