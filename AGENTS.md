# AGENTS.md — AI Assistant Context

## Project Identity
- **Name**: stock-classroom (A股量化教室)
- **Version**: v5.1 — Web 栈(Vue3+TS+Lightweight Charts+Tauri2) + Flask API v2
- **Type**: Tauri 2 Desktop App (Web frontend) + Flask API v2 (blueprints)
- **Python**: 3.14.3 (`C:\Python314`) — 项目运行时用这个
- **Database**: SQLite 多库 (`kline.db` + `fundamental.db` + `stock_cache.db` + `sim_trade.db` + `ai_trader.db` + `macro.db` + `agent.db`)
- **Data Source**: AKShare / Sina API (三源回退 Sina主/TX/EM)
- **PyQt5 旧版已归档删除** (`archive/pyqt5-legacy-2026-09-05.zip`)，`frontend/` 目录不存在，后端无任何 `frontend.*` 依赖；旧文档在 `archive/docs-pyqt5-legacy/`

## Architecture (Web v5.2)
```
Tauri Shell (web/src-tauri, frameless, 启动时拉起 stock-api.exe sidecar)
  └─ Vue3 SPA (web/src: views/router/stores/composables)
       └─ Flask API 127.0.0.1:5000 (backend/api/server.py, 17 blueprints, 统一 envelope)
```
- **后端打包**: `package/stock_api.spec` → 单文件 `stock-api.exe` (PyInstaller, 含 akshare data)
- **前端打包**: `web/src-tauri` → NSIS 安装包 (bundle.resources 内嵌 stock-api.exe + settings.example.json)
- **打包 pathex 只加 root + `backend/`**（不要加已不存在的 `frontend/`）
- **打包后数据目录**: 优先 `desktop.json` 里的 `data_dir`（桌面设置页可改，由壳注入 `SC_DATA_DIR`），
  否则 exe 旁 `data/`; frozen 路径经 `backend/api/paths.py` / `data_manager.py` / `trade_engine/schema.py` 处理

### 桌面壳（web/src-tauri/src/lib.rs，2026-09-20 起）
启动即「微信式」体验：**闪屏 → 主窗口**（主窗口 `visible:false` 创建，前端 bootstrap 完成调 `app_ready`
才显示；壳侧 25s 兜底）、**系统托盘**（显示/最小化到托盘/退出，左键切换）、**关闭=收进托盘**（可关）、
**单实例**（二次双击只唤起）、**窗口记忆**（`window-state`，特意排除 VISIBLE 标志否则会跳过闪屏）、
**开机自启**、**系统通知**（任务完成/失败）。偏好存 `app_config_dir/desktop.json`。
- **CORS 坑（打包版"后端连接不上"的根因）**：Windows 上 Tauri v2 的页面 origin 是
  **`http://tauri.localhost`**（http 不是 https），`backend/api/server.py` 的白名单必须含它，
  否则 webview 里所有请求被浏览器拦掉。
- **端口复用**：壳启动前探测 5000，已有后端就直接复用 —— Werkzeug 默认允许**多个 stock-api 同时监听同一端口**，
  请求会被随机分到旧实例（改后端"不生效"的隐形坑）。
- **后端日志**：`%LOCALAPPDATA%\com.stockclassroom.app\logs\stock-api.log`（GUI 模式下 stderr 原本全丢）。
- **图标**：`web/src-tauri/make_icon.py` 生成 1024 母版 → `cargo tauri icon app-icon.png` 出全平台图标集。

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
| `protocol.py` | **编号决策协议 + 确定性闸门**（借鉴 PA_Agent 决策树）：G0 数据可用性 / G1 风险闸门（能否开仓·额度·上限·冷静期）/ G2 持仓处置（逐票浮亏·距峰值·**结构**·系统标记）/ **G2b 挂单前提** / G3 市场环境（regime+沪深300结构）/ M4 选股依据·M7 下单执行（模型答）/ G5 标的合规 / G6 资金与仓位 / G8 收盘兜底；`validate_decision()` 校验模型输出（thinking 长度/outlook 合法性） |
| `structure.py` | **价格结构特征**（程序算的客观事实，借鉴 market_features）：区间位置与区位、区间宽度×ATR、距上下沿×ATR、波段结构（HH+HL / LH+LL / 区间）、自极点回撤×ATR、**突破质量**（none/wick_probe/close_breakout/failed/testing/surviving/broke_down）、重叠率与**铁丝网分数**、距 MA20×ATR；`compute_cached()` 进程内缓存 |
| `bars.py` | **K 线几何特征**（棒级，判买入/卖出时点）：形态分类（inside/outside/doji/trend bull-bear）、实体与影线占比、收盘位置、与前棒重叠、**微双底 MDB/微双顶 MDT**、内-外-内 IOI、相对 EMA20 跳空棒、对前 5 棒区间突破、**信号棒跟随 follow-through**（yes/failed/no）、**H1/H2/L1/L2 计数**（含"信号棒偏弱"标记） |
| `routing.py` | **结构分类路由**（借鉴 pattern_routing + Al Brooks 策略手册）：把程序事实归成 上升回踩/上升突破/区间上沿/区间下沿/区间中部粘滞/下降破位/突破失败/急涨/不明 九类，每类附「常见处理/主要风险」；提示里写入手册的量化规律（影线试探失败率 70~80%、存活突破约 60% 走到区间高度、铁丝网优先级高于入场信号）；接入上下文、`screen_stocks` 标签、`get_stock_factors` |
| `sys1.py` | **System 1 实验（时序）**：次日大盘方向预测（13 特征：指数动量/位置/均线距离/ATR/波动/量比/全市场广度/北向），逻辑回归+HGB，**时间序列样本外**（训练≤2021、测试 2022+ 1143 天）。结论：**小模型命中 34~35% vs 多数类基线 38.9% —— 谁都做不好**；HGB 原始 ECE 0.306（温度 3.0 后才 0.115）；弃权门控几乎换不来命中率。产出接进模型上下文当**认知护栏**（"连小模型都做不到，你的高置信同样可疑"） |
| `sys1_xsec.py` | **System 1 横截面头（有赢面那个）**：预测「未来 N 日跑赢等权池」的概率，39 因子 + HGB + **三段切分**（训练≤2022/校准 2023/测试 2024+）；保序回归校准（ECE 0.019→0.010）；实测**排序用 raw 概率**（保序是阶梯函数会并列退化）、**信号口径必须是截面分位**（绝对概率带 [0.45,0.55] 实测反向：有信号组超额更低）。样本外 654 天：Top10% 组 5 日超额 **+0.265%**（56.9% 日子为正）vs 固定因子组合 +0.148%；分位分层单调（+0.265/+0.139/+0.039/-0.188/-0.389）→ **排序可信、择时不可信**。持久化 `data/sys1_xsec.pkl`。**分域头**（`--tag/--pool-skip`）：`mid_small` = 流动性排名 601~1800 的中小盘域（`data/sys1_xsec_mid_small.pkl`），样本外 Top10% 组 +0.237%、**空头端 p≤10% 组 -0.718%**（29.5% 日子为正，多空 0.955%）；但同域里**固定因子组合的多头更强（+0.432%）** → 中小盘选股用组合、回避看模型。工具 `get_sys1_view/sys1_candidates` 带 `domain` 参数；API `/api/trader/sys1_xsec?tag=mid_small` |
| `coherence.py` | **决策自洽性校验**（借鉴 coherence_checks）：预测 vs 委托方向、说法 vs 实际委托、买单是否在 thinking 里被提到、账户事实粗交叉；**提示而非拒绝**，随决策落库并前端展示 |
| `continuity.py` | **决策连续性**（借鉴 decision_continuity）：挂单前提失效判定（买单市价高于挂单价 ≥3×ATR 或结构跌破箱体下沿 → "前提已变"，只提示不强制撤）+ 上轮立场关系（首单/同向/反手/延续等待，A股"反手"=清仓后又买回） |
| `calibration.py` | **预测校准**（借鉴 Laya 的 RLCD/temperature scaling）：ECE、可靠性曲线、温度拟合（一维逻辑回归，校准后 ECE）、**区分度**（高/低置信组命中率之差，<5pp 则明说"别拿置信度当门槛"）、**门槛建议**（lift <10pp 不建议硬门槛）；样本 <20 条标注不可下结论。设计原则来自 Laya 的教训：**置信度不是概率（要拟合），且模型读不懂输入时置信度不会报警 → 输入校验必须放在模型之前**（我们的 G0/G1/G3 正是如此） |
| `outlook.py` | **每日方向预测 + 自动打分校准**（借鉴 PA_Agent 的"未来走势预期"，闭环化）：模型给 `outlook={direction(up/down/flat/**abstain**),confidence,reason}`（abstain=弃权，不计命中、单独统计弃权率） → 次日用真实净值结算（±0.3% 算平）→ 命中率/**方向性命中率（排除看平）**/置信度分桶/Brier；`score_pending()` 在 daily 与 replay 里自动补分 |
| `performance.py` | 战绩与自我提升: `performance_block()` 按 FIFO 配对成交算胜率/盈亏比/平均持有/连势/累计收益/最大回撤/日胜率；`performance_summary_text()` 注入上下文；`review_trader()` 强制自省产出 self_critique/lessons/style/**rules(纪律规则)** |
| `discipline.py` | **自省结论 → 硬约束**: 规则白名单 `block_new_buy/position_cap_pct/stop_loss_pct/max_new_positions_day/require_momentum_up/**sell_reentry_cooldown**（卖出冷静期·反手冷却）/**pending_expiry_days**（挂单超时撤销）`；`normalize_rules()` 只能收紧不可放宽、去重、上限6条；`save_rules()` 落 `kind='rule'` 记忆（同类只留最新）；`active_rules()/protection_rules()` 按 as_of 判生效与过期；`check_buy()` 在下单路径执行；`enforce_protection()` 收盘后强制止损/移动止损（含 T+1 处理）。系统兜底 `DEFAULT_PROTECTION`(止损8%/移动止损10%@15%/**冷静期1日/挂单超时3日**)；`expire_pending_orders()` 每日决策前清理陈旧挂单 |

- **规则归系统**: 本金固定与 A 股规则**不写进提示词**，由 TradeEngine 强制执行，违规返回错误让模型自行调整（像用券商软件）。
- **风格自定**: 无预设人设；AI 把自我认知写入 `kind='style'` 长期记忆（同类只保留最新 active），持仓逻辑 `kind='thesis'`，另有 `lesson`/`note`/`market`。
- **触发**: `update_daily.py` 第⑨步（对每个 enabled 档案逐个跑）+ `/api/trader/run`（单交易员）/ `/api/trader/run-all`（全部启用）。
- **小模型协同实验结论（3 个，含 2 个负结论，别重复踩）**：取交易员账户 181 笔真实买入逐笔检验「小模型当第二意见」——① ✓ 它池内排序有效（600 只池 Top10% 组 5 日超额 +0.231% vs 固定因子组合 +0.208%，分层单调）；② ✗ **不能用它评审 LLM 的选择**（它的分位与 LLM 买入的 5 日结果相关 **-0.291**，最看好组 -2.24% vs 最不看好组 +2.85%）；③ ✗ **不能当风险预警**（与后续 20 日回撤相关 +0.02）；④ 覆盖不足：LLM 选票 65.7% 在它参照系外（LLM 偏好池外中小票）。→ 归因：**两者不同域不同风格**（LLM=池外+动量/主题；小模型=池内+短周期反转/小市值），互相评审必然错配。定位=**独立扫描器/候选来源**，不是评分器。证据 `data/experiments/llm_picks_vs_sys1.json`。
  **域匹配复检（第二轮）**：LLM 选票的流动性排名中位 **1341**（≤600 占 31%、≤1800 占 57%、≤3000 占 76%）→
  换用 `mid_small` 头后覆盖升至 57%，但相关性仍为 **-0.208**；换到 LLM 的持有周期（10/20 日）相关在
  -0.02~+0.56 之间噪声波动（分组 n 极小，不足下结论）→ **"域匹配"提高了覆盖率，没有恢复评审价值**；
  结论不变：小模型只输出**它自己的名单**（供参考/对照），不评判 LLM 的名单。
  **严格池复验（2026-09-24，前视修复后）**：两个头都**维持排序能力**（结论未被前视污染）——
  mid_small（裁尾 ±20%）：Top10% +0.197%（旧 +0.147%）/ Bottom10% -0.985% / 价差 **+1.182%**（旧 +1.112%）；
  流动池头：原始 top10% +0.267%（旧 +0.231%）/ 裁尾价差 +0.787%。
  **A/B：空头端当候选池过滤器（在模型自己的域内，三配置 K=20/50、H=5/10，654 天）** ——
  对照臂 A=固定因子组合 TopK（本域已验证更强的多头选择器，也是 LLM 候选池的现实代理）：
  ① 过滤臂 B（A 剔除模型当日后 10%）B−A = **-0.007/+0.002/-0.003%**（零效果）—— 方向对（被剔者 -0.180% vs 池均 +0.148%）
  但**平均只删 0.7/50 个名字**，且对照池 50 个里已有 16.4 个同时在模型前 10%（两选择器多头高度一致）；
  ② 正向结合臂 F（组合∩模型前 10%，"双重认可"）F−A = **-0.047/-0.092/-0.091%**（三配置一致为负，反而更差，
  与"模型多头弱于组合"自洽）；③ oracle 上界 ±4~8%/5日说明真机会在"选得更好"，但小模型不给这份增量信息。
  → 最终定位：**独立扫描器**，任何"拿它改造另一个选择器"的用法都无证据支持。证据 `data/experiments/ab_short_filter_k*.json`。
- **小模型协同**：工具 `sys1_candidates(top)`（小模型从流动性前 400 只里挑横截面最强的当起点）+ `get_sys1_view(codes)`（查关注票的"跑赢等权池"概率 + 全场分位信号）；SYSTEM 里写明"排序可信、择时不可信，参考不是指令"。API `/api/trader/sys1`（时序实验）与 `/api/trader/sys1_xsec`（横截面成绩，带 `codes=` 可现算）。
- **API**: `/api/trader/{profiles,overview,state,profile,decisions,memory,run,run-all,news,selection,performance,rules,outlook}`（state/decisions/memory/run 按 `profile_id`；`selection` 支持 `date=` 按历史日 as-of 审计选股口径、`weights=` 覆盖评分口径；`performance` 返回战绩明细；`rules` 返回生效纪律规则与兜底保护参数）。
- **自我提升闭环**: 模型上下文有「你的战绩」（真实胜率/回撤/盈亏比/连势），先看数据再决定是否改变打法；每 3 个交易日 / 回撤≥8% / **单笔平仓亏损≥5%** 触发强制自省，把战绩+逐日决策原文交给 LLM，产出 `self_critique`/`lessons`/`style`/**`rules`**，存 `trader_decision.review` 并写入 `kind='lesson'/'style'/'rule'` 长期记忆。前端「战绩与自我提升」面板 + 每日「选股依据·候选池」「自我复盘」卡片。
- **自省变硬约束（两层）**: ①下单路径 —— 生效规则由 `discipline.check_buy()` 在 `place_order/preview_order` 前检查，违规直接拒绝并返回券商式原因（模型只能调整）；②持仓保护 —— 每日决策后 `enforce_protection()` 对未平仓持仓做兜底止损/移动止损，模型不卖的由系统卖（回放与实盘 `run_daily_decision` 同一套）。规则可带有效期（默认 5 交易日）自动过期，且只能比系统兜底更严。
- **评分口径可覆盖**: `factor_engine/config.py` 的 `WEIGHT_PRESETS`（`default` / `steady{trend18,momentum15,volume10,price10,stability30}`）+ `resolve_weights()`（预设名 / dict / `"trend:18,momentum:15"`）+ `load_config_with_weights()`（按目标满分等比缩放组内 condition 分值）。回放创建可带 `weights`（写入 `profile.meta.weights`），用于同一参数下的口径对照实验。
- **纵向回放** (`replay.py`): 让交易员在过去数据里逐日无前视模拟。as-of 上下文（K线/regime/候选全部 `date<=D`，历史新闻不可回溯故标注不可用）；date-aware 工具按历史日成交/结算；游标存 `profile.meta.cursor`，每次最多 30 天可续跑；每 20 日 LLM 生成一次阶段总结（`kind='stage'`）压缩上下文；`distill_to_live()` 把回放风格/教训/笔记回流到源交易员。API `/api/trader/{replays,replay,replay/<id>/continue,replay/<id>/distill}`。前端 AI 页「AI 操盘手 → 纵向回放」。

## LLM 操盘手 vs 机械组合（2026-09-23，结论：**不能判操盘手选股无用**）

用已有 19 个回放档案、**从 `trader_decision.executions` 取模拟日期的买入**（trades.traded_at 对老回放是真实时间，会错位），
按日配对比较（同一天：LLM 的买入 vs 组合 Top-K 的每只票），裁尾口径、相对中小盘域等权池：

| 周期 | LLM 选票 | 机械组合 Top20 | LLM−组合 | LLM 胜率 |
|---|---|---|---|---|
| **5 日** | **+1.110%** | +0.503% | **+0.608%** | **57.5%** |
| 10 日 | -0.068% | +0.038% | -0.106% | 45.3% |
| 20 日 | -0.442% | -0.467% | +0.025% | 54.7% |

- **5 日尺度上 LLM 不弱（点估计更好）但置信区间极宽（±17~20%）→ 样本不足以判定显著**；
  10/20 日两者都归零/转负
- **与组合 Top50 重叠 0%** → 两条腿**互补而非冗余**（LLM 不买组合前排的票）
- 买入当天该股涨停的比例仅 **0.7%** → 它**不追板**（与"事件全是负期望"的注入相容）
- 机械组合在**不同窗口间波动很大**（2022-04 窗 +2.3%/5日 ↔ 2026-04 窗 -3.8%/5日）→ 单窗口结论不可靠，必须长样本
- → 因此**上纸面盘（B）**：同时积累"组合"与"操盘手"的前瞻记录，用不可回看的数据判定优劣

## 口径纪律（2026-09-23 更正，重要）

**所有"平均超额"必须标注口径**：A 股中小盘 5 日持有期的超额分布**肥尾极重**（实测 2024+ 样本外
1.6% 的 (股票,日) 观测 |超额|>20%，最大 +144%/5日——真实行情，非数据错误），
**原始均值被个别暴涨股主导**。裁尾 ±20% 后：

| 对象 | 原始均值 | **裁尾 ±20%** | 中位数 | 备注 |
|---|---|---|---|---|
| 中小盘域固定因子组合 Top50 | +0.310% | **+0.193%** | — | 原报告数字约高估 1.6 倍 |
| 小模型（mid_small）Top10% | +0.229% | **+0.147%** | -0.394% | 排序不变（中位口径也单调） |
| 小模型（mid_small）Bottom10% | -0.717% | **-0.965%** | -1.570% | **空头端比原报告更强** |

→ 结论方向不变（分层单调、多空价差 +0.95~1.11%），但**引用数字时用裁尾口径**；
中位数普遍为负说明"典型个股跑输等权池均值"（均值由少数赢家拉动）。
配对差值（B−A）不受影响（同日内相减，肥尾对冲）。

## 股票池前视修正（2026-09-24，重要，改写了"组合超额"的量级）

`panel.pick_universe(as_of=历史日)` 原实现**只限下界不限上界** → 用"今天"的成交额去选历史日的池
（前视）。实测：300 只池子里，前视版与严格 as-of 版**只重叠 41%**（前视版会挑到 2018 年才上市、
如今很流动的名字）。已修：默认 `strict_as_of=True`（`--pool-lookahead` 可复现旧行为对照）。

修正前后（4 因子组合、24/6 折、2016-2025）：

| 口径 | 均值超额 | 中位 | 为正折数 | **多空价差（市场中性）** | 全期 IC |
|---|---|---|---|---|---|
| 旧：前视池 + 无 gap + 不覆盖末段 | **+10.1%/年** | +4.3% | 8/10 | **+9.1%/年**（夏普 0.42） | 0.0055 |
| 新：严格池 + gap5 + 覆盖末段 | **-0.3%/年** | +4.9% | 7/10 | **+9.0%/年**（夏普 0.47） | 0.0159 |

→ **结论修正**：① **排序能力是真的且稳健**（IC 反而升高、多空价差 9%/年不变）；
② **多头超额（相对等权池）主要是前视池造成的假象**（+6.2% → -1.1%）—— 组合研究里"多头绝对/相对水平"
必须用严格池复核，**相对比较（配对差、分层）受影响小**。
③ 中小盘域复核（skip=600/take=1200/2018 池）**没有崩**：K=20/H=5 净@10bp 从 +1.7% → **+4.2%**，
但 H=10/H=20 与 K=50 变差（+5.5%→+2.6%、+2.3%→+0.1%）→ "H=10~20 最优"的说法**不稳健**，
只能说 K=20 集中度有正贡献。
④ **其余结论的池前视复验（2026-09-24，全部用严格池重跑）**：

| 对象 | 旧（前视池） | 新（严格池） | 判定 |
|---|---|---|---|
| 因子体检榜 78 个因子的 **IC 排序** | — | **Spearman 0.969** | ✅ 排序结论稳定（IC 普遍更高：-RET1 0.0054→0.0129、-ATR14 0.0082→0.0201）|
| 「高波动占优」（-ATR14/-AMP 长期组合） | -13.8% / -18.5% | **-6.8% / -9.7%** | ✅ 方向不变、**幅度约减半** |
| HGB 机器学习（`ml_rank`，10 折） | 多空 **+32.2%**（9/10 折） | **+15.6%**（7/10 折） | ⚠️ 大幅减弱，但仍为正、多数折为正 |
| HGB 多头超额 | +11.6% | **-5.3%** | ✗ 与前视池假象一致 |
| `smb`（微盘）| — | 逐月 as-of 剔除、全市场池 | ✅ 无池前视（方法本身干净）|

→ 统一规律：**排序/多空价差类结论基本幸存（幅度下调），"多头超额"类结论系统性被前视池高估**。

⑤ **walk-forward 折构造**同时升级（对照 AlphaMaster 审计）：训练窗已是滚动固定长度（非 expanding）✓、
测试窗等长 ✓；新增 `gap_days=5`（隔离多日持有期标签的边界渗透）与 `include_tail=True`
（原来最新约 1 个月永远不被样本外覆盖）。`composite_test` 新增 `--gap-days/--no-tail/--pool-lookahead`
与 `summary` 落盘（含按折均值与按天加权两种口径）。

## 成本门槛与敞口诊断（2026-09-24，借鉴 AlphaMaster 的多目标奖励）

在 `reward.evaluate()` 里新增三组指标（每次评估自动产出，不再靠事后补测）：
- **`ann_2x_cost` / `ex_ann_2x_cost`**：成本压力测试（2× 成本下是否仍为正）—— 组合的唯一死因是成本
- **`cost_breakeven_bp`**：盈亏平衡费率（每天的组合毛超额 ÷ 换手，换算成单边 bp）
- **`pool_beta` / `side_share` / `weight_hhi`**：敞口诊断（对池的 beta、与池同向的日占比、权重集中度）

**4 因子组合（严格池、24/6 折、2016-2025）的实测**：

| 指标 | 值 | 读法 |
|---|---|---|
| 样本外超额 均值 / 中位 | **-0.3% / +4.9%（年化）** | 均值被少数深负折拖累 |
| **2× 成本超额 均值** | **-4.2%**（6/10 折为正） | **成本门槛不通过** |
| **pool_beta 均值** | **1.077** | >1：放大池的波动，不是低 beta 载体 |
| **side_share 均值** | **0.862** | 86% 的日子与池同向 → **大部分时候是"池的杠杆版"** |

→ 一句话：**多头端没有可证实的净 alpha；alpha 主要在空头端**（多空价差 +9%/年 vs 多头超额 ≈0）。
这与另外两条独立证据一致：事件研究（全是**负**期望）与小模型（强项在**空头端** -0.97%/5日）。
**对纯多头策略的含义**：选股只能"避损"，不能"增收"；真正还没被试的是**仓位/择时**（要不要持有池、
什么时候持有），而 `strategy/regime.py` 已有现成分类器可用来做这个实验。

## 仓位/择时实验（2026-09-24，结论：**择时全害，满仓最好**）

问题：组合 86% 的日子与池同向（β≈1.08）→ "什么时候持有池"是否比"持有哪几只"更重要？
5 条规则对照（中盘域 601~1800、组合 Top-20、24/6 折 10 折、全部因果只用到当日历史）：

| 规则 | 仓位均值 | 折均超额 | 超额年化 | **2× 成本超额** | 绝对年化 | 绝对回撤 | β |
|---|---|---|---|---|---|---|---|
| **R0 满仓（基线）** | 1.00 | **+15.1%** | **+11.9%** | **+7.1%** | **+21.0%** | 46% | 1.08 |
| R1 regime 三档（牛1/震0.5/熊0） | 0.54 | +1.2% | -3.5% | -6.0% | +7.7% | 38% | 0.57 |
| R2 系统性风险截断 | 0.98 | +14.5% | +9.8% | +5.1% | +19.0% | 50% | 1.04 |
| R3 MA60 开关 | 0.54 | +6.6% | -2.1% | -4.7% | +9.2% | 41% | 0.57 |
| R4 MA60×regime | 0.45 | -1.1% | -6.1% | -8.1% | +5.5% | 40% | 0.47 |

- **满仓在收益/成本门槛/绝对收益三项上都最好**；择时规则只把 β 从 1.08 压到 0.45~0.57
  （回撤省 5~8pp，代价是年化少 11~15pp）→ **"择时"实质是减仓，不是 alpha**；
  真想做风控，用固定现金比例更干净（同样的 β 下降，不用承担择时错误）。
- 副产品：**中盘域组合通过成本门槛**（2× 成本 +7.1%~+11.8%）——与 top-300 大盘域（-4.2%，不通过）对照
  → **效应集中在中小盘**，与"微盘/反转在中小盘更强"一致。
- `reward.evaluate()` 新增 `scale` 参数（逐日仓位系数，调仓成本随比例缩放）——择时/仓位实验通用。

## 新信息维度测试（2026-09-23，结论：全部无增量）

在中盘域（601~1800、1200 只）对固定因子组合做增量 A/B（K=50、H=5、654 个样本外交易日、裁尾口径），
把 14 个候选因子**逐个**加进等权 rank 组合，看增量与分层：

| 数据源 | 因子 | 分层跨度（裁尾） | 增量 A+−A |
|---|---|---|---|
| 资金流 `fund_flow_daily`（5205 只/2010 起/日频） | 主力净流入 5 日、20 日、加速、超大单、净占比 | FF_MAIN20 **单调递减** +0.034→-0.410 | -0.10 ~ -0.49（全负） |
| 两融 `margin_daily`（4639 只/85% 覆盖/日频） | 融资余额 5 日变化、融资买入占比 | ≈0 或非单调 | -0.17 ~ -0.34 |
| 股东户数 `holder_count`（季度，**有 announce_date**） | 户数环比（取负=筹码集中） | -0.142→-0.075（弱正向） | -0.081 |
| 基金持仓 `fund_hold`（季度，滞后 90 天） | 持仓变动%、持有基金家数 | 递减（基金增仓→更差） | -0.18 ~ -0.24 |
| 估值 `fundamental.db`（**pe_ttm/pb，5179 只/2018 起/日频**） | 1/PE、1/PB、合成、亏损标记 | ≈0（无单调） | -0.26 ~ -0.30 |

**唯一结构发现**：20 日主力净流入与未来 5 日**单调负相关**（持续流入→跑输）——即**反转信号**，
而反转已在组合的 -RET1/-RET5 里，所以**冗余而非增量**。其余维度全部无效。
→ 不要再用这些数据源找 alpha（除非换用法：事件驱动/极端值/行业相对）。
→ **`daily_basic`/`share_float` 是空表**（估值只有 `fundamental.db` 的 pe_ttm/pb）；
**板块动量测不了**：`stock_sector` 只覆盖池内 25%，`sector_data/sector_board` 只有当日快照。

## 组合构建与执行层（2026-09-23，中小盘域 654 个样本外交易日、裁尾口径）

**持有期 × 持仓数 × 成本**（可买池＝剔除次日涨停/停牌；年化按 250/H 折算，成本按单边×2/H）：

| 配置 | 年化毛 | 净@5bp | 净@10bp | 净@20bp | 净@30bp | 真实换手/次 |
|---|---|---|---|---|---|---|
| K=20 H=5 | +11.7% | +6.7% | +1.7% | -8.3% | -18.3% | 76% |
| **K=20 H=10** | +10.3% | **+7.8%** | **+5.3%** | +0.3% | -4.7% | 76% |
| **K=20 H=20** | +8.0% | +6.7% | **+5.5%** | **+3.0%** | **+0.5%** | 76% |
| K=50 H=10 | +7.3% | +4.8% | +2.3% | -2.7% | -7.7% | 69% |
| K=100 H=10 | +4.2% | +1.7% | -0.8% | -5.8% | -10.8% | 62% |

- **集中度**：K=20 ≫ K=50 > K=100（信号集中在最前面几只；分散化在这个信号上是负贡献）
- **持有期是对抗成本的唯一有效杠杆**：H=5 只在 ≤5bp 费率下活着；H=20 即使 30bp 仍为正
- **可交易性折损 ≈ 0**：Top50 里平均只有 0.2 只不可买（9.1% 的日子有），折减 0.002%
  —— 因为组合偏好"跌过的票"（反转），很少涨停；不可买那 0.2 只本身超额 +0.66%（追不上就放弃，代价可忽略）
- **净值视角（含小盘 beta，非重叠调仓）**：K=20/H=20 年化 +34.7%、最大回撤 30.4%、年化波动 55.9%、胜率 56.2%；
  同期等权池 +70.9%（≈21%/年）→ **绝对收益里大部分是池的 beta + 高波动，真正的"选股 alpha"是相对池的 +8~10% 毛 / +5% 净**
- 结论：**默认建议 K=20~50、H=10~20**（成本假设 ≤10bp）；该组合波动 55~63%、回撤 28~37%，
  必须配合仓位管理（AI 操盘手的纪律规则体系正是为此）

## 事件驱动研究（2026-09-23，结论：热点事件全是**负**期望）

中小盘域（601~1800）、2024-01~2026-09、T+1 开盘买入持有 5 日、裁尾 ±20%、
**已按同日 RET5 分位匹配对照**（剥离动量混杂）：

| 事件 | 样本 | 事件组 5 日超额 | 同分位对照 | **净效应** | 胜率 |
|---|---|---|---|---|---|
| 首板（涨停） | 2089（3.6/日） | -1.404% | -0.237% | **-1.166%** | 40.5% |
| 连板≥2 | 626（1.8/日） | -2.722% | -0.385% | **-2.337%** | 37.8% |
| 跌停 | 3699（8.4/日） | -1.306% | -0.169% | **-1.137%** | 39.4% |
| 龙虎榜净买强（净买/成交≥10%） | 1315（2.4/日） | -2.347% | -0.277% | **-2.070%** | 35.4% |

→ **"涨停=很强、跌停=超跌该反弹、龙虎榜净买=有资金" 三种直觉在该域该期间全部不成立**；
追热点的期望是负的（-1.1~-2.3%/5日）。这是**回避清单**级的证据，不是买入信号。
已接进 AI 操盘手上下文（`context._event_evidence()` → `event_evidence` 块），
因为它偏动量/主题风格 —— 事实给它，决定权仍归它（并提示样本仅两年多、别当铁律）。

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
| `smb.py` | 规模因子（SMB 小−大）+ 月度「最小市值 N 只」策略；市值口径 = **成交额 ÷ 换手率**（免疫复权）；剔除规则全 as-of；`--include-bj` 把北交所纳入股票池（默认不含，含时自动跑一遍不含的对照组） |
| `paper_portfolio.py` | **组合纸面盘（前向记录）**：用固定因子组合（K=20/H=10、中盘域、每日 1/H 分仓、单边 10bp 成本）**每天真实往前跑**，状态 `data/paper_portfolio.json`（持仓/分仓/净值历史），同日幂等；接进 `update_daily` ㉑ 步；API `/api/alpha/paper`；前端「策略 → 因子挖掘 → 组合纸面盘」。目的=把回测结论变成不可回看、不可调参的**前瞻**记录。
  **异常通知**（走 `notify.push`，前端 NotifyBell 可见 + 可选 webhook）：① 单日净值跌幅 ≤ **-3%**；
  ② 从峰值回撤 ≤ **-10%**（阈值在 `config` 里可调）；③ **`check_staleness()`**：落后最新交易日 > 2 天
  （"跑没跑"）→ 由 ㉑ 步每日调用，㉑ 步失败会写 `{'error': ...}` 从而进当天的失败汇总通知 |
| `allocation.py` | **通用多腿组合构建器**：腿 = `smb` / `equal` / `etf:<code>` / `file:<path>`；输出相关矩阵、固定配比网格、自动配比（等权/逆波动/最小方差/最大夏普）；**滚动样本外**（`--rolling --window 36`）每月只用过去 N 月估权重 |

**API**：`/api/alpha/{meta,mine,walkforward,runs,run/<id>,composite,zoo,composite_report,factor-analysis,smb,allocation}`（`allocation` 支持 `rolling=1&window=36`）、
`/api/trader/selection?source=scorecard|composite|smallcap`、`/api/report/{composite,factor-zoo,factor-analysis,backtest,smb,allocation}`、
`/api/notify/{list,summary,read,clear,settings,test}`、`/metrics`（Prometheus 文本）。

**已证实 / 已否定**（300 只流动股 × 2016-2025，数据见 `data/factor_*.json`、`data/alpha_*.json`）：
- **公式搜索无效**：搜出来的“最优公式”样本外不如同预算随机对照（搜索−对照 −14.3pp，仅 2/10 折更好）。
- **固定因子组合有效（2026-09-24 修正）**：短期反转 + 小市值 + 远离 60 日高点。
  **排序稳健**：严格 as-of 池下多空价差仍 **+9.0%/年**（夏普 0.47）、IC 0.016；
  **但多头超额脆弱**：10 折均值从 +10.1%/年（前视池）**降到 -0.3%/年**（严格池），中位 +4.9%/年、7/10 折为正
  —— 引用组合超额时**必须注明池口径**，且不要把"多头 vs 等权池"当作稳定 alpha。
- **低波动类因子在本土是反向的**（高波动占优）：-ATR14/-AMP 多空价差 -28%/-45%，“超额为正”是风格 beta。
- **机器学习（HGB）的极端分位含真实信息**：多空价差均值 **+32.2%、9/10 折为正**（截尾 ±11% 复算仍成立），但整体 IC ≈ 0。
- **IC 口径陷阱**：计算 IC 时**不能叠加“次日涨停不可买”过滤**（信号恰好集中在这些样本，会把 IC 抹到 0）；可买性只约束组合构建。
- **微盘效应集中在北交所**（2026-09-14 补齐北交所数据后）：全市场流通市值最小的 15 只里 14 只是北交所（920xxx）——原先“最小 5 只”永远落在沪深小票，**与外部实证不是同一个股票池**，这是此前结论不一致的主因。同门槛同成本对照：2016-2025 含北交所 **+13.0%**（t=1.51）vs 不含 +9.3%；北交所成立后（2021-11 起）**+19.5%** vs +9.9%。但**成本是生死线**（单边 0.5% 时 +13.0% → +0.2%）、回撤 55~63%、持仓市值 3 亿级 → 只能小仓位卫星，不能当主力。
- **组合配比不能用样本内最优**（`allocation.py` 滚动样本外）：逆波动 1.38→1.32（几乎不衰减）、最小方差 1.43→1.25、最大夏普 1.45→**1.16**（衰减最狠）。只用风险信息的配比才稳。

**数据可靠性**（实测教训）：`py_mini_racer`(新浪 V8) 并发下会崩进程 —— `update_daily` 等长跑路径 **≤12-16 并发**；
**批量补数据一律走多进程**（`ProcessPoolExecutor`，每进程独立 V8 上下文）：实测线程 6 并发即崩，
`scripts/rebuild_bj.py` 用 4 进程 4.4 分钟补完 343 只北交所、0 失败（崩溃自动降并发重试）；
`update_daily` 的全市场增量已改为固定回看 10 个交易日（原全局缺口判断会漏“某天只有部分股票更新”）；
`scripts/backfill_missing_day.py` 用于逐股票补齐残缺交易日（分块落库、可续跑）。

**股票池覆盖**：`kline.db` 现有 5,554 只 active（沪深 5,211 + **北交所 343**）。北交所 2026-09-14 前完全缺失，
由 `scripts/rebuild_bj.py` 补齐（`ak.stock_info_bj_name_code()` 名单 + 新浪 `stock_zh_a_daily(bjXXXXXX, qfq)`，
2010-12 起 28.9 万行）；`codec.is_bj_code/ak_symbol` 已识别 43/83/87/88/920 段 → `bj` 前缀，
`update_daily` 的全市场增量自动带上北交所，无需手动维护。

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
| Scripts | `scripts/rebuild_bj.py` | **北交所全历史首拉**（343 只/28.9 万行，多进程幂等可续跑，2026-09-14）；新浪 `stock_zh_a_daily(bjXXXXXX, qfq)` 主源，东财兜底；之后由 update_daily 自动增量 |
| Backend | `scripts/rebuild_etf.py` | ETF 全量历史首拉(多进程, 1606只/144万行, 幂等可续跑); update_daily ⑫步每日增量 |
| Backend | `backend/api/blueprints/fund_flow.py` | **资金流**: `/api/fund-flow/kline` 个股日频资金流历史; kline.db `fund_flow_daily`(主力/超大/大/中/小单 额+占比, 东财daykline全历史) |
| Scripts | `scripts/rebuild_fund_flow.py` | 资金流全量首拉(多进程幂等); `probe_fund_flow.py` 东财反爬探测+速率测试; update_daily ⑬步每日增量 |
| Backend | `backend/api/blueprints/lhb_margin.py` | **龙虎榜/融资融券**: `/api/lhb`(单股/最近明细) + `/api/margin`(单股融资融券历史); lhb_daily 24.2万行(2010起) + margin_daily(2010-03起) |
| Scripts | `scripts/rebuild_lhb_margin.py` | 龙虎榜+融资融券全历史首拉(季度批次/按日16线程续跑); update_daily ⑮步回补 |
| Backend | `backend/data_manager.py` | `rebuild_period_kline`(周K/月K聚合: kline_weekly 293万行+kline_monthly 70万行) + `get_period_kline`; update_daily ⑭步增量 |
| Backend | `industry_pe` 表 + `/api/market/industry-pe` | **行业市盈率**(巨潮证监会行业分类 120 行业, 加权/中位/算术平均, 日频); update_daily ⑯步 |
| Scripts | `scripts/rebuild_chip.py` | **筹码分布全市场**(250天, 多进程每进程独立V8); `update_chip_all`; update_daily ⑰步每日重算 |
| Backend | `holder_count`/`fund_hold` 表 + `/api/holder` `/api/fund-hold` | **股东户数/基金持仓**(季度 2015-2026, 46期); `scripts/rebuild_holder.py`; update_daily ⑲步 |
| Backend | `board_list`/`board_daily` 表 + `/api/market/board/{list,kline}` | **概念/行业板块指数**(同花顺 374概念+90行业, 全历史 81万行, 数据当天有); `scripts/rebuild_board.py`; update_daily ⑳步 |
| Desktop | `dev.py`（根目录） | **一键开发环境**：后端+前端一起起，先检查 5000 是否被桌面版冻结后端占用（`--kill` 可停），`--port/--api-only/--web-only` |
| Desktop | `web/src-tauri/src/lib.rs` | 桌面壳：闪屏→主窗口、系统托盘、单实例、窗口记忆、开机自启、系统通知、`SC_DATA_DIR` 注入、后端日志落盘、端口复用检测 |
| Desktop | `web/public/splash.html` | 启动闪屏（品牌 + 进度条 + 三段状态），纯 HTML 随包分发 |
| Desktop | `web/src-tauri/make_icon.py` + `app-icon.png` | 应用图标母版（1024px）→ `cargo tauri icon` 生成全平台图标集（icon.ico 含 16~256） |
| Desktop | `web/build_desktop.bat` | 一键打包（vcvars64 → npm build → cargo tauri build --bundles nsis）；ASCII-only 避开 cmd 代码页问题 |
| Web | `web/src/lib/chartTheme.ts` | 图表主题：从 CSS 令牌解析颜色/均线配色/tooltip 样式，注册 `sc-tokens` ECharts 主题（切主题自动重建实例） |
| Web | `web/src/lib/tauri.ts` | 桌面能力桥（`isTauri()` 降级）：窗口控制 + `appReady/systemNotify/hideToTray/autostart/desktopPrefs` |

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

## 开发与调试（重要，2026-09-20 起）
**一条命令起开发环境**：`python dev.py`（后端 5000 + 前端 5173，Ctrl+C 一起停；`--kill` 先停桌面版后端，
`--api-only/--web-only/--port` 可选）。
- **别拿桌面版后端做开发**：安装的客户端常驻托盘并占用 5000，其后端是**冻结的旧构建** ——
  改 Python 代码不会生效却毫无报错，最容易误判"改了没用"。`dev.py` 会直接把它点出来。
- **并行联调**：`python run_web.py --port 5001` + `cd web && SC_API_TARGET=http://127.0.0.1:5001 npm run dev`
  （vite 的 `/api` 代理支持 `SC_API_TARGET`；前端 `VITE_API_BASE` 亦可用）。
- **浏览器开发不受桌面壳影响**：`isTauri()` 为假时闪屏/托盘/单实例/通知/等后端全部跳过。
- **调桌面壳本身**：`cd web/src-tauri && cargo tauri dev`（debug 构建不会拉起 sidecar，后端仍用 dev.py）。
- **前端校验**：`cd web && npx vue-tsc --noEmit && npx vite build`（本机 npx 不在 PATH 时显式用
  `C:/nvm/v22.23.2/node.exe`）。**改了 Rust 或 tauri.conf 必须 `cargo check`/重新 `build_desktop.bat`**，
  否则安装版还是旧的。

## Build
**Web 版(Tauri) — 一键脚本（内部处理 vcvars64，无需手动 activate）**:
```bat
rem 1) 后端 sidecar (PyInstaller, 含 akshare data)
python -m PyInstaller --clean --noconfirm package\stock_api.spec --distpath package\dist --workpath package\build_api
rem 2) 前端 + 外壳（vcvars64 → npm build → cargo tauri build --bundles nsis）
web\build_desktop.bat
rem 输出: web\src-tauri\target\release\bundle\nsis\股票教室_<版本>_x64-setup.exe
rem 安装：简体中文向导 / 当前用户安装 / 桌面+开始菜单快捷方式
rem 便携版: package\dist\stock-api.exe 与 web\src-tauri\target\release\StockClassroom.exe 放同目录, 旁有 data/ + backend/configs/
```
**前端校验**: `cd web && npx vue-tsc --noEmit && npx vite build`（本机 npx 不在 PATH 时用 `C:/nvm/v22.23.2/node.exe`）

## Dependencies
Core: `flask`, `akshare`, `pandas`, `requests`, `py_mini_racer`, `openai`
- 项目固定 venv `.update-venv/` (uv, 供每日自动化 update_daily.py) 装 akshare/pandas/openai/baostock.

## Git
Remote: `https://github.com/1479650473/stock-classroom`
- data/ 整目录 gitignored, 不入库; 临时 `_*.py/_*.png/_*.log` 不入库; api_key 绝不入库.
