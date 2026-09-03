# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v5.0 — Web 栈(Vue3+TS+ECharts+Tauri2) + Flask API (+ PyQt5 旧版仍在 frontend/)
- **Type**: Tauri 2 Desktop App (Web frontend) + Flask API v2 (blueprints)
- **Python**: 3.14.3 (C:\Python314) — 项目运行时用这个; Hermes venv python 无 PyQt5 不可用
- **Database**: SQLite 多库 (kline.db + fundamental.db + stock_cache.db + sim_trade.db)
- **Data Source**: AKShare / Sina API (三源回退 Sina主/TX/EM)

## Architecture (Web v5.0)
```
Tauri Shell (web/src-tauri, frameless, 启动时拉起 stock-api.exe sidecar)
  └─ Vue3 SPA (web/src: views/router/stores/composables)
       └─ Flask API 127.0.0.1:5000 (backend/api/server.py, 12+ blueprints, 统一 envelope)
```
- **后端打包**: `package/stock_api.spec` → 单文件 `stock-api.exe` (PyInstaller, 含 akshare data)
- **前端打包**: `web/src-tauri` → NSIS/MSI 安装包 (bundle.resources 内嵌 stock-api.exe)
- **⚠️ 打包坑**: `frontend/platform/` 是名为 `platform` 的包, **绝不能**把 frontend 加入 PyInstaller pathex (遮蔽 stdlib platform → pandas 崩溃)
- **打包后数据目录**: exe 旁 `data/` (或 `SC_DATA_DIR` 环境变量); frozen 路径经 `backend/api/paths.py` / `data_manager.py` `/trade_engine/schema.py` 处理

## Web API(backend/api/)
- `server.py`: create_app, 全局错误信封, CORS 限本机 origins
- `envelope.py`: ok/err + `int_arg()` 安全解析; 所有 blueprint 统一 error.code=string
- `jobman.py`: 线程池 job + SSE, 6h TTL 清理; `client.ts.streamJob` 前端复用
- `agent_chat.py`: `/api/agent/chat` SSE tool-calling(16工具); `backend/agent/toolkit.py`
- PyQt5 桌面入口 `desktop_app.py` / `frontend/plugins/*`(研究worker/训练引擎)**仍是后端核心**, 被蓝本图 import (如 frontend.plugins.research.worker)

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
| Backend | `backend/strategy/regime.py` | A股牛/熊/震荡分类 + 系统性风险截断 + 权重动态化 |
| Backend | `backend/strategy/sell_rules.py` | 卖出三驱动规约(止损/移动止损/策略卖出, 无止盈) |
| Backend | `backend/strategy/position_guard.py` | 持仓守护引擎(单持仓保护判定) |
| Backend | `backend/strategy/day_guard.py` | 每日持仓守护循环(读模拟账户→判定→预览/真卖) |
| Backend | `backend/strategy/verify_full_lifecycle.py` | 完整生命周期验证(选股→买→持有带保护→卖→结算→净值) |
| Backend | `backend/strategy/cycle_test.py` | 分周期测试(牛/熊/震荡/全周期/样本内外防过拟合) |
| Backend | `backend/strategy/stock_deep.py` | 个股资讯深挖+LLM主观判断(选股剩几只后) |
| Backend | `backend/strategy/news_driven.py` | 事件驱动候选池(涨停+热点板块+豆包消息, isolated) |
| Backend | `backend/agent/search_client.py` | 豆包搜索客户端(资讯源, 财经语境) |
| Backend | `backend/agent/research_loop.py` | ResearchLoop 单标的/组合重平衡 |
| Backend | `backend/agent/llm_client.py` | LLMClient (DeepSeek) + `chat_with_tools` |
| Backend | `backend/agent/toolkit.py` | **Web Agent 工具集(16)**: 交易6/研究4/策略6, `execute_tool(name, args)` |
| Backend | `backend/trade_engine/` | **Simulated trading engine (v4.2)** |
| Backend | `backend/update_daily.py` | **每日自动化: K线池+基本面+纸面盘+净值快照+regime+事件池+深挖+守护** |
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

## 卖出三驱动(用户策略哲学, 已定死) + 验证
- **不加固定止盈(让利润奔跑)**, 用**三驱动**: ①条件止损(默认8%, 兜底防大亏) ②移动止损(默认10%回撤/15%激活, 利润奔跑后锁利) ③策略卖出/重平衡调出(信号/排名失效兑现). `sell_rules.SellRuleSet.build(rebalance_bars, top_k_pct, stop_loss_pct=0.08, take_profit_pct=0, trailing_stop_pct=0.10, trailing_activation_pct=0.15, enable_rebalance_exit=True)`; `time_limit_bars` 默认0(不设时间止损, 与重平衡周期同长会每期清仓致 rebalance_exit 永不触发). 卖出优先级: 止损>移动止损>重平衡调出>止盈.
- **完整生命周期验证**: `verify_full_lifecycle(frames, contract, start, end, rule_set)` 逐日回放(每日保护判定+重平衡日排名调出+净值/指标/胜率/α). **保护bar必须用真实 open/high/low panel**(high/low=0 会每票每值误报止损).
- **分周期测试**: `cycle_test.run_cycle_test(frames, contract, rule_set)` 按 regime 把历史切成牛/熊/震荡主要周期段, 各段跑 verify → 对比 + 样本内/样本外(防过拟合) + 全周期. 对应架构图"回测架构".
- 卖出引擎: `position_guard.PositionGuard`(单持仓判定) + `day_guard.run_day_guard(dry_run=True)`(每日读模拟账户, 默认预览不真卖). 落库 `data/day_guard_log.json`. 前端 trade 持仓表加"卖出条件"列(触发红'止损'/绿'移动止损'/黄, 未触发灰'保护中').

## Theme (v4.2)
- Dark: `#0B0D11` (bg) / `#14171C` (panel) / `#D4A574` (accent gold) — graphite
- 3 themes: graphite / obsidian / ivory. `theme.py: build_style(base_fs)` + `premium.PAL`(live, 挂 signals.changed 自刷)
- `fs()` font scaling, `dp()`/`dps()` dimension scaling

## Naming Conventions
- Plugin files: `plugin.py`, `panel.py`, `companion.py`
- Backend: `backend/` contains all data logic
- Chinese UI text everywhere; use `dp(x)`/`fs(x)` not hardcoded px

## Build
**Web 版(Tauri) — 需要 vcvars64 环境(cl.exe)**:
```bat
rem 1) 后端 sidecar (PyInstaller, 含 akshare data)
python -m PyInstaller --clean --noconfirm package\stock_api.spec --distpath package\dist --workpath package\build_api
rem 2) 前端 + 外壳 (需先 activate VS BuildTools vcvars64)
cd web\src-tauri && cargo tauri build
rem 输出: web\src-tauri\target\release\bundle\{msi,nsis}\StockClassroom_*.exe
rem 便携版: package\dist\stock-api.exe 与 web\src-tauri\target\release\stock-classroom.exe 放同目录, 旁有 data/ + backend/configs/
```
**PyQt5 旧版**: `package\build_desktop.bat` → `dist/StockClassroom/`. Requires SQLite 库 in `data/`.

## Dependencies
Core: `flask`, `PyQt5`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`
- 项目固定 venv `.update-venv/` (uv, 供每日自动化 update_daily.py) 装 akshare/pandas.

## Git
Remote: `https://github.com/1479650473/stock-classroom`
- data/ 整目录 gitignored, 不入库; 临时 `_*.py/_*.png/_*.log` 不入库; api_key 绝不入库.
