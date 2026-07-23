# stock-classroom — 对话提示词

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 版本: v4.1 | 最后更新: 2026-07-24

## 项目概述

A 股量化选股桌面应用。**v4.1 插件化架构**：平台骨架独立运行，功能模块以插件形式挂载，含 AI 助手、设置面板、数据管道、伴侣面板。单插件崩溃不影响全局。
Flask 后端 (可选 API 桥) + PyQt5 桌面端 + SQLite 双库架构。
桌面端入口: `desktop_app.py` (启动器, ~30行)，平台壳: `frontend/platform/platform_shell.py`。

### 核心功能
- 三大指数实时行情 + K 线图 (MA5/10/20/60 + MAVOL5, MACD/RSI, 十字光标+信息卡片)
- 多因子选股 Top 20 (43 因子 + DSL 条件引擎, 外置 JSON 评分卡)
- 筹码分布计算 (获利比例/平均成本/集中度, JS 引擎本地计算)
- 周K线自动聚合 (从日线 SQL 窗口函数生成)
- 数据中心面板 (表浏览 + 股票分层双模式, 线程安全, 表头排序)
- 内置日志终端 (stdout/stderr 重定向, 暗色等宽字体)
- 全量数据自动维护 (Task Scheduler 每日 18:00 触发)

## 数据库架构

### kline.db (主库 — 持久化数据)

kline_daily 按年份拆分为 27 张分年表, 通过 UNION ALL 视图兼容旧查询。

| 表 | 行数 | 说明 |
|------|------|------|
| kline_2000~kline_2026 | 27 张 x ~126K/年 | 分年 K 线表 (含 turnover 列) |
| kline_daily (视图) | 3,411,365 | UNION ALL 全部 27 张分年表 |
| kline_weekly | 10,379 | 周K线 (从日线聚合) |
| stock_list | 5,209 | 股票名录 |
| chip_distribution | 26,244 | 筹码分布 |
| north_flow | 2,706 | 北向资金日级净流入 |
| lhb_stock | 1,093 | 龙虎榜个股统计 |
| high_low | 502 | 创新高新低 |
| limit_up | 47 | 涨停股池 |
| market_daily | 881 | 市场日线 |

### stock_cache.db (缓存库 — 仅实时快照)
- stock_spot 沪深A股实时行情 (含PE/PB/市值)

## 启动方式

```bash
# 桌面端一键启动 (纯本地, 无需 Flask)
python desktop_app.py

# Flask API 服务器 (可选, 桌面端 v4.0 已不依赖)
# python run_server.py
```

## 核心架构

```
PyQt5 Desktop (desktop_app.py)  --  v4.0 插件架构, 纯本地, 零 HTTP
  +-- QHBoxLayout (全局)
  |   +-- 左侧 72px 竖排导航 (market/picks/holdings/dc)
  |   +-- 右侧主区域
  |       +-- 顶栏: 品牌 + 搜索 + 设置 ⚙ + AI助手 ⭐ + 日志按钮 + 在线状态
  |       +-- QSplitter: 左面板 QStackedWidget (4页) + 右面板 KlineWidget
  |       +-- 状态栏: 指标切换 + 股票名
  |       +-- LogWindow (切换显示, stdout/stderr 重定向)
  +-- LocalWorker (QThread) -- 唯一异步线程
        |  直调本地函数
        +-- get_kline_data() + enrich_kline()  --> K线图 (8ms)
        +-- FactorScorer.score_batch()        --> 选股面板
        +-- cyq 查询                           --> 筹码数据
              |
        SQLite 双库 (kline.db + stock_cache.db)
```

Flask API (backend/app.py, 26 路由) 仅作为外部接口保留，桌面端不再依赖。

## API 路由 (Flask 端, 26 个)

| 路由 | 说明 |
|------|------|
| GET /api/kline?code=X&days=180 | K线数据 |
| GET /api/kline/weekly?code=X&days=52 | 周K线 |
| GET /api/picks | 选股 Top20 |
| GET /api/cyq?code=X | 筹码分布 |
| GET /api/cyq/refresh?code=X | 刷新筹码缓存 |
| GET /api/market | 三大指数实时行情 |
| GET /api/market/overview | 市场概览 |
| GET /api/market/sectors | 板块行情 |
| GET /api/market/north-flow | 北向资金 |
| GET /api/market/lhb | 龙虎榜 |
| GET /api/market/limit-up | 涨停池 |
| GET /api/market/high-low | 创新高新低 |
| GET /api/holdings | 持仓列表 |
| GET /api/holdings/summary | 持仓汇总 |
| GET /api/stock/list | 股票名录 |
| GET /api/stock/search?q=X | 模糊搜索 |
| GET /api/stock/stats | 数据库统计 |
| GET /api/stock/delisted | 退市股票 |
| GET /api/stock/update-logs | 更新日志 |
| GET /api/stock/klines-by-year?code=X | 分年K线 |
| GET /db/monitor | 数据库监控 |
| GET /db/tables | 表结构 |
| GET /db/table/{tbl} | 分页查询 |
| GET /db/dc/stock-layers?code=X | 股票分层 |
| GET /diagnose_akshare | AKShare 连通性诊断 |
| GET / | 静态首页 |

桌面端 v4.0 不依赖任何 HTTP 路由。

## 当前状态 (2026-07-21 更新)

- [x] 数据库重构: 历史数据全进 kline.db, stock_cache.db 仅存实时快照
- [x] 按年份分区: kline_daily 拆为 27 张分年表
- [x] 换手率入库: turnover 列加至所有分年表
- [x] K线渲染重构: 纯 QPainter 原生绘制, 60fps+
- [x] 多因子选股: 43因子 + DSL 条件引擎, 外置 JSON 评分卡
- [x] 筹码分布: JS 引擎本地计算 (py_mini_racer)
- [x] 自动维护: daily_maintenance.py, 18:00 触发
- [x] **全局主题升级**: Caffeine → 暗色 (#0D1117/#161B22/#D4A574), 6 文件同步
- [x] **K线本地化**: 桌面端 K线/评分/筹码全部直调本地, 零 HTTP 依赖, 8ms 出图
- [x] **日志终端**: LogStream/LogWindow stdout/stderr 重定向
- [x] **dc_panel 优化**: 线程安全、表头排序、底部统计栏
- [x] **UI 字号上调**: 全局 13px 基准, 各组件等比放大
- [x] **P0 bug 修复**: diagnose_akshare import 缺失
- [x] **死代码清理**: 右侧 dc_page + 5 死方法、matplotlib/pyqtgraph K线旧代码

## 待办

1. 分钟K线扩展 — 待创建 kline_minute 表
2. Tick 数据 — 腾讯 stock_zh_a_tick_tx_js() 可用, 待建表
3. [x] 持仓面板 — 已实现（HoldingsPanel, 摘要卡片+明细表格）
4. [x] 评分引擎统一 — Flask API 端已使用 FactorScorer
5. [x] data_lhb.py 集成 — 龙虎榜详情已集成到 daily_maintenance.py 和 app.py
6. [x] K线旧代码清理 — matplotlib/pyqtgraph 旧文件已移除
7. [x] 全局主题升级 — Caffeine → 暗色, 6 文件同步
8. [x] K线本地化 — 桌面端零 HTTP 依赖
9. [x] 日志终端 — LogStream/LogWindow 实现
10. 持仓管理 — 对接数据库持久化 (当前 DUMMY_HOLDS)
11. 缓存库 schema 集中管理
12. 安装包分发

## 重要约定

- data_manager.py 写入分年表: INSERT INTO kline_{year} (非 kline_daily)
- 东财 push2/push2his API 在 Python 中全部被墙 (OpenSSL 指纹), 用 Sina API 替代
- JS 引擎: py_mini_racer.MiniRacer 执行 cyq_calculator.js
- 筹码分布: ak_get_cyq_chip_data(code, days=1250, window=250) 滑动窗口

## 关键文件速查

### 平台核心 (v4.0)

| 文件 | 说明 |
|------|------|
| desktop_app.py | 启动入口 (~30行), 不 import 任何 panel |
| frontend/platform/platform_shell.py | 平台骨架 QMainWindow (~200行), 顶栏+导航+双栈+状态栏+水印 |
| frontend/platform/plugin_base.py | IPlugin 接口 + PlatformServices + PlatformBus 信号总线 |
| frontend/platform/plugin_manager.py | 插件发现/注册/激活/ErrorBoundary 错误隔离 |
| frontend/platform/theme.py | 全局 STYLE 样式表 + COLORS 配色 + `build_style()` + `fs()` |
| frontend/platform/log_window.py | LogStream/LogWindow 日志终端 |
| frontend/platform/local_worker.py | 统一后台线程 QThread |
| frontend/plugins/settings/config.py | `load_settings()` / `save_settings()` → `backend/configs/settings.json` |
| backend/configs/settings.json | `font_size` + `agent{api_base, api_key, model}` |

### 插件 (v4.0)

| 文件 | 区域 | 说明 |
|------|------|------|
| frontend/plugins/search/plugin.py | TOPBAR | 搜索框 |
| frontend/plugins/settings/plugin.py | TOPBAR | 设置面板 (字体+AI配置) |
| frontend/plugins/agent/plugin.py | TOPBAR | AI助手浮动聊天窗 |
| frontend/plugins/market/plugin.py | LEFT | 市场面板 |
| frontend/plugins/picks/plugin.py | LEFT | 选股面板 |
| frontend/plugins/holdings/plugin.py | LEFT | 持仓面板 |
| frontend/plugins/datapipeline/plugin.py | LEFT | 数据管道面板 |
| frontend/plugins/datacenter/plugin.py | LEFT | 数据中心面板 |
| frontend/plugins/kline/plugin.py | RIGHT | K线图 + 指标切换 |
| frontend/plugins/plugins.json | -- | 导航顺序 + 默认激活 |

### 后端

| 文件 | 说明 |
|------|------|
| backend/data_manager.py | SQLite 写操作 + cache_cyq_chip_data + build_weekly_kline |
| backend/akshare_source.py | 数据源封装 + ak_get_cyq_chip_data + diagnose_akshare |
| frontend/plugins/kline/widget.py | K线 QPainter 绘图组件 (被 kline 插件引用) |
| frontend/cyq_calculator.js | 筹码分布 JS 引擎 |