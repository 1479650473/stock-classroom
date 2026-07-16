# 叶瞬光量化选股系统 — 对话提示词

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 版本: v3.1 | 最后更新: 2026-07-15

## 项目概述

A 股量化选股桌面应用。Flask 后端 + PyQt5 桌面端 + SQLite 双库架构。
当前使用 **Caffeine 暖色调暗色主题**。

### 核心功能
- 三大指数实时行情 + K 线图（MA5/10/20, MACD/RSI, 十字光标）
- AI 多因子选股 Top 20（43 因子 + DSL 条件引擎）
- 筹码分布计算（获利比例/平均成本/集中度）
- 周K线自动聚合（从日线生成）
- 数据中心面板（表浏览 + 股票分层双模式）
- 全量数据自动维护（每日 18:00 Task Scheduler 触发）
- 多因子评分系统（5 因子组，外置 JSON 评分卡）

## 数据库架构

### kline.db（主库 — 持久化数据）

kline_daily 按年份拆分为 27 张分年表，通过 UNION ALL 视图兼容旧查询。

| 表 | 行数 | 说明 |
|------|------|------|
| kline_2000~kline_2026 | 27 张 × ~126K/年 | 分年 K 线表（含 turnover 列） |
| kline_daily (视图) | 3,411,365 | UNION ALL 全部 27 张分年表 |
| kline_weekly | 10,379 | 周K线（从日线聚合） |
| stock_list | 5,209 | 股票名录 |
| chip_distribution | 26,244 | 筹码分布 |
| north_flow | 2,706 | 北向资金日级净流入 |
| lhb_stock | 1,093 | 龙虎榜个股统计 |
| high_low | 502 | 创新高新低 |
| limit_up | 47 | 涨停股池 |
| market_daily | 881 | 市场日线 |

### stock_cache.db（缓存库 — 仅实时快照）
- stock_spot 沪深A股实时行情（含PE/PB/市值）

## 目录结构

```
stock-classroom/
├── desktop_app.py           # PyQt5 主程序
├── run_server.py / run_desktop.py / start_desktop.bat
│
├── backend/
│   ├── app.py               # Flask API (15+ 路由)
│   ├── data_manager.py      # SQLite + AKShare 数据管理层
│   ├── akshare_source.py    # AKShare 数据源封装 (含筹码JS引擎)
│   ├── indicators.py        # MACD/RSI/MA/布林带
│   ├── factor_engine/       # 多因子评分框架 (43因子)
│   ├── configs/             # JSON 评分卡配置
│   └── cache_modules.py     # 缓存模块
│
├── frontend/
│   ├── kline_chart_v2.py    # K线图 (旧版matplotlib, v2.8)
│   ├── kline_widget.py     # K线图 (QPainter原生, 60fps, v3.1)
│   ├── cyq_calculator.js    # 筹码分布 JS 计算引擎
│   ├── secret-room.html     # 彩蛋
│   └── panels/
│       ├── market_panel.py
│       ├── picks_panel.py    # 选股面板 (因子评分展示)
│       ├── dc_panel.py      # 数据中心 (表浏览+股票分层)
│       └── local_worker.py  # QThread 后台线程
│
├── data/
│   ├── kline.db             # 主库 (509MB)
│   └── stock_cache.db       # 缓存库
│
├── docs/
│   ├── TECH_MANUAL.md       # 完整技术手册
│   ├── SESSION_PROMPT.md    # 本文件（对话提示词）
│   └── 选股体系-数据需求梳理.md
│
├── scripts/
│   ├── daily_maintenance.py # 全量数据维护（K线/周线/缓存/筹码）
│   ├── daily_stock_update.xml  # Task Scheduler 配置
│   └── logs/                # 维护日志
│
├── package/                 # PyInstaller 打包
└── docs/数据字典/
    ├── akshare数据字典.md
    └── 索引-按选股流程分类.md
```

## 核心架构

```
PyQt5 Desktop
  ↕ 异步 HTTP (127.0.0.1:5000)
Flask API (backend/app.py)
  ↕
数据层 (data_manager / indicators / factor_engine)
  ↕
Sina API ←→ kline.db (主库)     stock_cache.db (缓存: stock_spot)
    ↑               ↑
  akshare_source    27 张分年表 + kline_weekly + chip_distribution + ...
```

### 数据流

```
Sina API  → ak_fetch_kline()  → kline_{year} 分年表（9字段含turnover）
                                  ↕
                                kline_daily 视图（UNION ALL）
                                  ↕
                                build_weekly_kline() → kline_weekly
                                  ↕
                                ak_get_cyq_chip_data() → chip_distribution
```

## API 路由

| 路由 | 说明 |
|------|------|
| GET /api/kline?code=X&days=180 | K线数据（读取 kline_daily 视图） |
| GET /api/picks | 选股 Top20（多因子评分） |
| GET /api/cyq?code=X | 筹码分布数据 |
| GET /api/cyq/refresh?code=X | 刷新筹码分布缓存 |
| GET /api/cache/sectors | 板块行情 |
| GET /api/cache/north-flow | 北向资金 |
| GET /api/market | 三大指数实时行情 |
| GET /api/stock/list | 股票名录 |
| GET /api/stock/search?q=X | 模糊搜索 |

## 当前状态

- ✅ **数据库重构**: 历史数据全进 kline.db，stock_cache.db 仅存实时快照
- ✅ **按年份分区**: kline_daily 拆为 27 张分年表，UNION ALL 视图兼容
- ✅ **换手率入库**: turnover 列加至所有分年表，ak_fetch_kline 返回 9 字段
- ✅ **周K线**: kline_weekly 表，SQL 窗口函数聚合（日K线→周K线）
- ✅ **DC 面板**: 表浏览模式（27年分年折叠）+ 股票分层浏览模式
- ✅ **自动维护**: daily_maintenance.py，18:00 触发，覆盖K线/周线/缓存/筹码
- ✅ **多因子选股**: 43因子 + DSL 条件引擎，外置 JSON 评分卡
- ✅ **K线渲染重构**: 纯QPainter原生绘制, 60fps+, 零外部图表依赖
- ✅ **评分引擎统一**: factor_engine (43因子+DSL) 取代 strategy_engine, /api/picks 已切换
- ✅ **筹码分布**: 从 Sina API 获取 K 线+换手率，JS 引擎本地计算
- ✅ **cyq-data-loader Skill**: 已安装，codex 可自动触发筹码加载

## 待办/可优化

1. **分钟 K 线扩展** — Sina `stock_zh_a_minute()` 接口已验证可用，待创建 kline_minute 表
2. **Tick 数据** — 腾讯 `stock_zh_a_tick_tx_js()` 可用，待建表
3. **持仓面板** — 当前占位，待实现
4. **分钟K线扩展** — 待创建 kline_minute 表
5. **Tick数据** — 腾讯 stock_zh_a_tick_tx_js() 可用，待建表

## 重要约定

- `data_manager.py` 写入分年表：INSERT INTO kline_{year}（非 kline_daily）
- 东财 push2/push2his API 在 Python 中全部被墙（OpenSSL 指纹），用 Sina API 替代
- Sina API: `ak.stock_zh_a_daily()` 含 turnover/outstanding_share 字段
- JS 引擎: `py_mini_racer.MiniRacer` 执行 cyq_calculator.js
- 筹码分布: ak_get_cyq_chip_data(code, days=1250, window=250) 滑动窗口

## 关键文件速查

| 文件 | 说明 |
|------|------|
| backend/data_manager.py | SQLite 写操作 + cache_cyq_chip_data + build_weekly_kline |
| backend/akshare_source.py | 数据源封装 + ak_get_cyq_chip_data |
| frontend/kline_widget.py | K线图 (QPainter原生, 60fps, v3.1) |
| frontend/panels/dc_panel.py | 数据中心 (QTreeWidget 分组 + QStackedWidget 双模式) |
| frontend/cyq_calculator.js | 筹码分布 JS 引擎（从 AKShare stock_cyq_em 提取） |
| scripts/daily_maintenance.py | 全量维护（每日 18:00 触发） |
