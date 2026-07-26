# stock-classroom — 技术手册

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 版本: v4.2 | 最后更新: 2026-07-27
> 主题: 暗色 (#0D1117 / #161B22 / #D4A574)

---

## 一、项目概述

A 股量化选股桌面应用。v4.2 在插件化架构上新增了**模拟交易系统**（独立后端引擎 + 前端交易面板）、**AI Agent 工具调用**（自主下单关联交易）、**UI 自适应缩放**系统（dp 函数 + 19-23px 字体）和**窗口大小设置**。

桌面端入口: `desktop_app.py` (30行)，平台壳: `frontend/platform/platform_shell.py`。

### 核心功能

- 模拟交易系统: 账户管理、市价/限价下单、撮合引擎、持仓管理、成交记录、风控(T+1/仓位30%)
- AI Agent 自主交易: 6工具 function calling，查行情→分析→下单全自动
- K 线图表: QPainter 60fps+，MA/MACD/RSI/BOLL，十字光标+信息卡
- 多因子选股 Top 20: 43因子 DSL 引擎
- 筹码分布: JS 引擎本地计算
- 数据管道: 11步一键更新
- 数据中心: 表浏览 + 股票分层
- 动态主题: dp() 缩放 + fs() 字体 + 窗口大小可选

---

## 二、UI 架构

### 2.1 插件清单 (11个)

| 插件ID | 显示名 | 区域 | 说明 |
|--------|--------|------|------|
| search | 搜索 | TOPBAR | 顶栏搜索框 |
| settings | 设置 | TOPBAR | 字体/窗口/供应商配置 |
| agent | AI助手 | TOPBAR | ⭐ 浮动聊天窗 + 工具调用 |
| market | 市场 | LEFT | 大盘指数 + 板块 |
| picks | 选股 | LEFT | 43因子评分 Top 20 |
| holdings | 持仓 | LEFT | 模拟持仓 |
| trade | 交易 | LEFT | **模拟交易面板 (v4.2)** |
| datapipeline | 数据管道 | LEFT | 11步数据更新 |
| datacenter | 数据中心 | LEFT | 表浏览 + 股票分层 |
| trainer | 回测训练 | LEFT | **占位 (外部独立开发)** |
| kline | K线 | RIGHT | K线图 + 指标切换 |

### 2.2 插件系统核心文件

| 文件 | 职责 |
|------|------|
| `frontend/platform/plugin_base.py` | IPlugin 接口 + PluginRegion + PlatformBus + PlatformServices |
| `frontend/platform/plugin_manager.py` | PluginManager: 发现/注册/激活/ErrorBoundary |
| `frontend/platform/theme.py` | 全局样式 + build_style() + fs()/dp() 缩放函数 |
| `frontend/platform/log_window.py` | LogStream + LogWindow 日志终端 |
| `frontend/platform/local_worker.py` | 统一后台线程 QThread |
| `frontend/platform/platform_shell.py` | 平台骨架 QMainWindow |

### 2.3 动态主题与自适应缩放 (v4.2)

`theme.py` 提供三层缩放机制:

```python
fs(size)    # 字体: fs(13) at base 21 → "21px"
dp(size)    # 尺寸: dp(48) at base 21 → 78 (int)
dps(size)   # 尺寸CSS: dps(10) at base 21 → "16px"
```

所有插件使用 `dp(x)` 代替硬编码像素，widget尺寸自动跟随字体比例 (×1.62 at base 21)。全局 CSS 用 `$fsXX` 占位符自动替换。

**字体范围: 19-23px** (基准 21px), 窗口默认 1980×1280，Settings → 个性显示可切换小/中/大。

### 2.4 窗口大小设置 (v4.2)

`backend/configs/settings.json` 中 `window_size` 字段:
- `small`: 1400×850
- `medium`: 1550×950
- `large`: 1980×1280 (默认)

启动时 platform_shell 读取设置并 setGeometry，设置面板可视切换，重启生效。

---

## 三、模拟交易系统 (v4.2 新增)

### 3.1 架构

```
frontend/plugins/trade/panel.py (UI)
  └─ backend/trade_engine/engine.py (TradeEngine)
       └─ sim_trade.db (SQLite)
```

### 3.2 TradeEngine

| 类别 | 方法 | 说明 |
|------|------|------|
| 账户 | create/get/list/reset | 完整CRUD |
| 下单 | place_order(..., market/limit, current_price) | 市价立即成交，限价挂单冻结 |
| 撤单 | cancel_order(order_id) | 解冻资金/股票 |
| 撮合 | check_orders(account_id, code, price) | 价格到达触发限价单成交 |
| 持仓 | get_positions / update_position_price | 现价更新 + 浮动盈亏 |
| 费率 | 佣金0.03%(万三) + 卖出印花税0.05% | A股标准 |
| 风控 | 仓位30%上限 + T+1禁止当日卖出 | A股规则 |

### 3.3 交易面板 UI

| 组件 | 功能 |
|------|------|
| AccountBar | 账户选择/新建/重置 |
| SummaryCards | 总资产/可用/冻结/市值/浮盈/累计 6指标 |
| StockSearch | 输入代码/名称 250ms防抖搜索，下拉选股 |
| OrderPanel | 买/卖切换，市价/限价，数量，价格，预估成本 |
| PendingOrders | 限价委托待成交 + 撤单按钮 |
| PositionTable | 持仓明细，点击预填卖单+打开K线 |
| TradeHistory | 成交流水 |

### 3.4 价格轮询

QTimer 每5秒: fetch_realtime_prices(持仓+挂单代码) → update_position_price → check_orders → 刷新UI。

---

## 四、AI Agent 工具调用 (v4.2 新增)

### 4.1 架构

```
用户输入 → ChatWindow._send()
  → ChatWorker(QThread).run()
    → loop (max 5 rounds):
      → LLMClient.chat_with_tools(messages, TOOLS)
      → if tool_calls: execute_tool() → append result → loop
      → if content: emit response → display bubble
```

### 4.2 6 个工具

| 工具 | 输入 | 输出 |
|------|------|------|
| `get_account_summary` | — | 总资产/可用/冻结/市值/盈亏 |
| `get_positions` | — | 持仓明细列表 |
| `get_stock_price` | code | 实时现价/涨跌幅 |
| `search_stock` | keyword | 模糊搜索匹配列表 |
| `place_order` | code,name,side,type,price,qty | 成交结果/挂单确认 |
| `cancel_order` | order_id | 撤单确认 |

### 4.3 AI账户

Agent 使用独立的 "AI账户" (100,000 初始资金)，与主账户隔离。启动时自动创建。

### 4.4 文件

| 文件 | 职责 |
|------|------|
| `agent/tools.py` | 6工具 schema + ToolExecutor(TradeEngine绑定) |
| `agent/llm_client.py` | chat_with_tools() — OpenAI function calling |
| `agent/chat_worker.py` | QThread 工具调用循环 (max 5 rounds) |
| `agent/config.py` | system_prompt: 量化交易AI，自主决策 |

---

## 五、K 线图表

### 5.1 QPainter 渲染架构

```
paintEvent()
  +-- _draw_price()  -- K线蜡烛 + MA5/10/20/60 + Y轴标注
  +-- _draw_vol()    -- 成交量柱 (红涨绿跌) + MAVOL5
  +-- _draw_ind()    -- MACD (DIF/DEA/柱) 或 RSI14 (30/50/70线)
  +-- _draw_dates()  -- 日期标签
  +-- _draw_title()  -- 代码 | 名称 | K线数 | 最新价 | 涨跌幅
  +-- _draw_cross()  -- 十字光标 + 信息卡片
```

v4.2: 图表边距(ml/mt/mb) + 文字坐标 + 交互菜单位置全部使用 dp() 等比缩放。

---

## 六、多因子评分引擎

`backend/factor_engine/` — 43因子 DSL 引擎，5组26条件，总分0-100，8-9秒扫4000只。

---

## 七、数据层

### 数据库

| 数据库 | 大小 | 用途 |
|--------|------|------|
| kline.db | ~510 MB | 主库: K线/股票列表/筹码/资金流/龙虎榜 |
| stock_cache.db | ~4 MB | 缓存库: 实时快照 |
| sim_trade.db | ~10 KB | **模拟交易 (v4.2)**: accounts/orders/positions/trades |

### 数据源

AKShare / Sina API。东财 push2 API Python 被墙 (OpenSSL 指纹)，用 Sina API 替代。

---

## 八、已知问题与待办

### 已知问题

1. kline.db 偶发 WAL 锁 — 并发读写
2. 缓存库 schema 分散

### 待办

| 项目 | 状态 |
|------|------|
| 分钟K线扩展 | 待开发 |
| Tick 数据 | 待开发 |
| 持仓面板 (持久化) | 已由 trade 插件替代 |
| 评分引擎统一 | 已完成 |
| 安装包分发 | 待调研 |
| 回测训练营 | 外部独立开发中 |
| 条件单/止损止盈 | 待开发 |
| 资产曲线图表 | 待开发 |
