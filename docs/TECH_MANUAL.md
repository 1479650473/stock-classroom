# 叶瞬光量化选股系统 — 技术手册

> 项目路径: `D:\小光工作区\projects\stock-classroom`
> 版本: v3.2 | 最后更新: 2026-07-21
> 主题: YeLight 暗色 (#0D1117 / #161B22 / #D4A574)

---

## 一、项目概述

A 股量化选股桌面应用。后端 Flask API (26 路由) + 前端 PyQt5 桌面主程序 + SQLite 双库持久化。
桌面端纯本地运行，零 HTTP 依赖，数据通过 AKShare / Sina API 在线获取。
桌面端入口: `run_desktop.py`，Flask 入口: `run_server.py`。

### 核心功能

- 三大指数实时行情 + K 线图 (QPainter 原生绘制, MA5/10/20/60 + MAVOL5, MACD/RSI)
- 多因子选股 Top 20 (43 因子 + DSL 条件引擎, 外置 JSON 评分卡)
- 筹码分布计算 (获利比例/平均成本/集中度, JS 引擎本地计算)
- 周K线自动聚合 (从日线 SQL 窗口函数生成)
- 数据中心面板 (表浏览 + 股票分层双模式, 线程安全)
- 内置日志终端 (stdout/stderr 重定向, 暗色等宽字体)
- 全量数据自动维护 (Task Scheduler 每日 18:00 触发)
- YeLight 暗色主题全局 UI

---

## 二、UI 架构

### 2.1 整体结构

基于 **PyQt5** 框架，入口 `desktop_app.py` (QMainWindow)。布局采用固定侧边栏 + 右侧内容区:

```
QMainWindow (DesktopApp)
  +-- QHBoxLayout (全局)
      +-- 左侧导航栏 (72px 固定宽, 竖排 QVBoxLayout)
      |   +-- 市场行情 (market)
      |   +-- 选股 (picks)
      |   +-- 持仓 (holdings)
      |   +-- 数据 (dc)
      |   +-- stretch
      |   +-- 刷新按钮
      +-- 右侧主区域 (QSplitter 水平分割)
          +-- 顶栏: 品牌 "YeLight 量化选股" + 搜索框 + 日志按钮 + 在线状态
          +-- 左面板: QStackedWidget (4 页)
          |   +-- 市场行情 (MarketPanel)
          |   +-- AI选股 (PicksPanel)
          |   +-- 模拟持仓 (HoldingsPanel)
          |   +-- 数据中心 (DCPanel)
          +-- 右面板: KlineWidget (K线图, 始终显示)
          +-- 状态栏: K线指标切换 + 股票名
```

左侧 72px 竖排导航栏，不再使用 QListWidget。右侧固定为 K 线图，左侧通过 QStackedWidget 切换面板，不再有右侧的 dc_page 内嵌表格。

### 2.2 UI 组件技术

| 组件 | 文件 | 技术栈 | 说明 |
|------|------|--------|------|
| K线图 | frontend/kline_widget.py | QPainter 原生绘制 | 60fps+, 零外部依赖, 纯本地数据 |
| 市场面板 | frontend/panels/market_panel.py | QWidget + QTableWidget | 指数卡片 + 板块按钮, hover 高亮 |
| 选股面板 | frontend/panels/picks_panel.py | QWidget + QTableWidget | 因子评分分解, 总分三级 badge |
| 数据中心 | frontend/panels/dc_panel.py | QTreeWidget + QStackedWidget | 表浏览/股票分层双模式, 线程安全 |
| 持仓面板 | frontend/panels/holdings_panel.py | QWidget + QTableWidget | 摘要卡片 + 持仓明细 |
| 本地加载 | frontend/panels/local_worker.py | QThread | 后台数据加载 (评分/K线/筹码) |
| 日志终端 | desktop_app.py (LogStream/LogWindow) | QTextEdit + signal | stdout/stderr 重定向, 暗色等宽 |

### 2.3 异步数据加载

统一使用 **LocalWorker** (QThread) 加载本地数据:

- **LocalWorker**: 桌面端唯一异步线程，通过信号发射 `result(tag, data)`。K 线加载、评分计算、筹码查询均经此通道
- **ApiThread** (遗留): 仅保留于代码中，桌面端 v3.2 起不再使用 HTTP API

桌面端纯本地运行策略:
- K 线数据: LocalWorker 直接调用 `get_kline_data()` + `enrich_kline()`，不经过 Flask API，8ms 出图
- 评分计算: LocalWorker 直接调用 `FactorScorer.score_batch()`，不走 HTTP
- 筹码数据: 如需刷新则直接调用 JS 引擎本地计算

### 2.4 日志终端

桌面端内置日志终端 (LogStream + LogWindow):

- `LogStream(QObject)`: 继承 QObject，重写 `write()` / `flush()`，通过 pyqtSignal `new_line` 发射内容
- `LogWindow(QWidget)`: QTextEdit 容器，接收 new_line 信号追加显示，支持自动滚底、清空按钮、行数统计
- 顶栏右侧 "日志" 按钮 toggle 显示/隐藏终端窗口
- 启动时自动将 sys.stdout / sys.stderr 重定向到 LogStream 实例

### 2.5 全局样式

在 `desktop_app.py` 中以 STYLE 字符串全局定义，应用为 QMainWindow 样式表。

核心配色 (YeLight 暗色):

| 元素 | 色值 | 说明 |
|------|------|------|
| 底色 | `#0D1117` | 最深层背景 |
| 面板/卡片 | `#161B22` | 面板底色 |
| 边框 | `#21262D` | 边框/分割线 |
| 主文字 | `#C9D1D9` | 高对比白 |
| 辅助文字 | `#8B949E` | 灰色 |
| 强调色 | `#D4A574` | 暖金 (选中/高亮/品牌) |
| 选中背景 | `#1A2332` | 导航选中底色 |
| 次强调 | `#1C2128` | hover 背景 |
| 涨 (A股红) | `#E54D2E` | 上涨/阳线 |
| 跌 (A股绿) | `#3FB950` | 下跌/阴线 |
| 均线5 | `#FFA726` | MA5 橙色 |
| 均线10 | `#FDBF6E` | MA10/DEA 暖黄 |
| 均线20 | `#CE93D8` | MA20 紫色 |
| 均线60 | `#64B5F6` | MA60 蓝色 |
| DIF | `#FF6B6B` | MACD DIF |
| MACD柱 | `#E54D2E` / `#3FB950` | MACD 红涨绿跌 |

全局字号: 基准 13px，导航 14px，表头/标签 12px，K线坐标轴 9pt，日志终端 11px。

含完整 ScrollBar、Tooltip、QHeaderView、QLineEdit、QCheckBox、QComboBox 等控件全面样式覆盖。

---

## 三、K 线图 (QPainter 原生绘制)

### 3.1 技术选型演进

组件位于 `frontend/kline_widget.py` (v3.2):

| 版本 | 引擎 | 帧率 | 状态 |
|------|------|------|------|
| v2.8 | matplotlib (FigureCanvasQTAgg) | ~3fps | 已移除 |
| v3.0 | pyqtgraph | — | 已移除 |
| v3.1+ | **QPainter (当前)** | **60fps+** | 使用中 |

### 3.2 渲染架构

单次 paintEvent 内完成全图绘制:

```
paintEvent()
  +-- _draw_price()  -- K线蜡烛 + MA5/10/20/60 + Y轴标注
  +-- _draw_vol()    -- 成交量柱 (红涨绿跌) + MAVOL5 + Y轴
  +-- _draw_ind()    -- 副图: MACD (DIF/DEA/柱) 或 RSI14 (30/50/70线)
  +-- _draw_dates()  -- 底部日期标签
  +-- _draw_title()  -- 顶部标题栏: 代码 | 名称 | 总K线数 | 最新价 | 涨跌幅
  +-- _draw_cross()  -- 十字光标 + 信息卡片 (日期/O/H/L/C/成交量/指标值)
```

### 3.3 配色常量

| 常量 | 色值 | 用途 |
|------|------|------|
| `_BG` | `#0D1117` | 画布底色 |
| `_UP` | `#E54D2E` | 阳线 (收盘≥开盘) |
| `_DOWN` | `#3FB950` | 阴线 (收盘<开盘) |
| `_ACCENT` | `#D4A574` | 十字光标/标题代码/选中高亮 |
| `_MA5` | `#FFA726` | MA5 均线 |
| `_MA10` | `#FDBF6E` | MA10 / DEA |
| `_MA20` | `#CE93D8` | MA20 |
| `_MA60` | `#64B5F6` | MA60 |
| `_DIF` | `#FF6B6B` | MACD DIF 线 |
| `_GRID` | `#1C2128` | 网格线 |
| `_TEXT` | `#C9D1D9` | 主文字 |
| `_SUBTEXT` | `#8B949E` | 次文字/坐标标注 |
| `_VOL_UP` | `#E54D2E` | 成交量阳柱 |
| `_VOL_DOWN` | `#3FB950` | 成交量阴柱 |
| `_CROSS` | `#D4A574` | 十字光标线 |

### 3.4 交互机制

| 交互 | 事件 | 行为 |
|------|------|------|
| 缩放 | wheelEvent | 以鼠标位置为中心, 缩放比 3/4 (放大) / 4/3 (缩小), 范围 10~全量K线 |
| 平移 | mousePressEvent + mouseMoveEvent | 左键拖动, 记录起始 visible range 实时更新 _vs/_ve |
| 光标 | mouseMoveEvent | 鼠标 x 映射到 K线索引 _ch, 三面板同步十字线 |
| 信息卡 | mouseMoveEvent | 显示日期/O/H/L/C/成交量/指标值, 位置自适应不越界 |
| 切换 | switch_indicator(t) | MACD <-> RSI 副图切换, 顶部 segmented control 按钮 highlight |

### 3.5 数据流 (v3.2 本地模式)

KlineWidget 通过 `open_kline(code)` 触发数据加载:

1. `LocalWorker` (QThread) 直接调用 `get_kline_data(code)` 从 kline.db 查询日K线
2. 调用 `enrich_kline()` 计算 MA/MACD/RSI 指标 (基于 indicators.py)
3. work 完成后通过 `result("kline", data)` 信号回主线程
4. 主线程 `_on_kline_loaded()` 调用 `kline_widget.set_data(data)`
5. 整体加载耗时约 8ms，零 HTTP 请求

对比旧版 ApiThread → Flask → kline.db 链路，延迟从 ~50ms 降至 ~8ms，且彻底解除桌面端对 Flask 的依赖。

---

## 四、多因子评分引擎

### 4.1 整体架构

`backend/factor_engine/` 完整评分框架:

```
评分卡 JSON (backend/configs/default_scorecard.json)
  -> FactorScorer.score_batch(db_path, top_n=20)
    -> sqlite3 批量查询 (一次性加载候选股60根K线)
      -> FactorCalculator.compute_all() -- 43因子
      -> evaluate_indicator_conditions() -- DSL 26条件
      -> 加权汇总 -> clamp [0, 100]
        -> StockScore (to_api_dict -> JSON)
          -> picks_panel.py (QTableWidget + tooltip)
```

前端通过 LocalWorker (QThread) 异步调用。

### 4.2 文件结构

```
backend/
  factor_engine/
    __init__.py     -- 导出 FactorScorer / FactorCalculator
    models.py       -- 数据模型 (StockScore / FactorGroupResult / ConditionResult 等 dataclass)
    calculator.py   -- 43 个因子计算, @register_factor 装饰器注册
    dsl.py          -- 条件 DSL 求值器 (支持递归 and/or/not)
    config.py       -- 评分卡 JSON 加载/校验
    scorer.py       -- 评分调度主类 (FactorScorer)
    filters.py      -- 硬性过滤 (退市/ST/停牌/次新股)
  configs/
    default_scorecard.json  -- 5 因子组, 26 条条件
```

### 4.3 默认评分卡

5 大因子组, 权重合计 100%, 总分 0~100:

| 因子组 | 权重 | 最大 | 最小 | 指标数 | 条件数 | 评分重点 |
|------|------|------|------|-------|-------|---------|
| 趋势 | 30% | 30 | -20 | 3 | 8 | 均线多头排列, MA60支撑, 趋势方向 |
| 动量 | 25% | 25 | -20 | 2 | 6 | MACD金叉零轴红柱, RSI多空区间 |
| 量价 | 20% | 20 | -15 | 2 | 5 | 放量缩量, 量增价涨 |
| 价格形态 | 15% | 15 | -10 | 2 | 4 | 日涨幅区间, 振幅 |
| 稳定性 | 10% | 10 | -10 | 1 | 3 | 连涨天数, 振幅, 10日涨跌 |

评分规则: 组内各指标得分独立计算后累加 -> 分别 clamp 到各组 [min, max] -> 各组加权得分直接相加 -> 整体 clamp 到 [0, 100]。

### 4.4 DSL 条件引擎

每条条件由 JSON 片段定义, 支持递归组合:

```json
{"type": "gt", "args": ["MA5", "MA10"], "score": 4, "max": 4, "reason": "MA5在MA10之上"}
```

| 类型 | 参数 | 语义 |
|------|------|------|
| gt / gte | 2 | 大于/大于等于 |
| lt / lte | 2 | 小于/小于等于 |
| between | 3 | 闭区间 |
| cross_above | 2 | 上穿 (前一周不满足) |
| cross_below | 2 | 下穿 |
| and / or | N | 逻辑组合 |
| not | 1 | 逻辑非 |
| true | 0 | 恒通过 |

参数字符串从因子值字典查值, 数字直接使用。score 可正可负, max 限制正分上限。

### 4.5 43 个注册因子

| 分类 | 因子 ID | 最少K线 |
|------|---------|---------|
| 基本 | CLOSE / OPEN / HIGH / LOW / VOLUME | 1 |
| 价格 | CHANGE_PCT / AMP | 2 |
| 均线 | MA5 / MA10 / MA20 / MA60 | 5~60 |
| 均线比较 | MA5_GT_MA10 / MA10_GT_MA20 / MA_ALIGN_SCORE | 10~20 |
| 价格vs均线 | CLOSE_GT_MA5 / CLOSE_GT_MA10 / CLOSE_GT_MA20 / CLOSE_GT_MA60 | 5~60 |
| 均线斜率 | MA5_SLOPE | 6 |
| 动量 | MACD_DIF / MACD_DEA / MACD_BAR | 26 |
| MACD信号 | MACD_ABOVE_ZERO / MACD_CROSS / MACD_BAR_RISING | 26~27 |
| 超买超卖 | RSI6 / RSI14 / RSI_OVERSOLD / RSI_OVERBOUGHT | 7~15 |
| 布林 | BOLL_UP / BOLL_MID / BOLL_DN / BOLL_POS | 20 |
| 成交量 | VOL_RATIO_5 / VOL_RATIO_10 / VOL_UP_WITH_PRICE | 5~10 |
| 价格位置 | PRICE_POS_20 / PRICE_POS_60 | 20~60 |
| 价格趋势 | PRICE_CHANGE_5D / PRICE_CHANGE_10D / PRICE_CHANGE_20D | 6~21 |
| 连续 | CONSECUTIVE_UP / CONSECUTIVE_DOWN | 2 |

新增因子: calculator.py 中用 @register_factor("FACTOR_ID") 注册。

### 4.6 性能

| 场景 | 耗时 |
|------|------|
| 批量扫描 4000 只 (含SQL+计算+评分) | 8~9 秒 |
| 单只评分 (60根K线, 43因子, 26条件) | ~2ms |
| 数据库策略 | 200只一批, 避免SQL过长 |

### 4.7 使用方式

```python
from backend.factor_engine import FactorScorer

scorer = FactorScorer()
score = scorer.score_stock("600519", "贵州茅台", klines)
print(scorer.explain(score))

scores = scorer.score_batch("data/kline.db", top_n=20)
for s in scores:
    print(s.code, s.name, s.total_score)

scores = scorer.score_custom_list("data/kline.db", ["600519", "000858"])
```

---

## 五、数据层

### 5.1 文件职责

| 文件 | 职责 |
|------|------|
| app.py | Flask API (26 路由), 数据对外接口 |
| data_manager.py | SQLite DML + AKShare 调度 + 筹码/周线/CLI |
| akshare_source.py | AKShare 调用封装 + API 自文档字典 |
| indicators.py | 技术指标: MACD/RSI/MA/布林带 + enrich_kline() |
| cache_modules.py | 资金流向/涨停板缓存 (扩展) |
| strategy_engine.py | 旧版 6 维评分 (Flask API 端仍在用, 桌面端已用 FactorScorer 替代) |

### 5.2 数据源

| 数据源 | API | 用途 |
|--------|-----|------|
| AKShare 东方财富 | stock_zh_a_spot_em() | 实时行情 (5456只) |
| AKShare 东方财富 | stock_zh_index_spot_em() | 指数行情 |
| Sina API | stock_zh_a_daily() | 历史K线 (含 turnover) |
| AKShare | stock_zt_pool_em() | 涨停池 |
| JS引擎 | cyq_calculator.js | 筹码分布 (py_mini_racer 执行) |

### 5.3 数据流

```
Sina API -> ak_fetch_kline() -> kline_{year} 分年表 (9字段含turnover)
                                   |
                                 kline_daily 视图 (UNION ALL 27张)
                                   |
                                 build_weekly_kline() -> kline_weekly
                                   |
                                 ak_get_cyq_chip_data() -> chip_distribution
```

### 5.4 重要约定

- data_manager.py 写入分年表: INSERT INTO kline_{year} (非 kline_daily 视图)
- 东财 push2/push2his API 在 Python 中全部被墙 (OpenSSL 指纹), 用 Sina API 替代
- JS 引擎: py_mini_racer.MiniRacer 执行 cyq_calculator.js

---

## 六、数据库架构

### 6.1 双库设计

| 数据库 | 大小 | 用途 |
|--------|------|------|
| data/kline.db | ~510 MB | 主库: 所有持久化历史数据 |
| data/stock_cache.db | ~4 MB | 缓存库: 仅实时快照 |

### 6.2 kline.db 主库

kline_daily 按年份拆分为 27 张分年表 (kline_2000~kline_2026), UNION ALL 视图兼容旧查询。

| 表 | 行数 | 说明 |
|------|------|------|
| kline_daily (视图) | 3,411,365 | 日K线 UNION ALL 27张分年表 |
| kline_2000~kline_2026 | 27张 x ~126K/年 | 分年表 (含 turnover 列) |
| kline_weekly | 10,379 | 周K线 (从日线聚合) |
| stock_list | 5,209 | 股票名录 |
| chip_distribution | 26,244 | 筹码分布 |
| north_flow | 2,706 | 北向资金 |
| lhb_stock | 1,093 | 龙虎榜 |
| high_low | 502 | 创新高新低 |
| limit_up | 47 | 涨停池 |
| lhb_daily | — | 龙虎榜详情（东方财富 akshare 导入）|
| market_daily | 881 | 市场日线 |
| fund_flow | 0 | 资金流向 (暂不可用) |
| sector_data | 0 | 板块行情 (交易时段) |
| data_update_log | 2 | 更新日志 |

K线时间范围: 2000-01-04 ~ 至今。每张分年表独立 (code, date) 索引。

### 6.3 stock_cache.db 缓存库

| 表 | 说明 |
|------|------|
| stock_spot | 沪深A股实时行情快照 (含PE/PB/市值) |

仅存储可丢弃的实时快照，减少对 API 的重复请求。

---

## 七、API 路由

| 路由 | 说明 | 数据源 |
|------|------|--------|
| GET /api/market | 三大指数实时行情 | stock_cache.db |
| GET /api/market/overview | 市场概览 | kline.db |
| GET /api/market/sectors | 板块行情 | kline.db |
| GET /api/market/north-flow | 北向资金 | kline.db -> north_flow |
| GET /api/market/lhb | 龙虎榜 | kline.db -> lhb_stock |
| GET /api/market/limit-up | 涨停池 | kline.db -> limit_up |
| GET /api/market/high-low | 创新高新低 | kline.db -> high_low |
| GET /api/picks | 选股 Top 20 | strategy_engine (Flask端) |
| GET /api/kline?code=X&days=180 | K线数据 | kline.db -> kline_daily 视图 |
| GET /api/kline/weekly?code=X&days=52 | 周K线 | kline.db -> kline_weekly |
| GET /api/cyq?code=X | 筹码分布 | kline.db -> chip_distribution |
| GET /api/cyq/refresh?code=X | 刷新筹码缓存 | JS引擎计算后写入 |
| GET /api/holdings | 模拟持仓列表 | DUMMY_HOLDS / 占位数据 |
| GET /api/holdings/summary | 持仓汇总 | 持仓数据聚合 |
| GET /api/stock/list | 股票名录 | kline.db -> stock_list |
| GET /api/stock/search?q=X | 模糊搜索 | kline.db -> stock_list |
| GET /api/stock/stats | 数据库统计 | kline.db |
| GET /api/stock/delisted | 退市股票 | kline.db -> stock_list |
| GET /api/stock/update-logs | 更新日志 | kline.db -> data_update_log |
| GET /api/stock/klines-by-year?code=X | 股票分年K线 | kline_{year} |
| GET /db/monitor | 数据库监控 | kline.db |
| GET /db/tables | 表结构信息 | kline.db |
| GET /db/table/{tbl} | 分页查询表数据 | kline.db |
| GET /db/dc/stock-layers?code=X | 股票K线分层详情 | kline.db |
| GET /diagnose_akshare | AKShare 连通性诊断 | AKShare API |
| GET / | index.html | 静态首页 |

桌面端 v3.2 已不依赖任何 HTTP 路由，直接通过 LocalWorker 访问本地数据库和计算引擎。

---

## 八、每日自动维护

### 8.1 维护流程

`scripts/daily_maintenance.py`，周一~周五 18:00 (Task Scheduler) 执行:

| 步骤 | 内容 | 说明 |
|------|------|------|
| 1 | K线数据更新 | 增量拉取最新日K线, 写入对应分年表 |
| 2 | 周K线聚合 | 从日线实时聚合最新一周 |
| 3 | 缓存刷新 | 北向资金/龙虎榜/创新高/涨停池 |
| 4 | 筹码分布 | 选股列表 Top20 重新计算 |
| 5 | 日志归档 | 清理 30 天前旧日志 |

### 8.2 手动运行

```bash
python scripts/daily_maintenance.py
python scripts/daily_maintenance.py --date 20260710 --catch-up 30
python scripts/daily_maintenance.py --rebuild-weekly
python scripts/daily_maintenance.py --skip-cache --skip-cyq
```

### 8.3 定时任务

```powershell
schtasks.exe /CREATE /XML "scripts\daily_stock_update.xml" /TN "stock-classroom-daily"
```

### 8.4 日志

```
scripts/logs/maintenance_YYYYMMDD.log
```

---

## 九、筹码分布

- 数据来源: Sina API stock_zh_a_daily() (含 turnover/outstanding_share)
- 计算引擎: frontend/cyq_calculator.js (从 AKShare stock_cyq_em 提取)
- 执行器: py_mini_racer.MiniRacer
- 参数: ak_get_cyq_chip_data(code, days=1250, window=250) 滑动窗口
- 缓存: kline.db -> chip_distribution

---

## 十、已知问题与待办

### 已知问题

1. **kline.db 偶尔 WAL 锁** — 并发读写偶发, 需在启动时 wal_checkpoint
2. **缓存库 schema 分散** — fund_flow/limit_up 在 cache_modules.py 散布建表

### v3.2 已修复

| 问题 | 修复方式 |
|------|---------|
| app.py 缺少 diagnose_akshare import | 已添加 `from akshare_source import diagnose_akshare` |
| dc_panel 线程不安全 (工作线程操作 GUI) | GUI 操作从 _work_load() 移到 _on_loaded() 主线程 |
| K线加载依赖 HTTP/Flask API | open_kline 改为 LocalWorker 直调 get_kline_data() + enrich_kline() |
| 右侧 dc_page 死代码 (Page 1 + 5 死方法) | 已清理, right_stack 不再切换 |
| 全局字号偏小 (12px 基准) | 调至 13px 基准, 各组件等比放大 |

### 待办

1. 分钟K线扩展: Sina stock_zh_a_minute() 已验证, 待建 kline_minute 表
2. Tick 数据: 腾讯 stock_zh_a_tick_tx_js() 可用, 待建表
3. [x] 评分引擎统一: Flask 端已使用 FactorScorer（strategy_engine.py 已移除）
4. [x] 持仓面板: 已实现（HoldingsPanel, 摘要卡片+明细表格）
5. [x] 龙虎榜详情: data_lhb.py 已集成到 daily_maintenance.py + app.py
6. [x] K线图迁移: matplotlib/pyqtgraph 旧代码已清理
7. [x] 全局主题升级: Caffeine → YeLight 暗色, 6 文件同步
8. [x] 桌面端纯本地化: 零 HTTP 依赖, K线/评分/筹码全部直调
9. [x] 日志终端: LogStream/LogWindow stdout/stderr 重定向
10. 缓存库 schema 集中管理: 统一 DDL 入口
11. 安装包分发: Electron 壳 vs 重构方案
12. 持仓管理: 对接数据库持久化 (当前为 DUMMY_HOLDS 硬编码)

---