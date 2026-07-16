# 叶瞬光量化选股系统 — 技术手册

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 最后更新: 2026-07-15
> 当前版本: v3.1

---

## 一、项目概述

A 股量化选股桌面应用。**Flask 后端**（数据服务API）+ **PyQt5 桌面端**（UI 主程序）+ **SQLite 本地缓存**。

### 核心功能
- 三大指数实时行情 + K 线图（180天，MA5/10/20，MACD/RSI 切换）
- AI 选股 Top 20 多维评分引擎
- K 线十字光标 + 信息卡片（鼠标悬停显示日期/开/高/低/收/量）
- 成交量 + 成交额双轴面板，滚轮缩放 + 鼠标拖拽平移
- 数据中心面板（数据库浏览器，多表切换）
- 周K线聚合（从日线自动生成）
- 筹码分布计算（获利/成本/集中度）
- 数据中心面板（表浏览 + 股票分层浏览双模式）
- 全量数据自动维护（每日收盘后运行）
- Caffeine 暖色调暗色主题 UI

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────┐
│               PyQt5 Desktop (desktop_app.py)              │
│  ┌────────────────┐  ┌────────────────────────────────┐   │
│  │ 左侧导航:       │  │ 右侧区域 (QStackedWidget):     │   │
│  │ 市场 (Tab0)    │  │ KlineWidget (K线+成交量+指标, QPainter原生渲染)  │   │
│  │ 选股 (Tab1)    │  │ 或数据中心面板                  │   │
│  │ 持仓 (Tab2)    │  │ ↕ QSplitter 分割               │   │
│  │ 数据 (Tab3)    │  │                                │   │
│  └────────────────┘  └────────────────────────────────┘   │
│         │ ApiThread / LocalWorker (异步)                   │
├─────────┼────────────────────────────────────────────────┤
│         │ HTTP (127.0.0.1:5000)                          │
│  ┌──────┴────────────────────────────────────────────┐    │
│  │           Flask API (backend/app.py)               │    │
│  │  /api/market  /api/picks  /api/kline?code=X&days= │    │
│  │  /api/stock/search  /api/stock/list  /api/holdings│    │
│  │  共 12+ 路由                                       │    │
│  └───────────────────────────────────────────────────┘    │
│         │                                                 │
│  ┌──────┴────────────────────────────────────────────┐    │
│  │           数据层 (backend/)                        │    │
│  │  data_manager.py  → SQLite + AKShare 更新         │    │
│  │  indicators.py    → MACD/RSI/MA/布林带            │    │
│  │  strategy_engine.py → AI 选股评分                  │    │
│  │  akshare_source.py → AKShare 数据源封装            │    │
│  └───────────────────────────────────────────────────┘    │
│         │                                                 │
│  ┌──────┴────────────────────────────────────────────┐    │
│  │           数据库 (data/)                           │    │
│  │  kline.db       → 主库: K线/筹码/北向/龙虎榜等   │    │
│  │  stock_cache.db → 实时行情缓存 (stock_spot)        │    │
│  └───────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## 三、目录结构

```
stock-classroom/
├── desktop_app.py         # PyQt5 主程序 (QMainWindow, 全部UI)
├── run_server.py          # Flask 后端启动脚本
├── run_desktop.py         # 桌面端启动脚本
├── start_desktop.bat      # 一键启动 (先server再desktop)
├── pyproject.toml         # 项目配置
├── requirements.txt       # 依赖清单
│
├── backend/               # 数据层
│   ├── app.py             # Flask API (12+ 路由)
│   ├── data_manager.py    # SQLite + AKShare 数据管理
│   ├── indicators.py      # MACD/RSI/MA/布林带计算
│   ├── strategy_engine.py # AI 选股评分引擎
│   ├── akshare_source.py  # AKShare 数据源封装
│   └── cache_modules.py   # 缓存模块
│
├── frontend/              # PyQt5 前端组件
│   ├── kline_chart_v2.py  # K线图组件 (旧版matplotlib, v2.8)
|   +-- kline_widget.py        # K-line chart (QPainter native, 60fps+, v3.1)
│   ├── kline_chart_v3.py  # K线图组件 (旧版pyqtgraph, v3.0)
│   ├── kline_widget.py   # K线图组件 (QPainter原生, 60fps+, v3.1)
│   ├── secret-room.html   # 彩蛋页面
│   ├── cyq_calculator.js  # 筹码分布 JS 计算引擎
│   └── panels/            # 独立面板模块
│       ├── market_panel.py   # 市场/首页面板
│       ├── picks_panel.py    # 选股评分面板
│       ├── holdings_panel.py # 持仓面板 (暂禁用)
│       ├── dc_panel.py       # 数据中心面板
│       └── local_worker.py   # QThread 后台线程
│
├── data/
│   ├── kline.db           # 主库: K线+筹码+北向+龙虎榜等 (509MB)
│   └── stock_cache.db     # 实时行情缓存 (stock_spot)
│
├── docs/
│   ├── README.md           # 文档说明
│   ├── TECH_MANUAL.md      # 本技术手册
│   ├── 选股体系-数据需求梳理.md
│   └── 数据字典/
│       ├── akshare数据字典.md  # AKShare 接口参考
│       └── 索引-按选股流程分类.md
│
├── scripts/               # 数据维护脚本
│   ├── daily_maintenance.py    # 全量数据维护（K线/周线/缓存/筹码）
│   ├── daily_stock_update.xml  # Task Scheduler 配置
│   └── logs/                   # 维护日志
│
└── package/               # PyInstaller 打包
    ├── build.bat
    └── run.py
```

---

## 四、启动方式

### 方式一：一键启动 (推荐)
```bash
start_desktop.bat
```

### 方式二：分步启动
```bash
# 终端1: 启动 Flask 后端
python run_server.py

# 终端2: 启动桌面端
python desktop_app.py
```

### 方式三：命令行
```bash
python desktop_app.py --help
# 或直接双击 desktop_app.py
```

---

## 五、API 接口

| 路由 | 说明 |
|------|------|
| `GET /api/market` | 三大指数实时行情 |
| `GET /api/picks` | AI 选股 Top 20 |
| `GET /api/kline?code=X&days=180` | K 线数据 |
| `GET /api/holdings` | 模拟持仓 |
| `GET /api/stock/stats` | 数据库统计 |
| `GET /api/stock/list` | 股票名录 |
| `GET /api/stock/search?q=X` | 模糊搜索 |
| `GET /api/stock/delisted` | 退市股票 |
| `GET /api/stock/update-logs` | 更新日志 |
| `GET /db/monitor` | 数据库监控 |

---

## 六、数据库

### 6.1 主库 (kline.db)
存储所有持久化历史数据和计算指标。
kline_daily 按年份拆分为 27 张分年表 (kline_2000~kline_2026)，
通过 UNION ALL 视图 kline_daily 兼容旧查询。

| 表 | 行数 | 说明 |
|------|------|------|
| kline_daily (视图) | 3,411,365 | 日K线 UNION ALL 27张分年表 |
| kline_weekly | 10,379 | 周K线 (从日线聚合，含turnover) |
| stock_list | 5,209 | 股票名录 (含状态/最新日期/总天数) |
| chip_distribution | 26,244 | 筹码分布 (获利比例/平均成本/集中度) |
| north_flow | 2,706 | 北向资金日级净流入 |
| lhb_stock | 1,093 | 龙虎榜个股统计 |
| high_low | 502 | 创新高/新低统计 (20/60/120日) |
| limit_up | 47 | 涨停股池 |
| market_daily | 881 | 市场日线数据 |
| data_update_log | 2 | 数据更新日志 |
| fund_flow | 0 | 资金流向 (接口暂不可用) |
| kline_2000~kline_2026 | 27张×~126K/年 | 分年日K线表(含turnover列) |
| sector_data | 0 | 板块行情 |

- **K线时间范围**: 2000-01-04 ~ 2026-07-03
- **索引**: 每张分年表独立(code, date)索引
- **换手率**: turnover 列已加入所有分年表；ak_fetch_kline 返回 9 字段含 hsl
- **数据总量**: ~510 MB

### 6.2 实时缓存 (stock_cache.db)
- **表**: stock_spot — 沪深A股实时行情快照 (含PE/PB/市值)
- 仅存储可丢弃的实时快照数据，减少对 AKShare / 新浪 API 的重复请求
- 历史数据和指标数据均存储在 kline.db

## 七、关键依赖

| 依赖 | 用途 |
|------|------|
| Python 3.14 | 运行环境 (`C:\Python314\python.exe`) |
| PyQt5 | 桌面 GUI 框架 |
| PyQt5 QPainter | K 线图绘制 (原生Qt, 60fps+, 零外部依赖) |
| numpy | 数值计算 |
| Flask | REST API 服务 |
| akshare | 数据源 (东方财富/新浪API) |
| requests | HTTP 请求 |
| PyInstaller | 打包为 .exe |

---

## 八、配色方案

当前使用 **Caffeine 暖色调暗色主题**：

| 元素 | 色值 | 说明 |
|------|------|------|
| 背景 | `#111111` | 最深底色 |
| 卡片/面板 | `#191919` | 面板底色 |
| 边框 | `#201E18` | 暖黑色边框 |
| 主文字 | `#EEEEEE` | 高对比白色 |
| 辅助文字 | `#B4B4B4` | 灰色辅助 |
| 强调色 | `#FFE0C2` | 暖奶油色 |
| 次强调 | `#393028` | 暖咖啡棕 |
| 涨 (A股红) | `#E54D2E` | 红色 = 上涨 |
| 跌 (A股绿) | `#3fb950` | 绿色 = 下跌 |
| 均线 | `#FDBF6E` / `#FFA726` / `#CE93D8` | 暖黄/橙/紫 |

---

## 九、K 线图功能说明

K线图组件 frontend/kline_widget.py (v3.1) - 纯 QPainter 原生渲染：

- 三区联动: K线(蜡烛+MA5/10/20/60) + 成交量(红涨绿跌柱+MAVOL) + MACD/RSI 副图
- 交互方式:
  - 滚轮缩放 (以鼠标位置为中心, 10~总K线数范围限制)
  - 左键按住拖拽平移 (不越界数据范围)
  - 十字光标追踪 (暖金色虚横纵线, 三面板同步)
  - 信息卡片 (日期/O/H/L/C/V, 位置自适应不越界)
- 指标切换: MACD (DIF/DEA/柱) <-> RSI (14日, 含30/50/70线)
- 技术栈: PyQt5 QPainter 原生绘制, 零外部图表依赖
- 性能: 60fps+ (单次 paintEvent 完成全图绘制, 无SignalProxy/InfiniteLine)
- 鼠标事件: mouseMoveEvent/press/release + wheelEvent 原生Qt, 无信号代理
- 历史: v2.8 matplotlib -> v3.0 pyqtgraph -> v3.1 QPainter (当前)

## 十、已知问题

1. **持仓面板暂不可用** — 功能拆解中，占位显示

4. **Flask 依赖** — 桌面端需要 Flask 后端提供数据

---

## 十一、选股引擎

### 11.1 多因子评分框架

由 `backend/factor_engine/` 模块作为评分核心，配合 `backend/configs/` 下的 JSON 评分卡文件，
实现了一套完整可外部化、各维度便于独立修改的多因子评分体系。

前端 `frontend/panels/picks_panel.py` 通过 `LocalWorker` 异步调用 `FactorScorer.score_batch()`
获取评分结果并展示在左侧"选股"面板中。

### 11.2 数据流

```
评分卡 JSON (backend/configs/default_scorecard.json)
        |
        v
FactorScorer.score_batch(db_path, top_n=20, ref_date=None)
        |
        |-- sqlite3 (批量查询，一次性加载所有候选股票的60根K线)
        |
        v
FactorCalculator.compute_all()
        |-- 计算43个因子: MA5/10/20/60, MACD, RSI, BOLL, Volume...
        |
        v
evaluate_indicator_conditions(conditions, factor_values)
        |-- DSL 语意: gt/lt/between/cross_above/and/or/not...
        |
        v
加权汇总 (按因子组 weight 逐层 clamp)
        |
        v
StockScore (to_api_dict() -> JSON)
        |
        v
picks_panel.py (QTableWidget + tooltip 显示)
```

### 11.3 文件结构

```
backend/
  factor_engine/           # 多因子评分框架（核心模块）
    __init__.py            # 导出 FactorScorer 等接口
    models.py              # 数据模型 (StockScore / FactorGroupResult 等)
    calculator.py          # 因子计算层，43 个注册因子
    dsl.py                 # 条件 DSL 求值器
    config.py              # 配置文件加载 / 校验 / 列表
    scorer.py              # 评分调度 (FactorScorer)
  configs/
    default_scorecard.json # 默认评分配置: 5个因子组, 10个指标, 26条条件
frontend/
  panels/
    picks_panel.py         # 选股面板，通过 LocalWorker 调用 FactorScorer
```

### 11.4 默认评分卡

评分卡定义五大因子组，权重合计 100%，总分范围 0~100：

| 因子组 | 权重 | 最大 | 最小 | 指标数 | 条件数 | 说明 |
|------|------|------|------|-------|-------|------|
| 趋势 | 30% | 30 | -20 | 3 | 8 | 均线排列 / MA60支撑 / 趋势方向 |
| 动量 | 25% | 25 | -20 | 2 | 6 | MACD金叉零轴红柱 + RSI多空区间 |
| 量价 | 20% | 20 | -15 | 2 | 5 | 放量缩量 + 量增价涨 |
| 价格形态 | 15% | 15 | -10 | 2 | 4 | 日涨幅区间 + 振幅 |
| 稳定性 | 10% | 10 | -10 | 1 | 3 | 连涨天数 + 振幅 + 10日涨跌 |

**因子组评分规则**：组内各指标得分独立计算后累加，被 clamp 到 [min, max] 区间。
各组原始得分即为加权贡献（权重已体现在 max 中），总分为各组得分之和，clamp 到 [0, 100]。

配置文件位于 `backend/configs/`，默认加载 `default_scorecard.json`。
调用 `list_configs()` 可列出所有可用配置，`FactorScorer(config_path=...)` 切换。

### 11.5 条件 DSL

条件类型支持递归组合（and/or/not），每条条件由 JSON 片段定义：

```json
{"type": "gt", "args": ["MA5", "MA10"], "score": 4, "max": 4, "reason": "MA5在MA10之上"}
```

**语法表**：

| 类型 | 说明 | 参数 | 示例 |
|------|------|------|------|
| `gt` / `gte` | 大于 / 大于等于 | 2 | `["MA5", "MA10"]` |
| `lt` / `lte` | 小于 / 小于等于 | 2 | `["RSI14", 30]` |
| `between` | 闭区间 | 3 | `["VOL_RATIO_5", 1.5, 3.0]` |
| `cross_above` | 上穿（前一周期不满足） | 2 | `["MACD_DIF", "MACD_DEA"]` |
| `cross_below` | 下穿 | 2 | `["MACD_DIF", "MACD_DEA"]` |
| `and` / `or` | 逻辑组合 | N | `[cond1, cond2, ...]` |
| `not` | 逻辑非 | 1 | `[cond]` |
| `true` | 恒通过 | 0 | — |

**参数解析规则**：字符串参数从因子值字典中查值，数字参数直接使用。

**分数机制**：`score` 可以为正或负，正分通过时加、负分通过时减；
不通过时不产生分数。`max` 字段限制正分上限（负分不封顶）。

### 11.6 已注册因子（43 个）

| 分类 | 因子 ID | 最小K线 | 说明 |
|------|---------|---------|------|
| 基本 | CLOSE / OPEN / HIGH / LOW / VOLUME | 1 | 当日原始数据 |
| 价格 | CHANGE_PCT / AMP | 2 | 涨跌幅 / 振幅 |
| 均线 | MA5 / MA10 / MA20 / MA60 | 5~60 | 各周期移动平均 |
| 均线比较 | MA5_GT_MA10 / MA10_GT_MA20 / MA_ALIGN_SCORE | 10~20 | 均线排列判断 |
| 价格 vs 均线 | CLOSE_GT_MA5 / CLOSE_GT_MA10 / CLOSE_GT_MA20 / CLOSE_GT_MA60 | 5~60 | 收盘价位置 |
| 均线斜率 | MA5_SLOPE | 6 | +1向上 / 0走平 / -1向下 |
| 动量 | MACD_DIF / MACD_DEA / MACD_BAR | 26 | MACD 三线 |
| MACD 信号 | MACD_ABOVE_ZERO / MACD_CROSS / MACD_BAR_RISING | 26~27 | 零轴 / 金叉死叉 / 红柱 |
| 超买卖 | RSI6 / RSI14 / RSI_OVERSOLD / RSI_OVERBOUGHT | 7~15 | RSI 判断 |
| 布林 | BOLL_UP / BOLL_MID / BOLL_DN / BOLL_POS | 20 | 布林带位置 |
| 成交量 | VOL_RATIO_5 / VOL_RATIO_10 / VOL_UP_WITH_PRICE | 5~10 | 量比 / 量增价涨 |
| 价格位置 | PRICE_POS_20 / PRICE_POS_60 | 20~60 | 在 N 日区间的位置 |
| 价格趋势 | PRICE_CHANGE_5D / PRICE_CHANGE_10D / PRICE_CHANGE_20D | 6~21 | N 日涨跌幅 |
| 连续 | CONSECUTIVE_UP / CONSECUTIVE_DOWN | 2 | 连涨 / 连跌天数 |

新增因子：在 `calculator.py` 中用 `@register_factor("FACTOR_ID")` 装饰即可注册。

### 11.7 使用方式

```python
from factor_engine import FactorScorer

scorer = FactorScorer()

# 单只评分（需提供K线数据）
score = scorer.score_stock("600519", "贵州茅台", klines)
print(scorer.explain(score))

# 批量评分（直接查数据库，返回前20名）
scores = scorer.score_batch("data/kline.db", top_n=20)
for s in scores:
    print(s.code, s.name, s.total_score, s.to_api_dict())

# 指定股票评分（已选股列表重评）
scores = scorer.score_custom_list("data/kline.db", ["600519", "000858"])
```

### 11.8 评分结果结构

`StockScore.to_api_dict()` 返回 JSON，可直接被前端消费：

```json
{
  "code": "300998",
  "name": "宁波方正",
  "total_score": 76.0,
  "groups": [{
    "id": "trend",
    "name": "趋势因子",
    "weighted_score": 30.0,
    "max_score": 30.0,
    "min_score": -20.0,
    "indicators": [{
      "id": "ma_alignment",
      "name": "均线排列",
      "score": 14.0,
      "conditions": [
        {"type": "gt", "passed": true, "score": 4, "reason": "MA5在MA10之上"},
        {"type": "gt", "passed": true, "score": 4, "reason": "MA10在MA20之上"},
        {"type": "gt", "passed": true, "score": 3, "reason": "收于MA5上方"},
        {"type": "gt", "passed": true, "score": 3, "reason": "收于MA20上方"}
      ]
    }]
  }],
  "factors": {
    "MA5": 1520.5, "MACD_DIF": 0.234, "RSI14": 62.5, ...
  }
}
```

**前端面板 `picks_panel.py`** 使用方式：
- 表格列：排名 / 代码 / 名称 / 价格 / 涨跌幅 / 总分 + 5组因子分
- 行 tooltip：hover 时展示完整的评分明细（每组/每个指标/每条条件）
- 右键：在状态栏显示评分摘要
- 点击行：打开对应 K 线图

### 11.9 性能参数

| 场景 | 耗时 | 说明 |
|------|------|------|
| 批量扫描 4000 只 | 8~9 秒 | 含一次性 SQL 加载 60 根 K 线 |
| 单只评分（60 根） | ~2ms | 全 43 个因子计算 + 26 条条件 |
| 超时保护 | 0 = 不限时 | 传入 `timeout_seconds` 控制 |
| 数据库 | 一次性批量查询 | 200 只一批，避免 SQL 过长 |
| `top_n` | 默认 20 | 控制返回数量，排序后截取 |

### 11.10 扩展方式

| 扩展目标 | 操作 | 影响范围 |
|----------|------|-------
## 十二、每日自动维护

### 12.1 维护脚本

脚本位置: `scripts/daily_maintenance.py`

自动执行以下步骤（周一~周五 18:00）：

| 步骤 | 内容 | 说明 |
|------|------|------|
| 1 | K线数据更新 | 增量拉取最新日K线，写入对应分年表 |
| 2 | 周K线聚合 | 从日线实时聚合最新一周 |
| 3 | 缓存刷新 | 北向资金/龙虎榜/创新高/涨停池 |
| 4 | 筹码分布 | 选股列表 Top20 筹码指标重新计算 |
| 5 | 日志归档 | 清理 30 天前的旧日志 |

### 12.2 手动运行

```bash
# 全量更新
python scripts/daily_maintenance.py

# 只更新K线和周线
python scripts/daily_maintenance.py --skip-cache --skip-cyq

# 全量重建周线（首次使用）
python scripts/daily_maintenance.py --rebuild-weekly

# 指定日期回补
python scripts/daily_maintenance.py --date 20260710 --catch-up 30
```

### 12.3 定时任务

Task Scheduler 配置: `scripts/daily_stock_update.xml`

导入方式：
```powershell
schtasks.exe /CREATE /XML "scripts\daily_stock_update.xml" /TN "stock-classroom-daily"
```

### 12.4 日志查看

```
scripts/logs/maintenance_YYYYMMDD.log
```

每个日志文件包含时间戳、步骤状态、耗时。

---
