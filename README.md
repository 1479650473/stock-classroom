<p align="center">
  <h1 align="center">📈 stock-classroom</h1>
  <p align="center"><b>A股量化教室</b> — 桌面端量化选股 & 模拟交易系统</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v4.2.0-3fb950" alt="version">
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
| 🔍 **多因子选股** | 43因子 DSL 条件引擎，Top 20 推荐 |
| 💰 **模拟交易** | **完整交易系统 (v4.2)**: 账户/下单/撮合/持仓/T+1风控/费率 |
| 🤖 **AI 自主交易** | **6工具 function calling (v4.2)**: 查行情→分析→下单全自动 |
| 📈 **K线图表** | QPainter 原生 60fps 渲染，MACD/RSI/BOLL 指标 |
| 🎯 **筹码分布** | JS 引擎本地计算，获利比例/平均成本/集中度 |
| 📦 **持仓管理** | 模拟持仓面板，摘要卡片 + 明细表格 |
| 🔄 **数据管道** | 11步一键更新: K线/实时行情/板块/北向/涨停板/龙虎榜 |
| 🗄 **数据中心** | SQLite 三库浏览，表行数/列清单/日期范围 |
| 🤖 **AI 助手** | 浮动聊天窗，DeepSeek V4/智谱 GLM-4/Kimi K2.6 |
| ⚙ **设置中心** | 字体 (19-23px) + 窗口大小 (3档) + AI 供应商预设 + 测试连接 |
| 📝 **日志终端** | 内置 stdout/stderr 重定向，暗色终端 |

## 🏗 架构

**v4.x 插件化架构** — 平台骨架独立运行，11 个功能插件挂载。单插件崩溃不影响全局。

```
Platform Shell
  └─ PluginManager → 发现 / 注册 / 激活 / ErrorBoundary
      └─ 11 插件: search / settings / agent / market / picks /
                  holdings / trade / datapipeline / datacenter / trainer / kline
```

插件间通过 `PlatformBus` 信号总线通信。支持**伴侣面板**和 **AI 工具调用**。

## 🚀 快速开始

```bash
git clone https://github.com/1479650473/stock-classroom.git
cd stock-classroom
pip install -r requirements.txt
python desktop_app.py
```

## 💬 AI 助手配置

1. 启动后点击顶栏 ⚙ → **AI** 标签页
2. 选择供应商 (DeepSeek/智谱/Kimi)
3. 填入 API Key → 测试连接 → 应用
4. 点击 ⭐ 打开聊天窗
5. **v4.2 新功能**: 直接说"帮我买入100股平安银行"，AI 自动查价→下单

| 供应商 | 默认模型 | 获取 Key |
|--------|---------|----------|
| DeepSeek V4 Pro | `deepseek-v4-pro` | [platform.deepseek.com](https://platform.deepseek.com) |
| 智谱 GLM-4 Flash | `glm-4-flash` | [bigmodel.cn](https://bigmodel.cn) |
| Kimi K2.6 | `kimi-k2.6` | [platform.kimi.com](https://platform.kimi.com) |

## 📦 打包

```bat
package\build_desktop.bat
```

## 🎨 UI

暗色方案: `#0D1117` / `#161B22` / `#D4A574` (金)  
字体: 19-23px (dp 自适应缩放)，窗口: 1980×1280 (大) / 1550×950 (中) / 1400×850 (小)

## 📄 文档

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计、插件系统、目录结构 |
| [TECH_MANUAL.md](docs/TECH_MANUAL.md) | 技术手册、交易引擎、AI 工具、数据库 |
| [SESSION_PROMPT.md](docs/SESSION_PROMPT.md) | AI 对话提示词、API 路由 |

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| GUI | PyQt5, QPainter 60fps+ |
| 后端 | Flask (可选), 26 路由 |
| 数据库 | SQLite × 3 (kline.db + stock_cache.db + sim_trade.db) |
| 数据源 | AKShare / Sina API |
| 模拟交易 | 自研 TradeEngine (50项测试) |
| LLM | openai SDK, 6-tool function calling |

## 📝 版本

| 版本 | 日期 | 要点 |
|------|------|------|
| v4.2.0 | 2026-07-27 | 模拟交易系统、AI Agent 工具调用、dp缩放、窗口大小设置 |
| v4.1.0 | 2026-07-24 | AI Agent 插件、设置面板重构、供应商预设 |
| v4.0 | 2026-07-23 | 插件化架构、伴侣面板、数据管道 |

---

<p align="center">
  <sub>develop by siyuan-chen & xiaoguang</sub>
</p>
