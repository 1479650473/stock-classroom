# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v5.1 — Web 栈(Vue3+TS+Lightweight Charts+Tauri2) + Flask API v2
- **Type**: Tauri 2 Desktop App (Web frontend) + Flask API v2 (blueprints)
- **Python**: 3.14.3 (`C:\Python314`) — 项目运行时用这个
- **Database**: SQLite 多库 (`kline.db` + `fundamental.db` + `stock_cache.db` + `sim_trade.db` + `ai_trader.db` + `macro.db` + `agent.db`)
- **Data Source**: AKShare / Sina API (三源回退 Sina主/TX/EM)
- **PyQt5 旧版已归档删除** (`archive/pyqt5-legacy-2026-09-05.zip`)，`frontend/` 目录不存在，后端无任何 `frontend.*` 依赖；旧文档在 `archive/docs-pyqt5-legacy/`

## Architecture (Web v5.1)
```
Tauri Shell (web/src-tauri, frameless, 启动时拉起 stock-api.exe sidecar)
  └─ Vue3 SPA (web/src: views/router/stores/composables)
       └─ Flask API 127.0.0.1:5000 (backend/api/server.py, 17 blueprints, 统一 envelope)
```
- **后端打包**: `package/stock_api.spec` → 单文件 `stock-api.exe` (PyInstaller, 含 akshare data)
- **前端打包**: `web/src-tauri` → NSIS/MSI 安装包 (bundle.resources 内嵌 stock-api.exe)
- **打包 pathex 只加 root + `backend/`**（不要加已不存在的 `frontend/`）
- **打包后数据目录**: exe 旁 `data/` (或 `SC_DATA_DIR` 环境变量); frozen 路径经 `backend/api/paths.py` / `data_manager.py` / `trade_engine/schema.py` 处理

## Web API(backend/api/)
- `server.py`: create_app, 全局错误信封, CORS 限本机 origins; 注册 blueprints: system/jobs_bp/market/trade/kline/picks/overview/research/research_v2/agentops/pipeline/trainer/agent_chat/optimize/scheduler_bp/replay/**trader**
- `envelope.py`: ok/err + `int_arg()` 安全解析; 所有 blueprint 统一 error.code=string
- `jobman.py`: 线程池 job + SSE, 6h TTL 清理; `web/src/api/client.ts:streamJob` 前端复用
- `paths.py`: PROJECT_DIR / DATA_DIR / 各 DB 路径 (frozen 安全)
- `settings_store.py`: 读写 `backend/configs/settings.json` (白名单 theme/font_size/window_size/agent)
- `agent_chat.py`: `/api/agent/chat` SSE tool-calling(16工具); `backend/agent/toolkit.py`
- `agent/routes.py`: `/api/agent/v1` 能力分级网关 (R/W/B/T + 审计/幂等/限流/paper-only)，已挂载进 `create_app`（供外部 agent/MCP）；冒烟 `python backend/agent/smoke_test.py`

## Web 前端(web/src)
- **信息架构 v6**: 6 主页面 + 设置 — 工作台 `/` / 行情 `/market` / 策略 `/strategy` / 交易 `/trade` / AI `/ai` / 数据 `/data`; 旧路由 (`/overview /flow /kline /picks /holdings /agentops /agent /optimize /replay /research /datacenter /pipeline /trainer`) 全部重定向
- **AI 页三页签**: `AI 操盘手`(v6/TraderHub.vue: 总览对比 TraderOverview + 交易员详情 Trader) / `对话操盘`(Agent.vue) / `自动操盘台`(AgentOps.vue)
- **组件库**: `components/ui/` (AppPage/PageToolbar/SectionCard/StatTile/DataTable/Drawer/FormField/EmptyGuide/LoadingBlock/SearchInput/SegmentedControl)
- **图表**: `components/charts/KlineChart.vue` 封装 TradingView Lightweight Charts v5; 回放器仍用 ECharts (`composables/useEChart.ts`)
- **全局任务中心**: `stores/jobs.ts` (SSE 由 store 持有，切页面不断连) + `components/TaskCenter.vue`
- **设置持久化**: `composables/usePersistedRef.ts` (localStorage `sc_` 前缀)
- **主题**: `styles/tokens.css` 三主题 graphite / obsidian / ivory (含 `--ok`)

## AI 操盘手(backend/trader/) — 长期自主 LLM 交易员（支持多个）
**与「策略进化闭环」机制不同**：策略进化是 LLM 写策略契约→回测→裁决；AI 操盘手是 LLM 直接扮演交易员，操作专属账户做买卖决策。

- **多交易员**：每个交易员 = 独立档案 + 独立模拟账户 + 可选独立模型（`trader_profile.model`，空=全局）；可自定义新建/编辑/停用/删除（`/api/trader/profiles`）。前端 AI 页「AI 操盘手」= 总览对比（净值曲线 vs 沪深300 + 时间范围 + 对比表）+ 交易员详情（切换）。

| 文件 | 作用 |
|------|------|
| `account.py` | 交易员档案/账户生命周期：`ensure_profile`(兼容单例) / `create_trader` / `delete_trader` / `list_traders`；`trader_engine()` 解除项目级单票 30% 限制 |
| `store.py` | `data/ai_trader.db`: `trader_profile`(含 model/kind/meta) / `trader_decision`(含 trace/candidates/review) / `trader_memory` (轻量迁移) |
| `news.py` | 东财全球财经 + 个股新闻 (豆包可选)，按日缓存、失败降级 |
| `context.py` | 每日上下文: 账户/持仓(持有天数)/待成交委托/净值/regime/沪深300/候选/事件池/新闻/历史决策/自我风格/你的战绩 |
| `tools.py` | 13 工具: 查询 + `preview_order` + **`place_order`(直接下单)** + `cancel_order` + `remember` + `submit_decision` |
| `agent.py` | TraderAgent: LLM tool-calling 循环，产出思考/复盘 + 工具轨迹；支持 profile 级 model |
| `daily.py` | `run_daily_decision(profile_id)` 单交易员；`run_all_daily_decisions()` 遍历所有 enabled；同日幂等；`_maybe_review()` 周五/回撤≥8% 触发绩效自省 |
| `selection.py` | 选股链路审计: `build_snapshot(ref_date, top_n, with_events)` 输出股票池来源/生效与未生效过滤/评分卡窗口与五组权重/筛选漏斗/候选及分项得分；`compact_note()` 给模型看的候选池说明。候选池随决策落库，事后可核对 |
| `performance.py` | 战绩与自我提升: `performance_block()` 按 FIFO 配对成交算胜率/盈亏比/平均持有/连势/累计收益/最大回撤/日胜率；`performance_summary_text()` 注入上下文；`review_trader()` 强制自省产出 self_critique/lessons/style/**rules(纪律规则)** |
| `discipline.py` | **自省结论 → 硬约束**: 规则白名单 `block_new_buy/position_cap_pct/stop_loss_pct/max_new_positions_day/require_momentum_up`；`normalize_rules()` 只能收紧不可放宽、去重、上限6条；`save_rules()` 落 `kind='rule'` 记忆（同类只留最新）；`active_rules()/protection_rules()` 按 as_of 判生效与过期；`check_buy()` 在下单路径执行；`enforce_protection()` 收盘后强制止损/移动止损（含 T+1 处理）。系统兜底 `DEFAULT_PROTECTION`(止损8%/移动止损10%@15%) |

- **规则归系统**: 本金固定与 A 股规则**不写进提示词**，由 TradeEngine 强制执行，违规返回错误让模型自行调整（像用券商软件）。
- **风格自定**: 无预设人设；AI 把自我认知写入 `kind='style'` 长期记忆（同类只保留最新 active），持仓逻辑 `kind='thesis'`，另有 `lesson`/`note`/`market`。
- **触发**: `update_daily.py` 第⑨步（对每个 enabled 档案逐个跑）+ `/api/trader/run`（单交易员）/ `/api/trader/run-all`（全部启用）。
- **API**: `/api/trader/{profiles,overview,state,profile,decisions,memory,run,run-all,news,selection,performance,rules}`（state/decisions/memory/run 按 `profile_id`；`selection` 支持 `date=` 按历史日 as-of 审计选股口径、`weights=` 覆盖评分口径；`performance` 返回战绩明细；`rules` 返回生效纪律规则与兜底保护参数）。
- **自我提升闭环**: 模型上下文有「你的战绩」（真实胜率/回撤/盈亏比/连势），先看数据再决定是否改变打法；每 3 个交易日 / 回撤≥8% / **单笔平仓亏损≥5%** 触发强制自省，把战绩+逐日决策原文交给 LLM，产出 `self_critique`/`lessons`/`style`/**`rules`**，存 `trader_decision.review` 并写入 `kind='lesson'/'style'/'rule'` 长期记忆。前端「战绩与自我提升」面板 + 每日「选股依据·候选池」「自我复盘」卡片。
- **自省变硬约束（两层）**: ①下单路径 —— 生效规则由 `discipline.check_buy()` 在 `place_order/preview_order` 前检查，违规直接拒绝并返回券商式原因（模型只能调整）；②持仓保护 —— 每日决策后 `enforce_protection()` 对未平仓持仓做兜底止损/移动止损，模型不卖的由系统卖（回放与实盘 `run_daily_decision` 同一套）。规则可带有效期（默认 5 交易日）自动过期，且只能比系统兜底更严。
- **评分口径可覆盖**: `factor_engine/config.py` 的 `WEIGHT_PRESETS`（`default` / `steady{trend18,momentum15,volume10,price10,stability30}`）+ `resolve_weights()`（预设名 / dict / `"trend:18,momentum:15"`）+ `load_config_with_weights()`（按目标满分等比缩放组内 condition 分值）。回放创建可带 `weights`（写入 `profile.meta.weights`），用于同一参数下的口径对照实验。
- **纵向回放** (`replay.py`): 让交易员在过去数据里逐日无前视模拟。as-of 上下文（K线/regime/候选全部 `date<=D`，历史新闻不可回溯故标注不可用）；date-aware 工具按历史日成交/结算；游标存 `profile.meta.cursor`，每次最多 30 天可续跑；每 20 日 LLM 生成一次阶段总结（`kind='stage'`）压缩上下文；`distill_to_live()` 把回放风格/教训/笔记回流到源交易员。API `/api/trader/{replays,replay,replay/<id>/continue,replay/<id>/distill}`。前端 AI 页「AI 操盘手 → 纵向回放」。

## 因子挖掘与体检（backend/alpha/）— 公式搜索 + 因子动物园 + 机器学习

**来源**：机制借鉴 AlphaGPT（公式 token + 栈式 VM + 回测当奖励），因子清单借鉴 Qbot（Alpha158/技指），
工程模式借鉴 QuantDinger（MCP + 可观测性 + 通知）。结论优先于机制，见下方「已证实/已否定」段。

| 文件 | 作用 |
|------|------|
| `dsl.py` | 公式 DSL：18 算子 + Polish 前缀记法 + 栈式求值（numpy 面板）+ decode/随机合法建树 |
| `panel.py` | kline.db → `[股票 × 交易日]` 面板；**39 个因子**（均线族/分布形状/量价/ATR/换手统计/PSY/CCI/KDJ/OBV/VR/新高距离…）全部因果 + 截面 robust 标准化；open-to-open 目标；涨跌停/停牌掩码；**股票池按回测起点前成交额排序**（防选择偏误）+ 磁盘缓存；`build_neutralizer/neutralize_apply` 风格中性化（向量化） |
| `reward.py` | 回测奖励：Top-K 组合（T+1 开盘、单边 5bp）、Rank IC；**hold>1 重叠建仓**（换手 0.77→0.17）；超额（相对等权池）指标 |
| `search.py` | 遗传搜索（锦标赛/子树交叉变异/精英保留） |
| `walk_forward.py` | 滚动验证：train 24 月 → test 6 月逐折独立搜索；**随机对照**（同预算随机公式）+ 零信号基准 |
| `factor_zoo.py` | 批量体检 39 因子（含反向 78 个）：IC/IC20/中性化 IC/超额/Sortino/回撤/换手/半年为正 → `data/factor_zoo.json` |
| `composite.py` | **已验证的固定权重组合**：`-RET1 / -RET5 / -HIGH60_GAP / -LOG_AMT20` 等权 rank 合成，as-of 安全，参考日取「覆盖率≥60% 的最后一个交易日」 |
| `composite_test.py` | 固定组合的 10 折样本外验证 + 多空分位价差（市场中性口径） |
| `ml_rank.py` | 截面机器学习选股（sklearn HGB / numpy 岭回归）+ Monte-Carlo 块自助 + 随机对照 |
| `factor_analysis.py` | Alphalens 风格：分位组合/多空净值/单调性/IC 衰减/成本敏感性 |
| `validate_known.py` / `diagnose_null.py` | 流程自检（已知因子方向）与零信号基准 |
| `pipeline.py` / `store.py` / `import_reports.py` | API 与 CLI 共用的 mine/walk_forward 主流程 + `data/alpha.db`（alpha_run/alpha_formula）落库 |

**API**：`/api/alpha/{meta,mine,walkforward,runs,run/<id>,composite,zoo,composite_report,factor-analysis}`、
`/api/trader/selection?source=scorecard|composite`、`/api/report/{composite,factor-zoo,factor-analysis,backtest}`、
`/api/notify/{list,summary,read,clear,settings,test}`、`/metrics`（Prometheus 文本）。

**已证实 / 已否定**（300 只流动股 × 2016-2025，数据见 `data/factor_*.json`、`data/alpha_*.json`）：
- **公式搜索无效**：搜出来的“最优公式”样本外不如同预算随机对照（搜索−对照 −14.3pp，仅 2/10 折更好）。
- **固定因子组合有效**：短期反转 + 小市值 + 远离 60 日高点，10 折样本外超额为正 **8/10**，多空价差 +9.0%/年。
- **低波动类因子在本土是反向的**（高波动占优）：-ATR14/-AMP 多空价差 -28%/-45%，“超额为正”是风格 beta。
- **机器学习（HGB）的极端分位含真实信息**：多空价差均值 **+32.2%、9/10 折为正**（截尾 ±11% 复算仍成立），但整体 IC ≈ 0。
- **IC 口径陷阱**：计算 IC 时**不能叠加“次日涨停不可买”过滤**（信号恰好集中在这些样本，会把 IC 抹到 0）；可买性只约束组合构建。

**数据可靠性**（实测教训）：`py_mini_racer`(新浪 V8) 在 **20 并发下会崩进程**，补数据并发 ≤12-16；
`update_daily` 的全市场增量已改为固定回看 10 个交易日（原全局缺口判断会漏“某天只有部分股票更新”）；
`scripts/backfill_missing_day.py` 用于逐股票补齐残缺交易日（分块落库、可续跑）。

## 回测报告 / 可观测性 / 通知 / MCP
| 模块 | 说明 |
|------|------|
| `backend/strategy/report.py` | 自包含 HTML 报告（KPI + 净值曲线 + 月度热力表 + 分位柱状图 + 交易明细），零第三方绘图依赖 |
| `backend/metrics.py` | `/metrics`（Prometheus 文本）+ `/api/system/metrics`：任务/数据新鲜度/覆盖/未读通知/操盘手决策时效/data 占用 |
| `backend/notify.py` | 本地事件流（`data/notifications.json`，5 分钟节流）+ 可选 webhook；挂钩 jobman 任务失败与 update_daily 步骤异常；前端 `NotifyBell.vue` |
| `backend/mcp_server/` | MCP Server（stdio）：把 `/api/agent/v1` 包装成 **24 个工具**（R/W/B/T 分级），配置 `SC_BASE_URL`/`SC_AGENT_TOKEN`；见该目录 README |

## Key Files
| Layer | Files | Purpose |
|-------|-------|---------|
| Web | `web/src/router/index.ts` | v6 路由 + 旧路由重定向 |
| Web | `web/src/views/v6/*.vue` | 6 主页面 (Dashboard/Market/Strategy/Trade/AI/Data) |
| Web | `web/src/views/v6/TraderHub.vue` | AI 操盘手容器：交易员切换/新建/删除 + 总览/详情 |
| Web | `web/src/views/v6/TraderOverview.vue` | 总览对比：净值曲线 vs 沪深300 + 对比表 |
| Web | `web/src/views/v6/Trader.vue` | 单个交易员详情页 |
| Web | `web/src/views/v6/Replay.vue` | 纵向回放：实时逐日流 + 月/日折叠树 + 候选池/自我复盘/战绩面板 |
| Web | `web/src/components/CandDetail.vue` | 选股依据明细（来源/过滤/评分口径/候选表/事件池） |
| Backend | `backend/data_manager.py` | SQLite CRUD, AKShare dispatch, update_pool |
| Backend | `backend/akshare_source.py` | ~18 API wrappers + 3源回退 + 硬超时 |
| Backend | `backend/paper_worker.py` | 纸面盘 (原 frontend.plugins.research.worker 迁入) |
| Backend | `backend/trainer_engine.py` | 训练引擎 (原 frontend.plugins.trainer.engine 迁入) |
| Backend | `backend/strategy/metrics.py` | full_metrics (α/年化/夏普/胜率/回撤/β) |
| Backend | `backend/strategy/describe.py` | 策略契约→中文 买入/持有/卖出 条件 |
| Backend | `backend/strategy/optimize_loop.py` | 自主策略进化闭环 (LLM 提新契约→回测→裁决) |
| Backend | `backend/strategy/portfolio_rebalance.py` | SelectionContract + forward_paper_run |
| Backend | `backend/strategy/regime.py` | A股牛/熊/震荡分类 + 系统性风险截断 + 权重动态化 |
| Backend | `backend/strategy/sell_rules.py` | 卖出三驱动规约(止损/移动止损/策略卖出, 无止盈) |
| Backend | `backend/strategy/position_guard.py` | 持仓守护引擎(单持仓保护判定) |
| Backend | `backend/strategy/day_guard.py` | 每日持仓守护循环(读模拟账户→判定→预览/真卖) |
| Backend | `backend/strategy/verify_full_lifecycle.py` | 完整生命周期验证(选股→买→持有带保护→卖→结算→净值) |
| Backend | `backend/strategy/cycle_test.py` | 分周期测试(牛/熊/震荡/全周期/样本内外防过拟合) |
| Backend | `backend/strategy/stock_deep.py` | 个股资讯深挖+LLM主观判断(选股剩几只后) |
| Backend | `backend/strategy/news_driven.py` | 事件驱动候选池(涨停+热点板块+豆包消息, isolated) |
| Backend | `backend/agent/search_client.py` | 豆包搜索客户端(资讯源, 财经语境) |
| Backend | `backend/agent/research_loop.py` | ResearchLoop 单标的/组合重平衡 |
| Backend | `backend/agent/llm_client.py` | LLMClient (DeepSeek) + `chat_with_tools(tool_choice=)` |
| Backend | `backend/agent/toolkit.py` | **对话 Agent 工具集(16)**: 交易6/研究4/策略6, `execute_tool(name, args)` |
| Backend | `backend/trader/` | **AI 操盘手** (见上节) |
| Backend | `backend/trade_engine/` | **Simulated trading engine** (accounts/orders/positions/trades/account_nav) |
| Backend | `backend/update_daily.py` | **每日自动化(11步)**: 名录刷新+新股首拉+全市场K线(自动缺口检测≥60根缓冲)+指数/hs300/regime+基本面(3日轮换)+纸面盘+事件池+深挖+守护+净值+AI操盘手+收盘后数据(涨停5日回补/北向/龙虎榜/新高/板块快照)+宏观; 全局异常兜底+stderr落盘, 支持 `--pool-only/--skip-paper/--skip-kline` |
| Scripts | `scripts/rebuild_kline_unified.py` | 新浪qfq多进程全库重拉(统一qfq基准=最新 + volume=股/amount=元, 2026-09-11 修复2022/2023边界断层24%与2023缺2600只); `backfill_gaps.py --year/--days/--codes` 补缺; `check_data_health.py` 健康报告 |
| Backend | `backend/resilience.py` | akshare_wait 改随机分散(2026-09-11 修复 RateLimiter 无锁齐射致 py_mini_racer/V8 并发崩溃 = update_daily 多次3秒静默死亡根因) |
| Backend | `backend/api/blueprints/etf.py` | **ETF**: `/api/etf/{list,kline,compare}` 全市场ETF列表/单只K线/多只归一化对比; 数据在 kline.db `etf_list`+`etf_daily` 独立表(新浪qfq主源, 股/元口径) |
| Backend | `scripts/rebuild_etf.py` | ETF 全量历史首拉(多进程, 1606只/144万行, 幂等可续跑); update_daily ⑫步每日增量 |

## Navigation (v6)
`web/src/lib/nav.ts` = [工作台, 行情, 策略, 交易, AI, 数据]；设置入口在顶栏右侧。旧页面 (Research/Optimize/Replay/Agent/AgentOps/Pipeline/DataCenter/Trainer) 仍被新页面内嵌复用，保留。

## 卖出三驱动(用户策略哲学, 已定死) + 验证
- **不加固定止盈(让利润奔跑)**, 用**三驱动**: ①条件止损(默认8%, 兜底防大亏) ②移动止损(默认10%回撤/15%激活, 利润奔跑后锁利) ③策略卖出/重平衡调出(信号/排名失效兑现). `sell_rules.SellRuleSet.build(rebalance_bars, top_k_pct, stop_loss_pct=0.08, take_profit_pct=0, trailing_stop_pct=0.10, trailing_activation_pct=0.15, enable_rebalance_exit=True)`; `time_limit_bars` 默认0(不设时间止损, 与重平衡周期同长会每期清仓致 rebalance_exit 永不触发). 卖出优先级: 止损>移动止损>重平衡调出>止盈.
- **完整生命周期验证**: `verify_full_lifecycle(frames, contract, start, end, rule_set)` 逐日回放(每日保护判定+重平衡日排名调出+净值/指标/胜率/α). **保护bar必须用真实 open/high/low panel**(high/low=0 会每票每值误报止损).
- **分周期测试**: `cycle_test.run_cycle_test(frames, contract, rule_set)` 按 regime 把历史切成牛/熊/震荡主要周期段, 各段跑 verify → 对比 + 样本内/样本外(防过拟合) + 全周期. 对应架构图"回测架构".
- 卖出引擎: `position_guard.PositionGuard`(单持仓判定) + `day_guard.run_day_guard(dry_run=True)`(每日读模拟账户, 默认预览不真卖). 落库 `data/day_guard_log.json`. 前端 trade 持仓表加"卖出条件"列(触发红'止损'/绿'移动止损'/黄, 未触发灰'保护中').

## Theme (Web)
- Dark: `#0B0D11` (bg) / `#14171C` (panel) / `#D4A574` (accent gold) — graphite
- 3 themes: graphite / obsidian / ivory，全部 token 在 `web/src/styles/tokens.css`；语义色 `--up`(红涨) / `--down`(绿跌) / `--ok`(成功态)

## Naming Conventions
- 前端页面: `web/src/views/v6/*.vue` (主页面)，旧页面 `web/src/views/*.vue` (被内嵌)
- 后端: `backend/` 含全部数据/策略逻辑; 蓝图在 `backend/api/blueprints/`
- 中文 UI 文案; 尺寸/颜色用 CSS 变量 (`tokens.css`)，不硬编码

## Build
**Web 版(Tauri) — 需要 vcvars64 环境(cl.exe)**:
```bat
rem 1) 后端 sidecar (PyInstaller, 含 akshare data)
python -m PyInstaller --clean --noconfirm package\stock_api.spec --distpath package\dist --workpath package\build_api
rem 2) 前端 + 外壳 (需先 activate VS BuildTools vcvars64)
cd web\src-tauri && cargo tauri build
rem 输出: web\src-tauri\target\release\bundle\{msi,nsis}\StockClassroom_*.exe
rem 便携版: package\dist\stock-api.exe 与 web\src-tauri\target\release\stock-classroom.exe 放同目录, 旁有 data/ + backend/configs/
```
**前端校验**: `cd web && npx vue-tsc --noEmit && npx vite build`（本机 npx 不在 PATH 时用 `C:/nvm/v22.23.2/node.exe`）

## Dependencies
Core: `flask`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`
- 项目固定 venv `.update-venv/` (uv, 供每日自动化 update_daily.py) 装 akshare/pandas/openai/baostock.

## Git
Remote: `https://github.com/1479650473/stock-classroom`
- data/ 整目录 gitignored, 不入库; 临时 `_*.py/_*.png/_*.log` 不入库; api_key 绝不入库.
