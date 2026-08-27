# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v4.3
- **Type**: PyQt5 Desktop App + Optional Flask API
- **Python**: 3.14.3 (C:\Python314) — 项目运行时用这个; Hermes venv python 无 PyQt5 不可用
- **Database**: SQLite 多库 (kline.db + fundamental.db + stock_cache.db + sim_trade.db)
- **Data Source**: AKShare / Sina API (三源回退 Sina主/TX/EM)

## Architecture (plugin-based, v4.0+)
```
Platform Shell (~frameless custom titlebar, immutable)
  └─ PluginManager → discovers from frontend/plugins/
      └─ Each plugin: IPlugin subclass in plugin.py
Right pane = collapsible drawer (K线按需滑出, 非常驻)
```

**Key principle**: Platform never imports panel code directly. Plugins fail in isolation.

## Key Files
| Layer | Files | Purpose |
|-------|-------|---------|
| Entry | `desktop_app.py` (~30 lines) | App bootstrap |
| Platform | `frontend/platform/platform_shell.py` | Main window shell (frameless + 右栏抽屉) |
| Platform | `frontend/platform/plugin_manager.py` | Discover/register/activate/ErrorBoundary |
| Platform | `frontend/platform/plugin_base.py` | IPlugin interface, PlatformBus signals, PlatformServices |
| Platform | `frontend/platform/theme.py` | `build_style(base_fs)`, `fs()`, `dp()`, 3 主题 |
| Platform | `frontend/platform/premium.py` | PAL / well / card_qss / value_ss / SectionTitle |
| Backend | `backend/data_manager.py` | SQLite CRUD, AKShare dispatch, update_pool |
| Backend | `backend/akshare_source.py` | ~18 API wrappers + 3源回退 + 硬超时 |
| Backend | `backend/strategy/metrics.py` | full_metrics (α/年化/夏普/胜率/回撤/β) |
| Backend | `backend/strategy/describe.py` | 策略契约→中文 买入/持有/卖出 条件 |
| Backend | `backend/strategy/optimize_loop.py` | 自主策略进化闭环 (LLM 提新契约→回测→裁决) |
| Backend | `backend/strategy/portfolio_rebalance.py` | SelectionContract + forward_paper_run |
| Backend | `backend/agent/research_loop.py` | ResearchLoop 单标的/组合重平衡 |
| Backend | `backend/agent/llm_client.py` | LLMClient (DeepSeek) |
| Backend | `backend/trade_engine/` | **Simulated trading engine (v4.2)** |
| Backend | `backend/update_daily.py` | **每日自动化: K线池+基本面+纸面盘+净值快照** |
| Settings | `frontend/plugins/settings/config.py` | `load_settings()` / `save_settings()` → `backend/configs/settings.json` |
| Configs | `backend/configs/settings.json` | `font_size` + `window_size` + `agent{api_base, api_key, model}` |

## Plugins (all in `frontend/plugins/`, 15 total)
Nav 分两组 (plugins.json `nav_groups`): **核心工作流** + **数据工具**。

| ID | Region | 组 | Description |
|----|--------|----|-------------|
| overview | LEFT | 核心 | **总览 landing 页**: 账户卡/最近策略/市场速览/主功能/账户中心 |
| research | LEFT | 核心 | 因子研究 + 策略进化闭环入口 |
| picks | LEFT | 核心 | Factor scoring Top 20 |
| holdings | LEFT | 核心 | 纸面盘账本 (5策略曲线/持仓/调仓) |
| trade | LEFT | 核心 | **Simulated trading panel (v4.2)** |
| agentops | LEFT | 核心 | **AI操盘台** (单标的闭环/组合重平衡) |
| market | LEFT | 数据 | Market overview + sectors |
| datacenter | LEFT | 数据 | Database browser |
| datapipeline | LEFT | 数据 | Data update pipeline |
| trainer | LEFT | 数据 | Backtest training placeholder |
| flow | LEFT | 数据 | 全流程指挥舱 (frontend/flow) |
| kline | RIGHT | 数据 | K-line chart (QPainter) |
| agent | TOPBAR | — | Floating AI chat (6-tool function calling) |
| search | TOPBAR | — | Stock search input |
| settings | TOPBAR | — | Gear → settings (font/window/AI) |

## Navigation Order
`plugins.json` → `nav_groups` = [核心工作流(overview/research/picks/holdings/trade/agentops), 数据工具(market/datacenter/datapipeline/trainer/flow/kline)]. `default_left=overview`, `default_right=kline`.

## Theme (v4.2)
- Dark: `#0D1117` (bg) / `#161B22` (panel) / `#D4A574` (accent gold) — graphite
- 3 themes: graphite / obsidian / ivory. `theme.py: build_style(base_fs)` + `premium.PAL`(live, 挂 signals.changed 自刷)
- `fs()` font scaling, `dp()`/`dps()` dimension scaling

## Naming Conventions
- Plugin files: `plugin.py`, `panel.py`, `companion.py`
- Backend: `backend/` contains all data logic
- Chinese UI text everywhere; use `dp(x)`/`fs(x)` not hardcoded px

## Build
```bat
package\build_desktop.bat
```
Output: `dist/StockClassroom/`. Requires SQLite 库 in `data/`.

## Dependencies
Core: `flask`, `PyQt5`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`
- 项目固定 venv `.update-venv/` (uv, 供每日自动化 update_daily.py) 装 akshare/pandas.

## Git
Remote: `https://github.com/1479650473/stock-classroom`
- data/ 整目录 gitignored, 不入库; 临时 `_*.py/_*.png/_*.log` 不入库; api_key 绝不入库.
