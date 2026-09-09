# PLUGIN_MAP.md — stock-classroom 插件功能整理 & 前端逻辑梳理

> 目标：把 15 个插件的功能、数据来源、在主流程里的角色、以及前端整体逻辑（架构/数据流/主题/异步）说清楚。
> 服务端：`frontend/flow/flow_server.py`（`127.0.0.1:8234`）提供 `/status`+`/run/<stage>` 可介入 API。

---

## 1. 应用定位 & 主干闭环

**stock-classroom v4.3 — 大模型驱动的 A 股量化交易员桌面端（PyQt5 多插件）**。

主干闭环（主流程）：
```
数据管道(datapipeline) → 因子研究(research) → 策略回测(trainer/holdings) → 组合重平衡/纸面盘(paper→holdings/trade) → LLM 迭代(agent/agentops)
```
数据底座：`data/kline.db`（年度分区 `kline_YYYY` + `kline_daily` 视图）、`fundamental.db`、`stock_cache.db`、`sim_trade.db`。

## 2. 插件架构
- `frontend/platform/plugin_manager.py`：按 `plugins.json` 动态加载插件(`IPlugin`: plugin_id/name/icon/region/create_widget)。
- `PluginRegion`: `LEFT`(左栈)/`RIGHT`(右栈)/`TOPBAR`(顶栏)。
- `PlatformServices`：注入 `db_path`(kline.db)、`cache_path`(stock_cache.db)、`bus`(PlatformBus)。
- 外壳 `platform_shell.py`：**无边框自绘标题栏** + 左右 QStackedWidget + 导航栏 + 顶栏；**右栏=可折叠抽屉**（K线按需滑出）。
- 主题引擎 `theme.py`：`THEMES={graphite|obsidian|ivory}`，`build_style(key)`、`signals.changed`。工具包 `premium.py`：`PAL/card_qss/value_ss/label_ss/SectionTitle/CountUpLabel/well()`。

## 3. 每个插件功能表
| # | plugin_id | 名称 | 区域 | 组 | 功能 | 数据来源 | 主流程角色 |
|---|---|---|---|---|---|---|---|
| 1 | overview | 总览 | LEFT | 核心 | **landing 页**: 账户卡/最近最强策略/市场速览/主功能入口/账户中心 | `paper_runs.json`+`trade_engine` | 首页 |
| 2 | research | 研究 | LEFT | 核心 | 因子研究(BP/EP/ROE IC·ICIR) + 纸面盘 + **策略进化闭环入口** | `backend.strategy.factor_research` | **因子研究** |
| 3 | picks | 选股 | LEFT | 核心 | 因子选股 Top 20 | `factor_engine` | 策略选股 |
| 4 | holdings | 持仓 | LEFT | 核心 | **纸面盘账本**: 5策略曲线对比/每日持仓/每笔调仓 + **精确指标(α/年化/夏普)+买卖条件原理** | `data/paper_runs.json` | **纸面盘持仓(末步)** |
| 5 | trade | 交易 | LEFT | 核心 | 模拟账户/下单/成交 | `trade_engine`(sim_trade.db) | 模拟盘操作 |
| 6 | agentops | AI操盘 | LEFT | 核心 | **AI操盘台**: 单标的闭环 / 组合重平衡 | `research_loop` + `sim_trade.db` | **LLM 迭代/操盘** |
| 7 | market | 市场 | LEFT | 数据 | 大盘指数卡 + 涨跌分布 + 板块表 | `kline.db`(sector_board) | 行情总览 |
| 8 | datacenter | 数据中心 | LEFT | 数据 | 全市场列表 + 基本面详情 | `fundamental.db`+`kline.db` | 数据预览 |
| 9 | datapipeline | 数据管道 | LEFT | 数据 | 数据更新步骤表 | `data_manager` + `cache_modules` | **数据更新** |
| 10 | trainer | 回测训练 | LEFT | 数据 | 策略回测占位 | `backend.strategy.*` | **策略回测** |
| 11 | flow | 流程 | LEFT | 数据 | 全流程指挥舱(6步流水线+介入) | `frontend/flow/*` | **流程可视化** |
| 12 | kline | K线 | RIGHT | 数据 | 个股K线/均线/MACD/RSI (**右栏抽屉按需滑出**) | `kline.db`(get_kline_data) | 图表 |
| 13 | agent | AI助手 | TOPBAR | — | LLM 聊天(研究员/复盘) | DeepSeek(`settings.json`) | **LLM 迭代** |
| 14 | search | 搜索 | TOPBAR | — | 股票搜索输入 | — | 入口 |
| 15 | settings | 设置 | TOPBAR | — | 主题/字号/窗口/LLM 配置 | `settings.json` | theme 切换 |

## 4. 前端逻辑梳理
- **数据流**：插件 `create_widget` → 读库或调后端函数（多走 `LocalWorker`/`QThread`）→ 结果信号回主线程 → 填 UI。
- **右栏抽屉**：`_route_companion` 有 companion 才展开；无 companion 且未开 K线 → `_set_drawer(False)`（收起，左插件全屏）。`open_kline` 信号 → `_on_kline_request` 滑出。顶栏"K线"按钮开合。
- **导航分组**：`plugins.json#nav_groups` → 核心工作流 / 数据工具 两组，`default_left=overview`。
- **跨插件跳转**：`services.navigate(plugin_id, payload)` → 落地插件 `apply_navigation(payload)`（如"研究"带 `{hp:20}` 直达默认持有期）。
- **主题**：token 在 `theme.THEMES`，面板用 `premium.PAL`(live)。勿硬编码 hex、勿用 import 冻结的 `C_*`。
- **事件总线** `PlatformBus`：`open_kline`/`status_message`/`refresh_current`/`data_update_progress`/`settings_changed`/`navigate_plugin`。

## 5. 主流程 ↔ 插件映射
| 流程步 | 后端 | 前端插件/入口 |
|---|---|---|
| ① 数据更新 | `update_pool` / `update_daily.py` | datapipeline / Windows计划任务17:00 |
| ② 因子研究 | `study_factors` | research |
| ③ 策略回测 | `forward_paper_run` | holdings / trainer |
| ④ 组合重平衡/纸面盘 | `run_paper_multi`(forward_paper_run×N) | **holdings（多策略账本: 曲线+持仓+调仓+精确指标+条件原理）** |
| ⑤ 收益对比 | paper vs buyhold | flow compare 步 |
| ⑥ LLM 迭代 | `research_loop` / `optimize_loop` | agent / agentops |

## 6. 策略进化闭环 (v4.3, optimize_loop)
`backend/strategy/optimize_loop.py::run_optimize_loop()` — 一个函数跑通自主闭环：
① 5家族回测(精确指标 α/年化/夏普/胜率/回撤) → ② LLM/Stub 提新因子契约 → ③ 回测新契约 → ④ 裁决(不盲从AI, 收益更高才 accept) → ⑤ accept 写入模拟盘 + 每日交易记录。
- `metrics.py::full_metrics` 单一支撑: 总收益/年化α/CAGR/夏普/索提诺/Calmar/最大回撤/波动/β/超额/基准。
- `describe.py::describe_contract` 把契约渲染成中文"买入/持有/卖出"条件。
- LLMClient 在 `backend/agent/llm_client.py`。

## 7. 每日数据自动化 (v4.3)
- `backend/update_daily.py` + Windows 计划任务 `StockClassroom-DailyUpdate`（周一至五 **17:00**，app 关闭也能跑）。
- 刷新四步: ① 量化池K线(update_pool, ~287只) ② 基本面EP/BP/ROE ③ 纸面盘(paper_runs) ④ 账户净值快照(snapshot_nav)。
- 项目固定 venv `.update-venv/`（不依赖 `C:\Python314` 路径）。
- 交易日缓存 `data/trade_calendar.json`（akshare 日历, 非交易日跳过）。
- **K线源新鲜度**：新浪当日收盘 15:30 后逐步到位；DB max < 今日 会明确警告（防静默空转）。

## 8. 账户管理 + 净值曲线
- engine 直接操作: `create_account(name, capital)`/`rename_account`/`delete_account`/`reset_account`/`list_account_summaries`。
- **净值曲线(每日真实快照)**: `account_nav` 表 + `snapshot_nav(id)`(幂等同日覆盖) + `get_nav_history(id)`。总览 AI账户卡 `MiniNavSpark` 纯色折线。**勿用成交回放伪造NAV**(成交流水与余额不一致时会出负值伪历史)。

## 9. 已知问题
1. **多策略纸面盘内存峰值**: `run_paper_multi` 连续跑5策略时, 每策略内部为各因子建 287×1516 panel, 累计峰值可 OOM(小分配也失败)。已用 每策略后 del+gc.collect 缓解; 但系统内存紧张(Free~1GB)时 C低波动 仍可能 OOM —— 可单独跑该策略再 merge 进 paper_runs.json。
2. **research/picks/trainer** 打开为空, 需点「运行」按钮。
3. **frontend/ 加入 sys.path 会遮蔽 stdlib `platform`** → pandas 导入崩。
4. **成交流水与余额不一致(测试写入)** → 勿用其回放净值。
