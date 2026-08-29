<p align="center">
  <h1 align="center">📈 stock-classroom</h1>
  <p align="center"><b>A股量化教室</b> — 桌面端量化选股 & 模拟交易系统</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-v4.3-3fb950" alt="version">
  <img src="https://img.shields.io/badge/python-3.14-blue" alt="python">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4" alt="platform">
  <img src="https://img.shields.io/badge/gui-PyQt5-41CD52" alt="gui">
  <img src="https://img.shields.io/badge/license-MIT-8B949E" alt="license">
</p>

---

## ✨ 功能

| 模块 | 说明 |
|------|------|
| 🏠 **总览** | **v4.3 landing 页**: AI账户净值卡 / 最近最强策略 / 市场速览 / 主功能入口 / 账户中心 |
| 📊 **市场概览** | 三大指数实时行情 + 板块热度排行 |
| 🔍 **多因子选股** | 43因子 DSL 条件引擎，Top 20 推荐 |
| 💰 **模拟交易** | 账户/下单/撮合/持仓/T+1风控/费率 + **账户中心(改名/重置/删除)** |
| 🤖 **AI 自主交易** | 6工具 function calling，查行情→分析→下单全自动 |
| 🧠 **量化研究代理** | **backend/agent 研究闭环**: LLM 生成→回测→复盘→择优→AI决策门→paper |
| ♻ **策略进化闭环** | **v4.3 optimize_loop**: 5家族精确指标(α/年化/夏普)→LLM 提新契约→回测→裁决→模拟盘 |
| 📈 **K线图表** | QPainter 原生渲染，MACD/RSI/BOLL + **右栏抽屉按需滑出(非常驻)** |
| 🎯 **筹码分布** | JS 引擎本地计算，获利比例/平均成本/集中度 |
| 📦 **持仓管理** | 纸面盘账本: 5策略收益曲线对比/每日持仓/每笔调仓 + **净值曲线 mini 卡** |
| 🔄 **数据管道** | **每日自动更新(Windows计划任务 17:00)**: K线池/基本面/纸面盘/净值快照 |
| 🛡 **卖出门三驱动** | **条件止损(8%)+移动止损(10%/15%激活)+策略卖出**, 无固定止盈, 保护优先于排名 |
| 🔬 **完整生命周期验证** | **verify_full_lifecycle**: 选股→买→持有(带保护)→卖→结算→净值逐日回放 |
| 🧪 **分周期测试** | **cycle_test**: 牛/熊/震荡/全周期分类 + 样本内/样本外(防过拟合) |
| 🔄 **周期策略轮换** | **判断器驱动**: 牛→B反转进攻 / 震荡→F价值Tilt / 熊→C低波动防守, 模拟盘自动切换 |
| 📰 **事件驱动池** | AI账户当日涨停+热点板块, **isolated 突发利好·短期观察, 不进长期策略** |
| 🔎 **个股资讯深挖** | 选股剩前8只→豆包搜资讯→**LLM独立主观判断**(前置/后移/保持/剔名) |
| 🗄 **数据中心** | SQLite 多库浏览，表行数/列清单/日期范围 |
| 🤖 **AI 助手** | 浮动聊天窗，DeepSeek V4/智谱 GLM-4/Kimi K2.6 |
| ⚙ **设置中心** | 字体 + 窗口大小 + AI 供应商预设 + 测试连接 |

## 🏗 架构

**v4.x 插件化架构** — 平台骨架独立运行，15 个功能插件挂载。单插件崩溃不影响全局。

```
Platform Shell (无边框自绘标题栏)
  └─ PluginManager → 发现 / 注册 / 激活 / ErrorBoundary
      └─ 15 插件, 导航分两组: 核心工作流 / 数据工具
         核心: overview / research / picks / holdings / trade / agentops
         数据: market / datacenter / datapipeline / trainer / flow / kline
         顶栏: agent / search / settings
右栏 = 可折叠抽屉 (K线按需滑出, 非常驻占半屏)
```

插件间通过 `PlatformBus` 信号总线通信（含 `navigate_plugin(plugin_id, payload)` 带参跳转）。支持**伴侣面板**和 **AI 工具调用**。

## 🔄 核心交易循环 (v4.3)

**全自动闭环**，含判断器驱动的周期轮换、三驱动卖出门、分周期验证。详见 **`docs/Trading_Loop.md`**。

```
数据引入(行情/基本面) → 多因子复合判断 → regime动态权重 → 周期策略轮换(判断器驱动)
  → 回测(分周期+样本外) → 模拟盘(多策略+轮动) → 每日复盘 → sell三驱动(止损/移动止损/策略卖出)
  → LLM介入(个股深挖+事件驱动) → 净值结算 → 迭代
```

- **卖出门三驱动**: 条件止损(8%) + 移动止损(10%/15%激活) + 策略卖出(排名调出), 无固定止盈(让利润奔跑)。
- **周期轮换**: 牛→B反转进攻 / 震荡→F价值Tilt / 熊→C低波动防守 — 模拟盘自动切换。
- **验证**: 完整生命周期 + 分周期(牛/熊/震荡/全周期) + 样本外防过拟合。
- **数据地基**: 2023 K线缺口已补齐 (BP覆盖40→223/287), F价值Tilt全周期+98.3%。

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

暗色方案: `#0B0D11` / `#14171C` / `#D4A574` (金)  
字体: 19-23px (dp 自适应缩放)，窗口: 1980×1280 (大) / 1550×950 (中) / 1400×850 (小)

## 📄 文档

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计、插件系统、目录结构 |
| [TECH_MANUAL.md](docs/TECH_MANUAL.md) | 技术手册、交易引擎、AI 工具、数据库 |
| [SESSION_PROMPT.md](docs/SESSION_PROMPT.md) | AI 对话提示词、API 路由 |
| [RESEARCH_AGENT.md](docs/RESEARCH_AGENT.md) | backend/agent 量化研究代理层：闭环架构/因子库/安全/验证 |
| [TASK_LOG.md](docs/TASK_LOG.md) | 量化研究里程碑：提交序列 + 验证状态 |

## 🛠 技术栈

| 层 | 技术 |
|----|------|
| GUI | PyQt5, QPainter | 
| 后端 | Flask (可选), 26 路由 |
| 数据库 | SQLite × 多库 (kline.db + fundamental.db + stock_cache.db + sim_trade.db) |
| 数据源 | AKShare / Sina API (三源回退 Sina主/TX/EM + 硬超时) |
| 模拟交易 | 自研 TradeEngine |
| 量化策略 | factor_engine + portfolio_rebalance (SelectionContract) |
| LLM | openai SDK, 6-tool function calling |
| 自动化 | update_daily.py + Windows 计划任务 (项目 venv `.update-venv/`) |

## 📝 版本

| 版本 | 日期 | 要点 |
|------|------|------|
| v4.3 | 2026-08-27 | 总览 landing 页 / 策略进化闭环(α·年化·夏普精确指标) / 账户中心 / 净值曲线 / K线右栏抽屉 / 无边框自定义标题栏 / 每日自动更新(17:00计划任务) |
| v4.2.0 | 2026-07-27 | 模拟交易系统、AI Agent 工具调用、dp缩放、窗口大小设置 |
| v4.1.0 | 2026-07-24 | AI Agent 插件、设置面板重构、供应商预设 |
| v4.0 | 2026-07-23 | 插件化架构、伴侣面板、数据管道 |

---

<p align="center">
  <sub>develop by siyuan-chen & xiaoguang</sub>
</p>
