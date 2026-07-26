# stock-classroom — 对话提示词

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 版本: v4.2 | 最后更新: 2026-07-27

## 项目概述

A 股量化选股桌面应用。**v4.2 插件化架构**：平台骨架 + 11 个插件，含模拟交易系统、AI Agent 工具调用、UI 自适应缩放。

### 核心功能
- 模拟交易系统: 账户/下单/撮合/持仓/T+1风控/仓位限制
- AI Agent 自主交易: 6工具 function calling，自动查行情→分析→下单
- 三大指数实时行情 + K 线图 (MA5/10/20/60, MACD/RSI, 十字光标)
- 多因子选股 Top 20 (43 因子 DSL 条件引擎)
- 筹码分布 (JS 引擎本地计算)
- 数据管道 11 步更新 + 数据中心

## 数据库架构

### 三库设计 (v4.2)

| 数据库 | 用途 |
|--------|------|
| kline.db | 主库: K线/股票列表/筹码/资金流 ~510MB |
| stock_cache.db | 缓存库: 实时快照 ~4MB |
| sim_trade.db | 模拟交易: 账户/委托/持仓/成交 ~10KB |

## 启动方式

```bash
python desktop_app.py    # 桌面端
# python run_server.py    # Flask API (可选)
```

## 插件清单 (11个)

| ID | 区域 | 说明 |
|----|------|------|
| search | TOPBAR | 搜索框 |
| settings | TOPBAR | 设置 (字体/窗口/AI) |
| agent | TOPBAR | **AI助手 (工具调用 v4.2)** |
| market | LEFT | 市场面板 |
| picks | LEFT | 选股面板 |
| holdings | LEFT | 持仓面板 |
| trade | LEFT | **模拟交易面板 (v4.2)** |
| datapipeline | LEFT | 数据管道 |
| datacenter | LEFT | 数据中心 |
| trainer | LEFT | **回测训练 (占位 v4.2)** |
| kline | RIGHT | K线图 |

## 模拟交易系统

`backend/trade_engine/` — TradeEngine 完整撮合系统
- 费率: 佣金0.03% + 卖出印花税0.05%
- 风控: T+1、仓位30%上限、最小100股
- 前端: `frontend/plugins/trade/panel.py` — 下单面板 + 持仓 + 成交记录 + 5秒价格轮询

## AI Agent 工具调用

6 个工具: `get_account_summary / get_positions / get_stock_price / search_stock / place_order / cancel_order`

Agent 使用独立 "AI账户" (100,000 初始资金)，自主分析→下单，无需确认。

文件: `agent/tools.py` + `agent/chat_worker.py` (QThread 循环调用)

## Theme 缩放系统

`theme.py`: `fs()` (字体) / `dp()` (尺寸) / `dps()` (CSS) — 所有 widget 尺寸随基础字体等比缩放 (×1.62 at 21px)

字体范围: 19-23px。窗口: 1980×1280 (大) / 1550×950 (中) / 1400×850 (小)。

## 配置

`backend/configs/settings.json`:
```json
{"font_size":21,"window_size":"large",
 "agent":{"api_base":"...","api_key":"...","model":"deepseek-v4-pro"}}
```

## 关键文件速查

### 平台
| 文件 | 说明 |
|------|------|
| desktop_app.py | 启动入口 |
| frontend/platform/platform_shell.py | 平台骨架 |
| frontend/platform/theme.py | 主题 + fs()/dp() 缩放 |

### 后端 (v4.2 新增)
| 文件 | 说明 |
|------|------|
| backend/trade_engine/engine.py | TradeEngine 核心 |
| backend/trade_engine/test_shell.py | 50项测试 |
| backend/data_manager.py | 数据管理 |

### 插件 (v4.2 新增)
| 文件 | 说明 |
|------|------|
| frontend/plugins/trade/panel.py | 交易面板 |
| frontend/plugins/agent/tools.py | 6工具定义 + 执行函数 |
| frontend/plugins/agent/chat_worker.py | 工具调用循环 |

## 重要约定

- data_manager.py 写入分年表: INSERT INTO kline_{year}
- 东财 push2 API Python 被墙，用 Sina API 替代
- sim_trade.db 路径与 kline.db 同目录 (data/)
- AI 交易使用独立账户 "AI账户"，与手动交易账户隔离
