# stock-classroom MCP Server

把本项目的 **Agent Gateway（`/api/agent/v1`）** 暴露成 MCP，让 Claude Desktop / Cursor / Proma
等 MCP 客户端直接驱动这套系统（行情、选股、回测、持仓、策略、任务）。

设计参考 QuantDinger 的 `mcp_server`：**薄封装**——协议转换与鉴权转发，真正的能力、
权限分级（R 只读 / W 写入 / B 回测 / T 交易）、审计、幂等、限流都在服务端网关。

## 前置

1. 后端在跑：`python -c "from backend.api.server import create_app; create_app().run(port=5000)"`
2. 签发 Agent Token（**只在签发时返回一次**）：

```bash
python -c "from backend.agent import gateway as gw; import json; print(json.dumps(gw.issue_token('mcp-client', scopes='RWB'), ensure_ascii=False))"
```

返回里的 `full_token` 就是 token。

## 客户端配置

```json
{
  "mcpServers": {
    "stock-classroom": {
      "command": "python",
      "args": ["-m", "backend.mcp_server.server"],
      "cwd": "D:/小光工作区/projects/stock-classroom",
      "env": {
        "SC_BASE_URL": "http://127.0.0.1:5000",
        "SC_AGENT_TOKEN": "<上一步的 full_token>"
      }
    }
  }
}
```

Claude Desktop 配置文件位置：`%APPDATA%\Claude\claude_desktop_config.json`；
Cursor：`~/.cursor/mcp.json`。改完重启客户端。

## 工具清单（24 个）

| 级别 | 工具 |
|---|---|
| R | `sc_health` `sc_regime` `sc_indicators` `sc_market_stats` `sc_sectors` `sc_select` `sc_describe` `sc_search_symbol` `sc_leader_of` `sc_factors` `sc_klines` `sc_positions` `sc_strategies` `sc_strategy_get` `sc_watchlist` `sc_jobs` `sc_job_get` |
| W | `sc_strategy_create` `sc_strategy_update` `sc_watchlist_add` `sc_watchlist_remove` |
| B | `sc_backtest_run` |
| T | `sc_paper_order` `sc_kill_switch` |

## 自检

```bash
python -m backend.mcp_server.smoke_test            # 列工具
SC_AGENT_TOKEN=xxx python -m backend.mcp_server.smoke_test sc_health
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SC_BASE_URL` | `http://127.0.0.1:5000` | 后端地址 |
| `SC_AGENT_TOKEN` | 无 | Agent Token（必需，缺失时调用会返回明确提示） |
| `SC_TIMEOUT_S` | `30` | 单次请求超时 |
