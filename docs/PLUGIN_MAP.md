# PLUGIN_MAP.md — stock-classroom 插件功能整理 & 前端逻辑梳理

> 目标：把 13 个插件的功能、数据来源、在主流程里的角色、以及前端整体逻辑（架构/数据流/主题/异步）说清楚，并为「前端跟不上后端」定位缺口。
> 服务端：`frontend/flow/flow_server.py`（`127.0.0.1:8234`）提供 `/status`+`/run/<stage>` 可介入 API。

---

## 1. 应用定位 & 主干闭环

**stock-classroom v4.3 — 大模型驱动的 A 股量化交易员桌面端（PyQt5 多插件）**。

主干闭环（主流程）：
```
数据管道(datapipeline) → 因子研究(research) → 策略回测(trainer) → 组合重平衡/纸面盘(paper→holdings/trade) → 收益对比(compare) → LLM 迭代(agent)
```
数据底座：`data/kline.db`（年度分区 `kline_YYYY` + `kline_daily` 视图）、`fundamental.db`、`macro.db`、`stock_cache.db`、`sim_trade.db`。

## 2. 插件架构
- `frontend/platform/plugin_manager.py`：按 `plugins.json#nav_order` 动态加载插件（`IPlugin` 接口：`plugin_id/name/icon/region/create_widget/on_activate/refresh`）。
- `PluginRegion`: `LEFT`(左栈)/`RIGHT`(右栈)/`TOPBAR`(顶栏)。
- `PlatformServices`：注入 `db_path`(kline.db)、`cache_path`(stock_cache.db)、`bus`(PlatformBus 信号总线)。插件要么直接连库、要么调后端函数（`data_manager`、`trade_engine.engine.TradeEngine`、`backend.strategy.*`）。
- 外壳 `platform_shell.py`：左右 QStackedWidget + 导航栏 + 顶栏；主题切换即时重绘（`_on_theme_changed`→重建 QSS+`resync_theme()`+每个控件 `on_theme_changed()`）+ `_ThemeWipe` 柔光扫过。
- 主题引擎 `frontend/platform/theme.py`：`THEMES={graphite|obsidian|ivory}`，`build_style(key)`、`current_theme()`、`signals.changed`。工具包 `premium.py`：`PAL/card_qss/value_ss/label_ss/SectionTitle/CountUpLabel/BreadthGauge/SplitBar/MachinedWell/well()`。

## 3. 每个插件功能表
| # | plugin_id | 名称 | 区域 | 功能 | 数据来源 | 主流程角色 | 状态/说明 |
|---|---|---|---|---|---|---|---|
| 1 | search | 搜索 | TOPBAR | 「输入代码选择股票」搜索框 | — | 入口 | 输入代码 → `bus.open_kline` 打开K线 |
| 2 | settings | 设置 | TOPBAR | 外观主题/字号/窗口大小/LLM配置 | `settings.json` | — | theme 切换入口 |
| 3 | agent | Agent | LEFT | LLM 聊天(研究员/复盘) | DeepSeek(`settings.json`) | **LLM 迭代(最后一步)** | 真 LLM |
| 4 | market | 市场 | LEFT | 大盘指数卡 + 涨跌分布 + 行业/概念板块表 | `kline.db`(sector_board/kline_daily) | 行情总览 | ✅ 板块表激活即自动加载(已修) |
| 5 | picks | 选股 | LEFT | 选股(价值/策略) | 需动作按钮 | 策略选股 | ⚠️ 打开为空, 需点「选股」 |
| 6 | **holdings** | 持仓 | LEFT | **纸面盘账本**: 多策略收益曲线对比 + 每日持仓 + 每笔调仓 | `data/paper_runs.json`(run_paper_multi) | **纸面盘持仓(末步)** | ✅ **已重做**: 5 策略对比/持仓/调仓/曲线 |
| 7 | research | 研究 | LEFT | 因子研究: BP/EP/ROE IC·ICIR、纸面盘 | `backend.strategy.factor_research` etc. | **因子研究** | ⚠️ 打开为空, 需点「运行研究」 |
| 8 | trade | 交易 | LEFT | 模拟账户管理/下单/成交 | `trade_engine.engine.TradeEngine`(sim_trade.db) | 模拟盘操作 | ✅ 后端 7 账户正常 |
| 9 | datapipeline | 数据管道 | LEFT | 数据更新步骤表 | `data_manager` + `cache_modules` | **数据更新** | ✅ 10 步; K线步函数改名已修 |
| 10 | datacenter | 数据中心 | LEFT | 全市场股票列表 + 基本面详情 | `fundamental.db`+`kline.db` | 数据预览 | ✅ 股票列表 5205 只; 详情需选股 |
| 11 | trainer | 训练 | LEFT | 策略训练/回测 | `backend.strategy.*` | **策略回测** | ⚠️ 打开为空/无表格 |
| 12 | flow | 流程 | LEFT | **全流程指挥舱**(6步流水线+介入) | `frontend/flow/*` | **流程可视化** | ✅ web(QWebEngineView)+原生双形态 |
| 13 | kline | K线 | RIGHT | 个股K线/均线/MACD/RSI | `kline.db`(get_kline_data) | 图表 | ✅ 搜索/点击股票查看 |

## 4. 前端逻辑梳理
- **数据流**：插件 `create_widget` → 读 `db_path` 库 或 调后端函数（多走 `LocalWorker`/`QThread` 后台线程）→ 结果信号回主线程 → 填 QTableWidget/QLabel。**离开真实 Qt 事件循环时（offscreen）不渲染文字，验证用 `.text()/.rowCount()` 或前台真渲染截图。**
- **主题**：token 在 `theme.THEMES`，面板用 `premium.PAL`(live) / `qss_*`(当前主题分支)。**勿硬编码 hex、勿用 import 冻结的 `C_*`**（破浅色 ivory 主题 / 切主题后仍卡深色）。
- **事件总线** `PlatformBus`：`open_kline`/`status_message`/`refresh_current`/`data_update_progress`/`settings_changed`。
- **卡片**：`well(name)` 自绘 `MachinedWell`（QPainter，主题感知），非 QSS 卡。
- **异步**：数据加载基本都是 `LocalWorker`(QThread)+信号，避免阻塞 UI；进度回传在 flow 里用引擎 PROGRESS + QTimer 轮询。

## 5. 主流程 ↔ 插件映射
| 流程步 | 后端 | 前端插件/入口 |
|---|---|---|
| ① 数据更新 | `data_manager.daily_update` | datapipeline（步骤表） |
| ② 因子研究 | `study_factors` | research（运行研究） |
| ③ 策略回测 | `run_backtest` | trainer / research |
| ④ 组合重平衡/纸面盘 | `run_paper_multi`(forward_paper_run×N 契约) | **holdings（多策略账本: 曲线对比+每日持仓+调仓历史）** / trade |
| ⑤ 收益对比 | paper vs buyhold | flow compare 步 |
| ⑥ LLM 迭代 | `agent.*` | agent（聊天） |

## 6. 发现的脱节/问题（前端跟不上后端）
1. **holdings 从前毫无用处**（只显示 sim_trade 当天持仓）——**已重做**：读 `paper_runs.json` 展示 5 策略纸面盘账本（收益曲线对比/每日持仓/每笔调仓），见 §7。
2. **market 板块表**激活即空（需点「行业板块」）——已修（激活自动 `_load_sectors()`）。
3. **research/picks/trainer** 打开为空，需点「运行」按钮——功能藏在按钮后，体感「用不了」。
4. **datacenter 详情**需选股才出（正常交互）。
5. **`data_manager.update_kline`** 已改名为 `daily_update`（datapipeline 曾调用不存在函数，已修）。
6. **frontend/ 加入 sys.path 会遮蔽 stdlib `platform`** → pandas 导入崩（研究代理/面板隐患；app 本体不受影响）。

## 7. holdings 重做（已完成）
持仓 = 主流程末步「纸面盘」账本，读 `data/paper_runs.json`（`research/worker.py::run_paper_multi` 持久化，5 策略契约 + 买持基准）：
- **策略选择器**：F价值Tilt / D多因子 / A价值 / B反转 / C低波动（下拉切换；单策略时自动隐藏）。
- **收益曲线(策略对比)**：5 策略净值线 + 买持虚线，选中加亮(★)；买持按策略重平衡日网格采样（公平对比，避免日频抖动拉伸）。
- **每日/每调仓日持仓**：`daily_holdings[]`（date→holdings{code:qty}+cash+nav）；市值/现价/权重用 `kline_daily` join（日期归一化为紧凑 `YYYYMMDD`）。
- **每笔调仓历史**：`rebalance_log[]`（date→trades[{code, side, qty, price}]）。
数据源后端：`research/worker.py::run_paper_multi()`（内部 `forward_paper_run(frames, contract, ...)`×5）+ `portfolio_rebalance.py::forward_paper_run`（已增强记录 daily_holdings/rebalance_log）。

> 数据口径：纸面盘用 ~287 跨板块池(wide_pool)，`forward_paper_run` 真实现金/持仓追踪+逐期 mark-to-market。
> 取数时间：`data/paper_runs.json` 由 flow 指挥舱「纸面盘」步（`run_paper_multi`）或 `_gen_paper_multi.py` 生成；as_of 2026-07-03。
