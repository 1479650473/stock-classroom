<p align="center">
  <h1 align="center">📈 stock-classroom</h1>
  <p align="center"><b>A股量化教室</b> — 桌面端量化选股系统</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v4.1.0-3fb950" alt="version">
  <img src="https://img.shields.io/badge/python-3.14-blue" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform">
  <img src="https://img.shields.io/badge/gui-PyQt5-41CD52" alt="gui">
  <img src="https://img.shields.io/badge/license-MIT-8B949E" alt="license">
</p>

---

## ✨ 功能

| 模块 | 说明 |
|------|------|
| 📊 **市场概览** | 三大指数实时行情 + 板块热度排行 |
| 🔍 **多因子选股** | 43因子 + DSL 条件引擎，外置 JSON 评分卡，Top 20 推荐 |
| 📈 **K线图表** | QPainter 原生 60fps 渲染，MACD / RSI / BOLL 指标切换 |
| 🎯 **筹码分布** | JS 引擎本地计算，获利比例 / 平均成本 / 集中度 |
| 📦 **持仓管理** | 模拟持仓面板，摘要卡片 + 明细表格 |
| 🗄 **数据中心** | SQLite 双库浏览，表行数/列清单/日期范围 |
| 🔄 **数据管道** | 一键拉取日K线 / 实时行情 / 板块 / 北向资金 / 涨停板 / 龙虎榜等 11 步数据 |
| 🤖 **AI 助手** | 浮动聊天窗，支持 DeepSeek V4 / 智谱 GLM-4 / Kimi K2.6 |
| ⚙ **设置中心** | 字体大小调节 + AI 供应商预设 + 测试连接 |
| 📝 **日志终端** | 内置 stdout/stderr 重定向，暗色终端 |

## 🏗 架构

**v4.x 插件化架构** — 平台骨架独立运行，功能以插件形式挂载。单插件崩溃不影响全局。

```
Platform Shell (~200 行，不可变)
  └─ PluginManager → 发现 / 注册 / 激活 / ErrorBoundary
      └─ 9 个插件: search / settings / agent / market / picks /
                    holdings / datapipeline / datacenter / kline
```

插件间通过 `PlatformBus` 信号总线通信，不直接引用。支持 **伴侣面板** 机制（左侧数据 + 右侧详情联动）。

## 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/1479650473/stock-classroom.git
cd stock-classroom

# 2. 安装依赖
pip install -r requirements.txt

# 3. 准备数据库 (放入 data/ 目录)
#    kline.db + stock_cache.db

# 4. 启动桌面端
python desktop_app.py

# (可选) 启动 Flask API
# python run_server.py
```

## 💬 AI 助手配置

1. 启动后点击顶栏 ⚙ → **AI** 标签页
2. 选择供应商（DeepSeek / 智谱 / Kimi）
3. 填入 API Key → 测试连接 → 应用
4. 点击顶栏 ⭐ 打开聊天窗

| 供应商 | 默认模型 | 获取 Key |
|--------|---------|----------|
| DeepSeek V4 Pro | `deepseek-v4-pro` | [platform.deepseek.com](https://platform.deepseek.com) |
| DeepSeek V4 Flash | `deepseek-v4-flash` | 同上 |
| 智谱 GLM-4 Flash | `glm-4-flash` | [bigmodel.cn](https://bigmodel.cn) |
| Kimi K2.6 | `kimi-k2.6` | [platform.kimi.com](https://platform.kimi.com) |

## 📦 打包

```bat
package\build_desktop.bat
```

输出 `dist/StockClassroom/` (~285 MB)，需在 `dist/StockClassroom/data/` 放入 `kline.db` + `stock_cache.db`。

## 📁 项目结构

```
stock-classroom/
├── desktop_app.py            # 启动入口 (~30行)
├── backend/                  # 业务逻辑层
│   ├── data_manager.py       # SQLite CRUD + AKShare 调度
│   ├── akshare_source.py     # ~18 个 API 封装 + 诊断
│   ├── indicators.py         # MACD / RSI / BOLL
│   ├── factor_engine/        # 多因子评分引擎
│   └── configs/              # 评分卡 + 用户设置
├── frontend/
│   ├── platform/             # 平台骨架 (不可变)
│   │   ├── platform_shell.py
│   │   ├── plugin_manager.py
│   │   ├── plugin_base.py    # IPlugin 接口 + PlatformBus
│   │   └── theme.py          # 暗色主题 + 动态字体
│   └── plugins/              # 9 个功能插件
│       ├── agent/            # AI 聊天助手
│       ├── settings/         # 设置面板
│       ├── kline/            # K线图表 (QPainter)
│       └── ...
├── docs/                     # 架构 / 技术手册 / 数据字典
└── package/                  # PyInstaller 打包脚本
```

## 🎨 主题

暗色方案：`#0D1117` (底) / `#161B22` (面板) / `#D4A574` (金)  
支持 4 档字体：小(11) / 中(13) / 大(15) / 特大(17)

## 📄 文档

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计、插件系统、目录结构 |
| [TECH_MANUAL.md](docs/TECH_MANUAL.md) | 技术手册、配色、K线渲染、数据库 |
| [SESSION_PROMPT.md](docs/SESSION_PROMPT.md) | AI 对话提示词、API 路由 |

## 🛠 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| GUI | PyQt5 | QPainter K线渲染 60fps+ |
| 后端 | Flask (可选) | 26 路由 API 桥 |
| 数据库 | SQLite × 2 | kline.db (510MB) + stock_cache.db (4MB) |
| 数据源 | AKShare / Sina API | A股免费数据 |
| LLM | openai SDK | 兼容 DeepSeek / 智谱 / Kimi |
| 打包 | PyInstaller | ~285 MB onedir |

## 📝 版本

| 版本 | 日期 | 要点 |
|------|------|------|
| v4.1.0 | 2026-07-24 | AI Agent 插件、设置面板重构、供应商预设、打包支持 |
| v4.0 | 2026-07-23 | 插件化架构、伴侣面板、数据管道、字体设置 |

---

<p align="center">
  <sub>develop by siyuan-chen & xiaoguang</sub>
</p>
