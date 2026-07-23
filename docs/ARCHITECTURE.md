# stock-classroom — 架构设计

> 版本: v4.0 | 最后更新: 2026-07-23

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
│  │ 📦 持仓   │  │   Market    │  │    Kline           │  │
│  │ 🗄 数据   │  └─────────────┘  └────────────────────┘  │
│  │ 📈 K线    │                                          │
│  └──────────┘  服务总线: status / kline / log            │
│                 PluginManager: 发现 → 注册 → 隔离        │
│                 水印: develop by siyuan-chen & xiaoguang │
└──────────────────────────────────────────────────────────┘
```

## 二、分层架构

```
┌─────────────────────────────────────┐
│   desktop_app.py  (入口, ~30行)     │  启动入口
├─────────────────────────────────────┤
│   platform_shell.py  (骨架, ~200行)  │  顶栏 + 导航 + 双栈 + 状态栏 + 日志 + 水印
├─────────────────────────────────────┤
│   plugin_manager.py  (注册中心)      │  发现 / 注册 / 激活 / 隔离 / ErrorBoundary
├─────────────────────────────────────┤
│   plugin_base.py  (接口协议)         │  IPlugin / PlatformServices / PlatformBus / PluginRegion
├──────────────────┬──────────────────┤
│   plugins/       │   backend/       │
│   search_        │   app.py (Flask) │
│   market         │   data_manager   │
│   picks          │   factor_engine  │
│   holdings       │   indicators     │
│   datacenter     │   akshare_source │
│   kline          │   ...            │
└──────────────────┴──────────────────┘
```

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

    def create_widget() -> QWidget   # 创建功能界面
    def on_activate()                # tab 被选中时
    def on_deactivate()              # tab 被切换走时
    def refresh()                    # 刷新数据
```

### 3.2 PluginRegion

| 区域 | 说明 | 示例 |
|------|------|------|
| `LEFT` | 左侧主面板，在同一 QStackedWidget 中切换 | 市场、选股、持仓、数据中心 |
| `RIGHT` | 右侧面板，在右侧 QStackedWidget 中切换 | K线 |
| `TOPBAR` | 顶栏，始终可见 | 搜索框 |

### 3.3 PlatformBus 信号总线

```python
class PlatformBus(QObject):
    open_kline = pyqtSignal(str, str)       # 打开K线 code, name
    status_message = pyqtSignal(str)        # 状态栏消息
    log_message = pyqtSignal(str)           # 日志输出
    refresh_current = pyqtSignal()          # 刷新当前插件
```

插件间通过 PlatformBus 通信，不直接引用对方。

### 3.4 错误隔离 (ErrorBoundary)

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

由 `frontend/plugins/plugins.json` 的 `nav_order` 控制：

```json
{
  "nav_order": ["search", "market", "picks", "holdings", "datacenter", "kline"],
  "default_left": "market",
  "default_right": "kline"
}
```

### 4.3 生命周期

```
启动 → discover() → register() → inject_services() → build_ui()
                                                      └─ 动态创建导航栏按钮
                                                      └─ 添加 TOPBAR 插件 widget
                                                      └─ activate(default_left)
                                                      └─ activate(default_right)

切换到插件 → activate(plugin_id)
            ├─ deactivate 同区域当前插件
            ├─ ErrorBoundary._build() (首次则 create_widget)
            └─ 放入对应 QStackedWidget

关闭 → shutdown_all() → closeEvent
```

### 4.4 数据加载

统一使用 `LocalWorker (QThread)` 进行后台数据加载：

```
panel.load()
  └─ LocalWorker(func, tag).start()
      └─ run() → func(*args) → result.signal.emit(tag, data)
          └─ main thread: panel._on_data(tag, data)
              └─ update GUI (thread-safe via signal/slot)
```

## 五、目录结构

```
stock-classroom/
├── desktop_app.py              # 启动入口 (~30行)
├── run_server.py               # Flask API 启动 (~7行)
├── start_desktop.bat           # Windows 批处理启动
├── pyproject.toml              # 项目元数据 + 依赖声明
├── requirements.txt            # pip 依赖清单
├── .gitignore
│
├── backend/                    # 业务逻辑层
│   ├── app.py                  # Flask API (26路由)
│   ├── data_manager.py         # SQLite 读写 + AKShare 调度
│   ├── akshare_source.py       # AKShare 数据源封装
│   ├── indicators.py           # MACD/RSI/BOLL 计算
│   ├── data_lhb.py             # 龙虎榜导入
│   ├── cache_modules.py        # 资金流/涨停缓存
│   ├── configs/
│   │   └── default_scorecard.json  # 5组26条件因子评分卡
│   └── factor_engine/          # 多因子评分引擎
│       ├── __init__.py
│       ├── models.py           # StockScore 数据类
│       ├── calculator.py       # 43因子计算
│       ├── dsl.py              # 条件DSL求值器
│       ├── config.py           # 配置加载
│       ├── scorer.py           # FactorScorer 打分器
│       └── filters.py          # 股票过滤器
│
├── frontend/
│   ├── cyq_calculator.js       # 筹码分布 JS 引擎 (backend 引用)
│   │
│   ├── platform/               # 平台骨架 (v4.0 核心)
│   │   ├── platform_shell.py   # QMainWindow 壳 (~200行)
│   │   ├── plugin_manager.py   # 插件发现/注册/隔离/ErrorBoundary
│   │   ├── plugin_base.py      # IPlugin 接口 + PlatformBus + PlatformServices
│   │   ├── theme.py            # 全局 STYLE + COLORS
│   │   ├── log_window.py       # LogStream + LogWindow 日志终端
│   │   └── local_worker.py     # 统一 QThread 后台线程
│   │
│   ├── plugins/                # 插件目录 (每个自包含)
│   │   ├── plugins.json        # 导航顺序 + 默认激活
│   │   ├── search/             # 搜索 (TOPBAR)
│   │   │   └── plugin.py
│   │   ├── market/             # 市场 (LEFT)
│   │   │   ├── plugin.py       # MarketPlugin 包装器
│   │   │   └── panel.py        # MarketPanel 面板代码
│   │   ├── picks/              # 选股 (LEFT)
│   │   │   ├── plugin.py       # PicksPlugin 包装器
│   │   │   └── panel.py        # PicksPanel 面板代码
│   │   ├── holdings/           # 持仓 (LEFT)
│   │   │   ├── plugin.py       # HoldingsPlugin 包装器
│   │   │   └── panel.py        # HoldingsPanel 面板代码
│   │   ├── datacenter/         # 数据中心 (LEFT)
│   │   │   ├── plugin.py       # DataCenterPlugin 包装器
│   │   │   └── panel.py        # DCPanel 面板代码
│   │   └── kline/              # K线 (RIGHT)
│   │       ├── plugin.py       # KlinePlugin 包装器
│   │       └── widget.py       # KlineWidget QPainter 绘图
│   │
│   └── _archive/               # 历史版本存档
│       ├── strategy_engine.py
│       ├── kline_chart_v2.py   # matplotlib K线
│       ├── kline_chart_v3.py   # pyqtgraph K线
│       └── secret-room.html
│
├── data/                       # SQLite 数据库 (gitignored)
│   ├── kline.db
│   └── stock_cache.db
│
├── docs/
│   ├── ARCHITECTURE.md         # 架构设计文档
│   ├── TECH_MANUAL.md          # 技术手册
│   ├── SESSION_PROMPT.md       # AI 对话提示词
│   └── 数据字典/
│
├── scripts/                    # 运维脚本
│   ├── daily_maintenance.py    # 每日全量维护
│   ├── update_daily.bat
│   ├── update_daily.ps1
│   ├── daily_stock_update.xml  # Windows Task Scheduler
│   └── README.md
│
└── package/                    # PyInstaller 打包
    ├── run.py
    └── build.bat
```

## 六、技术栈决策

| 决策 | 选择 | 理由 |
|------|------|------|
| GUI 框架 | PyQt5 | 已验证稳定，将来可换 PySide6 (LGPL，上架友好) |
| Python 版本 | 3.14.3 | 已编译通过，暂不降级 |
| K 线渲染 | QPainter 手绘 | 60fps+，零外部依赖 |
| 数据存储 | SQLite 双库 | 单用户场景最优，将来可换 PostgreSQL |
| 后端框架 | Flask (可选) | 桌面端直连 SQLite，Flask 仅作 API 桥；将来换 FastAPI |
| 数据源 | AKShare | A 股最优免费源，将来可加付费源 (Wind/Tushare Pro) |
| 打包 | PyInstaller | 将来 MSIX 上架 Windows Store |
| 死依赖删除 | matplotlib / numpy / backtesting / scipy | v4.0 从核心依赖移除，仅 numpy 被 pandas 间接依赖 |

## 七、v4.0 改动总结

| 改动 | 文件 | 行数变化 |
|------|------|----------|
| 新增接口层 | `platform/plugin_base.py` | +90 |
| 新增插件管理器 | `platform/plugin_manager.py` | +160 |
| 移动+统一 Worker | `platform/local_worker.py` | 从 panels 移入 |
| 提取日志模块 | `platform/log_window.py` | 从 desktop_app.py 提取 |
| 提取主题模块 | `platform/theme.py` | 从 desktop_app.py 提取 |
| 新建平台壳 | `platform/platform_shell.py` | +210 |
| 6 个插件 | `plugins/*/plugin.py` | 每个 ~40-90 |
| 精简入口 | `desktop_app.py` | 803 → 30 |
| 清理 | 删除 ApiThread, matplotlib, numpy 死代码 | -160 |

## 八、加新功能指南

```bash
# 1. 创建插件目录
mkdir frontend\plugins\my_feature
echo "# My Feature" > frontend\plugins\my_feature\__init__.py

# 2. 实现 plugin.py
# frontend/plugins/my_feature/plugin.py
from frontend.platform.plugin_base import IPlugin, PluginRegion
from PyQt5.QtWidgets import QLabel

class MyPlugin(IPlugin):
    plugin_id = "my_feature"
    name = "新功能"
    icon = "🚀"
    region = PluginRegion.LEFT

    def create_widget(self):
        return QLabel("Hello World")

    def on_activate(self):
        if self._services:
            self._services.status("新功能已激活")

# 3. 在 plugins.json 的 nav_order 中添加
"nav_order": ["search", "market", "picks", "holdings", "datacenter", "my_feature", "kline"]

# 4. 重启，新功能自动出现在导航栏
# 不需要改 platform_shell.py 或 desktop_app.py 任何一行
```

## 九、未来演进方向

```
当前 (v4.0)                      未来
──────────────────────────────────────────────────
PyQt5                          PySide6 (上架商城 LGPL)
Flask 可选 API                 FastAPI (多用户并发 + 自动文档)
SQLite                        PostgreSQL + Redis (服务端)
AKShare 免费源                 付费数据源 (实时行情)
Windows 桌面                  跨平台 (macOS/Linux)
PyInstaller 简单打包            MSIX 签名上架 Windows Store
单用户本地                     多用户 SaaS
```

### 优先级

1. **插件化架构 (v4.0)** ← 已完成
2. **WebSocket 实时推送** ← 下一步
3. **FastAPI 替代 Flask** ← 多用户前完成
4. **PySide6 迁移** ← 上架商城前完成
5. **PostgreSQL 支持** ← 服务端部署前完成
