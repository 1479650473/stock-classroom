<p align="center">
  <h1 align="center">📈 stock-classroom</h1>
  <p align="center"><b>A股量化教室</b> — AI-LLM 驱动的 A 股交易策略研究 & 模拟交易系统</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v5.0-3fb950" alt="version">
  <img src="https://img.shields.io/badge/python-3.14-blue" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform">
  <img src="https://img.shields.io/badge/gui-Tauri2+Vue3-41CD52" alt="gui">
  <img src="https://img.shields.io/badge/license-MIT-8B949E" alt="license">
</p>

---

## ✨ 功能

| 模块 | 说明 |
|------|------|
| 🏠 **总览** | Landing 页: AI账户净值卡 / 最近最强策略 / 市场速览 / 主功能入口 / 账户中心 |
| 📊 **市场概览** | 三大指数实时行情 + 板块热度排行 |
| 🔍 **多因子选股** | 43因子 DSL 条件引擎，Top 20 推荐 + 一键模拟买入 |
| 💰 **模拟交易** | 账户/下单/撮合/持仓/T+1风控/费率 + 账户中心(改名/重置/删除) |
| 🤖 **AI 自主交易** | 16工具 function calling，查行情→分析→下单全自动 |
| 🧠 **AI操盘台** | 单标的闭环 / 组合重平衡 (SSE tool-calling 流式) |
| ♻ **策略进化闭环** | 5家族精确指标(α/年化/夏普)→LLM 提新契约→回测→裁决→模拟盘 |
| 📈 **K线图表** | ECharts 渲染，MACD/RSI/BOLL |
| 📦 **持仓管理** | 纸面盘账本: 5策略收益曲线对比/每日持仓/每笔调仓 + 净值曲线 |
| 🔄 **数据管道** | **每日自动更新(Windows计划任务 17:00)**: K线池/基本面/纸面盘/净值快照 |
| 🛡 **卖出门三驱动** | **条件止损(8%)+移动止损(10%/15%激活)+策略卖出**, 无固定止盈, 保护优先于排名 |
| 🔬 **完整生命周期验证** | **verify_full_lifecycle**: 选股→买→持有(带保护)→卖→结算→净值逐日回放 |
| 🧪 **分周期测试** | **cycle_test**: 牛/熊/震荡/全周期分类 + 样本内/样本外(防过拟合) |
| 🔄 **周期策略轮换** | **判断器驱动**: 牛→B反转进攻 / 震荡→F价值Tilt / 熊→C低波动防守, 模拟盘自动切换 |
| 📊 **完整回测指标** | 日期区间+夏普+α/β/γ(信息比率)+收益率+交易频率+胜率+盈亏比+索提诺/Calmar/波动 |
| 📰 **事件驱动池** | AI账户当日涨停+热点板块, **isolated 突发利好·短期观察, 不进长期策略** |
| 🔎 **个股资讯深挖** | 选股剩前8只→豆包搜资讯→**LLM独立主观判断**(前置/后移/保持/剔名) |
| 🗄 **数据中心** | SQLite 多库浏览，表行数/列清单/日期范围 |
| ⚙ **设置中心** | 字体 + 窗口大小 + AI 供应商预设 + AI定时交易卡 |

## 🏗 架构 (v5.0 — 当前主线)

**Web 栈为主开发线**（浏览器开发体验），PyQt5 旧版仍保留但不再发展（见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)）。

```
Tauri Shell (web/src-tauri, frameless, 启动时拉起 stock-api.exe sidecar)
  └─ Vue3 SPA (web/src: views/router/stores/composables)
       └─ Flask API 127.0.0.1:5000 (backend/api/server.py, 12+ blueprints, 统一 envelope)
```

- **后端打包**: `package/stock_api.spec` → 单文件 `stock-api.exe` (PyInstaller, 含 akshare data)
- **前端打包**: `web/src-tauri` → NSIS/MSI 安装包 (bundle.resources 内嵌 stock-api.exe)
- **⚠️ 打包坑**: `frontend/platform/` 是名为 `platform` 的包, **绝不能**把 frontend 加入 PyInstaller pathex (遮蔽 stdlib platform → pandas 崩溃)
- **遗留说明**: PyQt5 旧版已**归档压缩**至 `archive/pyqt5-legacy-2026-09-05.zip`（源文件已移除）。归档前已把 backend 依赖的纯逻辑迁移到 backend：`frontend.plugins.research.worker` → **`backend/paper_worker.py`**，`frontend.plugins.trainer.engine` → **`backend/trainer_engine.py`**，`frontend/cyq_calculator.js` → **`backend/cyq_calculator.js`**。

## 🔄 核心交易循环

**全自动闭环**，含判断器驱动的周期轮换、三驱动卖出门、分周期验证。详见 **`docs/Trading_Loop.md`**。

```
数据引入(行情/基本面) → 多因子复合判断 → regime动态权重 → 周期策略轮换(判断器驱动)
  → 回测(分周期+样本外) → 模拟盘(多策略+轮动) → 每日复盘 → sell三驱动(止损/移动止损/策略卖出)
  → LLM介入(个股深挖+事件驱动) → 净值结算 → 迭代
```

- **卖出门三驱动**: 条件止损(8%) + 移动止损(10%/15%激活) + 策略卖出(排名调出), 无固定止盈(让利润奔跑)。
- **周期轮换**: 牛→B反转进攻 / 震荡→F价值Tilt / 熊→C低波动防守 — 模拟盘自动切换。
- **回测口径**: **日K线回测**(非Tick) — 每日以收盘价成交, 无盘中撮合/涨跌停校验(见 Trading_Loop.md §7-8)。

## 🚀 快速开始 (Web v5.0)

```bash
# 1) 后端 API (127.0.0.1:5000)
C:/Python314/python.exe run_web.py

# 2) 前端 dev (Vite HMR, 5173, 代理 /api → 5000)
cd web && npm run dev

# 3) 桌面壳 (可选, 需 Rust + VS BuildTools)
cd web/src-tauri && cargo tauri dev
```

> PyQt5 旧版入口仍可运行: `python desktop_app.py`（需 PyQt5, 仅维护不发展）

## 📦 打包 (Web)

```bat
rem 1) 后端 sidecar (PyInstaller, 含 akshare data)
python -m PyInstaller --clean --noconfirm package\stock_api.spec --distpath package\dist --workpath package\build_api
rem 2) 前端 + 外壳 (需先 activate VS BuildTools vcvars64)
cd web\src-tauri && cargo tauri build
rem 输出: web\src-tauri\target\release\bundle\{msi,nsis}\StockClassroom_*.exe
```

## 💬 AI 助手配置

1. 启动后点击顶栏 ⚙ → **AI** 标签页
2. 填入 API Key (DeepSeek 等) → 测试连接 → 应用
3. 直接说"帮我买入100股平安银行"，AI 自动查价→下单

| 供应商 | 默认模型 |
|--------|---------|
| DeepSeek V4 | `deepseek-v4-pro` / `deepseek-v4-flash-vision-exp` |
| 智谱 GLM-4 | `glm-4-flash` |
| Kimi K2.6 | `kimi-k2.6` |

## 🎨 UI

暗色方案: `#0B0D11` (bg) / `#14171C` (panel) / `#D4A574` (accent gold) — graphite  
3 主题: graphite / obsidian / ivory

## 📄 文档

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计、插件系统、目录结构（PyQt5 旧版） |
| [TECH_MANUAL.md](docs/TECH_MANUAL.md) | 技术手册、交易引擎、AI 工具、数据库 |
| [SESSION_PROMPT.md](docs/SESSION_PROMPT.md) | AI 对话提示词、API 路由 |
| [RESEARCH_AGENT.md](docs/RESEARCH_AGENT.md) | backend/agent 量化研究代理层：闭环架构/因子库/安全/验证 |
| [TASK_LOG.md](docs/TASK_LOG.md) | 量化研究里程碑：提交序列 + 验证状态 |
| [Trading_Loop.md](docs/Trading_Loop.md) | **核心交易循环权威文档**（三驱动卖出门/回测口径/策略轮换） |

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Tauri 2 + Vue3 + TypeScript + ECharts + Pinia |
| 后端 | Flask (127.0.0.1:5000, 统一 envelope + jobman 线程池/SSE) |
| 数据库 | SQLite × 多库 (kline.db + fundamental.db + stock_cache.db + sim_trade.db + macro.db + agent.db) |
| 数据源 | AKShare / Sina API (三源回退 Sina主/TX/EM + 硬超时) |
| 模拟交易 | 自研 TradeEngine |
| 量化策略 | factor_engine + portfolio_rebalance (SelectionContract) + regime + sell_rules |
| LLM | openai SDK (DeepSeek 等), 16-tool function calling |
| 自动化 | update_daily.py + Windows 计划任务 (项目 venv `.update-venv/`) |

## 📝 版本

| 版本 | 日期 | 要点 |
|------|------|------|
| v5.0 | 2026-08-31 | **Web 栈迁移**: Vue3+Vite+TS+ECharts+Tauri2 + Flask API v2 (blueprints+统一envelope+jobman SSE) + AI操盘台16工具 + 策略进化闭环 + AI定时自主交易 |
| v4.3 | 2026-08-27 | 总览 landing 页 / 策略进化闭环(α·年化·夏普精确指标) / 账户中心 / 净值曲线 / K线右栏抽屉 / 无边框自定义标题栏 / 每日自动更新(17:00计划任务) |
| v4.2.0 | 2026-07-27 | 模拟交易系统、AI Agent 工具调用、dp缩放、窗口大小设置 |
| v4.1.0 | 2026-07-24 | AI Agent 插件、设置面板重构、供应商预设 |
| v4.0 | 2026-07-23 | 插件化架构、伴侣面板、数据管道 |

---

<p align="center">
  <sub>develop by siyuan-chen & xiaoguang</sub>
</p>
