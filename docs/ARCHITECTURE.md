# stock-classroom — 架构设计

> 版本: v4.3 | 最后更新: 2026-08-27

---

## 一、设计哲学

**平台是骨架，功能是插件。插件全部崩溃，平台照常运行。**

```
┌──────────────────────────────────────────────────────────┐
│  Platform Shell (platform_shell.py, ~200行, 不可变)       │
│  ┌──────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │ 导航栏    │  │ Left Stack  │  │ Right Stack        │  │
│  │(动态生成) │  │ QStackedWidget│  │ QStackedWidget     │  │
│  │ 📊 市场   │  │             │  │                    │  │
│  │ 🔍 选股   │  │ ErrorBoundary│  │ ErrorBoundary      │  │
│  │ 💰 交易   │  │   Market    │  │    Kline           │  │
│  │ 📦 持仓   │  └─────────────┘  └────────────────────┘  │
│  │ 🔄 数据   │                                          │
│  │ 🗄 数据中心 │  服务总线: status / kline / log            │
│  │ 💹 回测   │  PluginManager: 发现 → 注册 → 隔离        │
│  │ 📈 K线    │  水印: develop by siyuan-chen & xiaoguang │
│  └──────────┘                                          │
└──────────────────────────────────────────────────────────┘
```

## 二、分层架构

```
┌──────────────────────────────────────────┐
│   desktop_app.py  (入口, ~30行)           │  启动入口
├──────────────────────────────────────────┤
│   platform_shell.py  (骨架, ~300行)       │  顶栏 + 导航 + 双栈 + 状态栏 + 日志 + 水印
├──────────────────────────────────────────┤
│   plugin_manager.py  (注册中心)           │  发现 / 注册 / 激活 / 隔离 / ErrorBoundary
├──────────────────────────────────────────┤
│   plugin_base.py  (接口协议)              │  IPlugin / PlatformServices / PlatformBus / PluginRegion
├───────────────────┬──────────────────────┤
│   plugins/ (15)   │   backend/           │
│   overview        │   app.py (Flask)     │
│   research        │   data_manager       │
│   picks           │   factor_engine      │
│   holdings        │   trade_engine       │
│   trade           │   strategy/          │
│   agentops        │     metrics/describe/│
│   market          │     optimize_loop/   │
│   datacenter      │     portfolio_rebal  │
│   datapipeline    │   agent/ (research_loop)│
│   trainer         │   indicators         │
│   flow            │   akshare_source     │
│   kline           │   update_daily.py    │
│   agent/search/   │   ...                │
│   settings        │                      │
└───────────────────┴──────────────────────┘
```

> 右栏 = 可折叠抽屉(platform_shell `_set_drawer`): 平时收起(左插件全屏), 只有打开 K线 或某插件有 companion 才滑出; 无死区空间。

### 各层职责

| 层 | 职责 | 崩溃影响 |
|----|------|---------|
| **Platform Shell** | 窗口框架、导航栏、状态栏、日志、水印 | 全局，必须零崩溃 |
| **Plugin Manager** | 插件发现、注册、激活、错误隔离 | 平台级别，try/except 全覆盖 |
| **Plugin Base** | IPlugin 接口、PlatformServices 数据类、信号总线 | 编译期错误才影响 |
| **Plugins** | 具体功能实现 | 仅自身区域显示错误 fallback |

## 三、插件系统

### 3.1 IPlugin 接口

每个功能模块必须实现以下接口：

```python
class IPlugin(ABC):
    plugin_id: str        # 唯一ID，如 "market"
    name: str            # 显示名，如 "市场"
    icon: str            # emoji 图标，如 "📊"
    region: PluginRegion # LEFT / RIGHT / TOPBAR

    def create_widget() -> QWidget       # 创建功能界面
    def on_activate()                    # tab 被选中时
    def on_deactivate()                  # tab 被切换走时
    def refresh()                        # 刷新数据
    def create_companion_widget() -> QWidget | None  # 可选：右侧伴侣面板
```

### 3.2 PluginRegion

| 区域 | 说明 | 示例 |
|------|------|------|
| `LEFT` | 左侧主面板，在同一 QStackedWidget 中切换 | 市场、选股、交易、持仓、数据中心 |
| `RIGHT` | 右侧面板，在右侧 QStackedWidget 中切换 | K线 |
| `TOPBAR` | 顶栏，始终可见 | 搜索框、设置、AI助手 |

### 3.3 PlatformBus 信号总线

```python
class PlatformBus(QObject):
    open_kline = pyqtSignal(str, str)             # 打开K线 code, name
    status_message = pyqtSignal(str)              # 状态栏消息
    log_message = pyqtSignal(str)                 # 日志输出
    refresh_current = pyqtSignal()                # 刷新当前插件
    data_update_progress = pyqtSignal(str, object) # 数据更新进度
    settings_changed = pyqtSignal(dict)           # 设置变更通知
```

插件间通过 PlatformBus 通信，不直接引用对方。

### 3.5 错误隔离 (ErrorBoundary)

```python
class ErrorBoundary(QWidget):
    """包装插件 widget。创建失败时显示错误提示 + 重试按钮，不传播异常"""
```

- 插件 `create_widget()` 失败 → 显示 "插件加载失败" + 重试按钮
- 插件 `on_activate()` 失败 → 打印 traceback，不影响其他插件
- 插件 `refresh()` 失败 → 同上

## 四、核心机制

### 4.1 插件发现

```python
PluginManager.discover("frontend/plugins/")
    └─ 扫描每个子目录
        └─ 查找 plugin.py
            └─ importlib.import_module("frontend.plugins.{name}.plugin")
                └─ 查找 IPlugin 子类并实例化
```

### 4.2 导航栏顺序

由 `frontend/plugins/plugins.json` 的 `nav_order` 控制。TOPBAR 区域插件不出现在导航中。

```json
{
  "nav_order": ["search", "settings", "agent", "market", "picks", "holdings", "trade", "datapipeline", "datacenter", "trainer", "kline"],
  "default_left": "market",
  "default_right": "kline"
}
```

## 五、目录结构

```
stock-classroom/
├── desktop_app.py              # 启动入口 (~30行)
├── run_server.py               # Flask API 启动
├── AGENTS.md                   # AI 助手上下文
├── README.md                   # GitHub 首页
├── requirements.txt
│
├── backend/
│   ├── app.py                  # Flask API (26路由)
│   ├── data_manager.py         # SQLite 读写 + AKShare 调度
│   ├── akshare_source.py       # AKShare 数据源封装
│   ├── indicators.py           # MACD/RSI/BOLL
│   ├── data_lhb.py             # 龙虎榜导入
│   ├── cache_modules.py        # 资金流/涨停缓存
│   ├── configs/
│   │   ├── default_scorecard.json  # 5组26条件因子评分卡
│   │   └── settings.json           # font_size + window_size + agent
│   ├── factor_engine/          # 多因子评分引擎
│   ├── trade_engine/           # 模拟交易引擎 (v4.2)
│   │   ├── engine.py           # TradeEngine — 账户/下单/撮合/持仓结算
│   │   ├── models.py           # 数据模型
│   │   ├── schema.py           # sim_trade.db 建表
│   │   └── test_shell.py       # 50项端到端测试
│   ├── strategy/               # metrics/describe/optimize_loop/portfolio_rebalance (v4.3)
│   ├── agent/                  # research_loop/llm_client/decision_gate (v4.3)
│   └── update_daily.py         # 每日自动化 (Windows 计划任务 17:00)
│
├── frontend/
│   ├── platform/
│   │   ├── platform_shell.py   # QMainWindow 壳
│   │   ├── plugin_manager.py   # 插件发现/注册/隔离
│   │   ├── plugin_base.py      # IPlugin + PlatformBus + PlatformServices
│   │   ├── theme.py            # 全局主题 + build_style() + fs() + dp()
│   │   ├── log_window.py       # 日志终端
│   │   └── local_worker.py     # 统一 QThread
│   │
│   └── plugins/                # 15 个插件 (nav 分两组: 核心工作流 / 数据工具)
│       ├── plugins.json        # nav_order + nav_groups + default_left/right
│       ├── overview/           # 总览 (LEFT·核心) — v4.3 landing 页
│       ├── research/           # 研究 (LEFT·核心) — 因子研究 + 闭环入口
│       ├── picks/              # 选股 (LEFT·核心)
│       ├── holdings/           # 持仓 (LEFT·核心) — 纸面盘账本 + 精确指标/买卖条件
│       ├── trade/              # 模拟交易 (LEFT·核心) — v4.2
│       │   ├── panel.py        # 账户/下单/持仓/成交记录
│       │   └── styles.py
│       ├── agentops/           # AI操盘 (LEFT·核心) — v4.3 单标的闭环/组合重平衡
│       ├── market/             # 市场 (LEFT·数据)
│       ├── datacenter/         # 数据中心 (LEFT·数据)
│       ├── datapipeline/       # 数据管道 (LEFT·数据)
│       ├── trainer/            # 回测训练 (LEFT·数据) — v4.2 瘦身为占位
│       │   ├── engine.py       # TrainingEngine (保留, 供独立开发)
│       │   └── db.py           # 训练记录 SQLite (保留)
│       ├── flow/               # 流程 (LEFT·数据) — 全流程指挥舱
│       ├── kline/              # K线 (RIGHT·数据) — 右栏抽屉按需滑出
│       ├── search/             # 搜索 (TOPBAR)
│       ├── settings/           # 设置 (TOPBAR)
│       ├── agent/              # AI助手 (TOPBAR) — v4.2 支持工具调用
│       │   ├── tools.py        # 6个交易工具 schema + 执行函数
│       │   ├── chat_window.py  # 浮动聊天窗
│       │   ├── chat_worker.py  # QThread + 工具调用循环
│       │   ├── llm_client.py   # OpenAI 兼容客户端 + chat_with_tools()
│       │   └── config.py       # agent 配置
│
├── data/                       # SQLite 数据库 (gitignored)
│   ├── kline.db
│   ├── fundamental.db
│   ├── stock_cache.db
│   └── sim_trade.db            # 模拟交易账户 (v4.2, 含 account_nav 净值)
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TECH_MANUAL.md
│   ├── SESSION_PROMPT.md
│   └── 数据字典/
│
├── scripts/                    # 运维脚本
└── package/                    # PyInstaller 打包
```

## 六、技术栈决策

| 决策 | 选择 | 理由 |
|------|------|------|
| GUI 框架 | PyQt5 | 已验证稳定 |
| K 线渲染 | QPainter 手绘 | 60fps+，零外部依赖 |
| 数据存储 | SQLite | 单用户场景最优 |
| 数据源 | AKShare / Sina API | A 股免费数据 |
| LLM 客户端 | openai SDK | 兼容 OpenAI/DeepSeek/智谱/Kimi |
| 模拟交易 | 自研 TradeEngine | 完整撮合/持仓/风控，50项测试覆盖 |
| UI 缩放 | dp()/dps() 动态比例 | widget尺寸随字体等比缩放 |

## 七、v4.2 改动总结

| 改动 | 说明 |
|------|------|
| **模拟交易引擎** (新增) | `backend/trade_engine/` — TradeEngine 完整撮合系统，SQLite sim_trade.db，50项测试 |
| **交易插件** (新增) | `frontend/plugins/trade/` — 账户/下单面板/持仓表/成交记录，5秒价格轮询 |
| **AI Agent 工具调用** (新增) | `agent/tools.py` — 6工具 schema + 执行函数，OpenAI function calling 自主交易 |
| **聊天窗重构** | `chat_worker.py` 改为循环调用 LLM + 自动执行工具(最多5轮) |
| **UI 字体放大** | 基准 13px→21px，全部硬编码字号映射到 19-23px，~115处替换 |
| **dp() 缩放系统** | `theme.py` 新增 dp(x)/dps(x) — widget尺寸随字体等比缩放，~120处改动 |
| **窗口大小设置** | Settings "显示"页新增窗口大小选择器(小/中/大, 默认1980×1280) |
| **Trainer 瘦身** | 改名为"回测训练"，510行面板→25行占位，engine.py/db.py 保留 |
| **设置面板** | 窗口 1080×950 → dp自适应，按钮/导航等全部 dp() 缩放 |
| **K线图适配** | 图表边距/文字坐标/交互菜单位置全部 dp() 缩放 |
| **全局 Theme 模板** | Checkbox/ComboBox/ScrollBar 尺寸等比放大 |
| **文档更新** | 全部文档至 v4.2，新增交易引擎/插件/工具调用章节 |

## 八、加新功能指南

```bash
# 1. 创建插件目录
mkdir frontend\plugins\my_feature

# 2. 实现 plugin.py
from frontend.platform.plugin_base import IPlugin, PluginRegion
from PyQt5.QtWidgets import QLabel

class MyPlugin(IPlugin):
    plugin_id = "my_feature"
    name = "新功能"
    icon = "🚀"
    region = PluginRegion.LEFT

    def create_widget(self):
        return QLabel("Hello World")

# 3. 在 plugins.json 的 nav_order 中添加
# 4. 重启应用
```
