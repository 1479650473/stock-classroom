# 任务文档 — 量化研究/LLM 交易员里程碑

> 版本 v4.2+ · 最后更新: 2026-08-24 · 对应 `docs/RESEARCH_AGENT.md`

本表追踪"**大模型驱动的 A 股量化交易员**"任务的里程碑、提交与验证状态。
目标闭环：`LLM 研究代理生成策略 → 历史回测 → LLM 基于反馈迭代优化 → 最优策略上模拟盘 → 收益对比`。

## 里程碑

| # | 里程碑 | 提交 | 说明 | 验证 |
|---|--------|------|------|------|
| M0 | 量化研究底座 | `bf4e9ca` | 声明式策略契约 + A股回测器 + 标的目录 + 指标 | 垂直切片自检过 |
| M0.5 | 宏观 context 层 | `2477751` | 影响 A 股的全球宏观指标/regime(macro.db) | 11 指标 OK |
| M1 | Agent Gateway + MCP 骨架 | `fc6a47d` | 能力分级 R/W/B/T、异步回测 job、paper-only、18 工具 | 冒烟 36/36 |
| M1 | 保护引擎移植 + gap 成交修复 | `5de4c12` | 更诚实的回测(跳空破止损→按开盘) | 保护 10/10 |
| M1 | codec 规范化 + 数据源韧性 | `e6f1b4d` | 治本撞码(000001 不猜)、限流/重试/UA | codec 21/21 |
| M1 | 研究代理主循环 | `89cbd55` | 生成→回测→复盘→择优→paper 闭环 | 11/11 |
| M1 | 契约安全补强 | `e700fe6` | DSL 操作符白名单(防静默死策略) | validate 全拒 |
| M1 | AI 决策门 + M2 宏观选板块 + 因子研究 | `ff1db81` | 结构化决策门、宏观条件化选板块、IC/ICIR | M2 14/14 |
| M2 | 因子研究接进闭环 | `35516a5` | 研究→论证→生成(选中因子进契约) | 11/11 |
| M2 | 因子库扩充 + ICIR 自动选参 | `2f73ec2` | 动/反/波/RSI 多窗口 + ICIR 分档置信度 | M2 29/29 |
| — | 真 LLM 端到端 | `cb6a958` | LLM 基于研究因子+决策门生成/复盘；DSL 字符串阈值修复 | verify_llm_run |
| — | 价值/质量因子研究 | `64f56eb` | 东财每日估值 → EP/BP/ROE(扩展单日K线之外) | M2 34/34 |
| — | 价值研究扩到跨板块 | `d850052` | 行业中性化 + 287只/25板块池 | 跨板块 8/8 |
| — | 全市场价值研究管线 | `00a4694` | FULL 模式(万只级/5191)+ 可恢复预抓 | FULL 4/4 |
| 价值/质量因子进策略(DSL) | `edc13d0` | EP/BP/ROE 可被策略引用并回测 | 价值策略 4/4(+53.7%) |
| 数据缺口修复 | `598f753` | 深市主板块补齐 9→611 根；catch_up_missing 容错 | 82→14 只短 |
| metrics 口径统一 | `f9bc837` | 收益/回撤/胜率改标准小数(0.537=53.7%) | 全回归绿 |
| — | 价值选股(全市场实证标定+LLM生成) | `b3b9432` | factor_selector 标定 + LLM 生成低PB选股 + 决策门 | verify_value_selection |
| — | 价值叠加层+跨周期稳健性+三分离方法论 | `9215315` | 价值作过滤/择时叠加层(证伪) + 2023-2026 逐年稳健性 + RESEARCH_AGENT 三分离 | overlay/cycle |
| — | 价值 regime 开关+价值tilt接决策门+补抓历史K线 | `8529196` | value_tilt_state + 决策门tilt + verify_value_regime + prefetch_kline_history | regime/gate |
| — | 价值 regime 开关升级+value_tilt硬裁决+因子×景气周期框架 | `d579ea3` | 价值价差自指开关 + value_hard_rule + factor_cycle矩阵 | regime2/gate/facycle |
| — | 组合级价值tilt+市场宽度第三路信号+多因子分层 | `7b2c333` | 价值升级为组合层(权重tilt) + 破年线宽度信号 + 分层而非独立回测 | pf/tilt_alloc |
| — | 重平衡选股器+NET计成本+全局寻优+多窗口 | `b6aa4c9` | portfolio_rebalance(接portfolio_value_alloc) + ResearchLoop.portfolio_paper 挂进主闭环 + NET分层保留/tilt不增价值(修正) + 训练/验证分离 + hp多窗口 + HP=5断点机制(纯成本) + 框架/优化脚本彻底对齐 | pfopt/paper/hp5/loop |
| — | 按持有期自适应配置器+多期forward+降频结论 | `9d09f29` | adaptive_config_for_hp(HP_LAYER_MIN=20, 规则化) + forward_paper_run(多期调仓循环) + 分层HP20>HP5>价值HP5→保持分层+慢调仓 | aft/fwd |
| — | **数据时效三层根治** | `2dae4fa` | 三源回退+硬超时 / update_codes 缺口窗口 / _as_of 基本面感知(取kline+BP齐备日) | as_of 07-03→08-24 |
| — | **每日数据自动化** | `740f19b` | update_daily.py + Windows 计划任务(15:40); 项目固定venv; 交易日跳过; 数据管道面板显示自动更新状态 | schtasks 跑通 |
| — | **精确回测指标 + 策略条件原理** | `70a04b2`/`f169048` | metrics.full_metrics(α/年化/夏普/sortino/Calmar/胜率/β) + describe.describe_contract(中文买卖条件) | 5策略带精确指标 |
| — | **自主策略进化闭环** | `5a92e84` | optimize_loop: 家族指标→LLM/Stub提新因子契约→回测→裁决(不盲从AI)→模拟盘+每日交易 | 真实LLM闭环跑通 |
| — | **前端可用性重构** | `bd8db84` | 导航分组(核心工作流/数据工具) + 总览landing页 + 账户中心(改名/重置/删除) | 渲染目检通过 |
| — | **账户净值曲线 + 主功能带参跳转** | `57ab58a`/`64b783d` | account_nav快照表 + MiniNavSpark + navigate(payload)带参跳转 | 净值快照真实累计 |
| — | **K线右栏抽屉 + 无边框标题栏** | `a9fee71` | 右栏=按需抽屉(非常驻) + WM_NCHITTEST无边框自绘标题栏 | 截图目检通过 |
| — | **调度修正(17:00)+源新鲜度校验+多策略OOM** | `ff17c59`/`a91770e` | 新浪当日数据15:40常未到→改17:00; K线未覆盖当日→警告; 多策略循环del+gc防OOM | as_of 08-27 5/5策略OK |
| — | **消息/资讯双模块(LLM介入主观内容)** | `c8a1d26`/`d863f7e`/`53252bf`/`67ec6c8` | 豆包搜索客户端 + 🅱️事件驱动池(涨停+热点板块,isolated不进长期策略) + 🅰️个股资讯深挖(豆包搜公司资讯→LLM独立主观判断) | 冒烟:事件池36只/长飞光纤保持/天通股份剔名 |
| — | **市场环境regime感知+权重动态化** | `909e88d`/`32439c5` | A股牛/熊/震荡分类器(hs300) + 系统性风险截断 + 因子权重随regime动态 | 看盘页环境条显示, 震荡→建议F价值Tilt |
| — | **卖出门三驱动+完整生命周期验证** | `c7a20f1`/`5aca141`/`63375ed` | 条件止损(8%)+移动止损(10%/15%激活)+策略卖出(无止盈) + verify_full_lifecycle逐日回放 | 三驱动+36.3%回撤-12.9% vs 无保护+40.2%回撤-19.0% |
| — | **分周期测试+样本外验证** | `0f5ab49`/`40d9767` | cycle_test(牛/熊/震荡/全周期/样本内外) + **2023 K线缺口修复**(补240只) | 全周期-25.8%→+98.3%, 样本外+25%未过拟合 |
| — | **判断器驱动周期策略轮换** | `f19c847`/`010c03a` | STRATEGY_ENV数据驱动重写 + rotate_strategy + rotated_contract + portfolio_paper自动切换 | 牛→B反转/震荡→F价值Tilt/熊→C低波动 |
| — | **核心循环文档** | `33de334` | docs/Trading_Loop.md(核心循环权威文档) + README功能表/核心循环小节 | — |
| — | **完整回测指标** | `39848ba`/`781a05e` | 日期区间隔离(start_date/end_date) + α/β/γ(信息比率) + 交易频率/交易总次数/胜率/盈亏比; 修pnl=0 bug(二次遍历依赖已pop cost_basis) + 前端摘要卡7→12项 | 5策略完整指标(夏普/α/β/γ/交易) |
| — | **价值tilt信号激活** | `7f578a0` | _calc_value_spread(BP因子longShort近4期价差) + plan_at补算 → w_value在1.5/0.3/1.0摆动, F价值Tilt/D多因子彻底区分 | F+35.1% vs D+41.8% 不同 |

## 关键验证汇总(2026-08-24，工作区干净)

| 项 | 结果 |
|----|------|
| 研究代理闭环(Stub) | 11/11 |
| M2(宏观选板块+IC/ICIR+决策门+价值) | 34/34 |
| 价值策略(EP/BP 回测) | 4/4 · 600036 +53.70%(跑赢买入持有 26.35%) |
| 跨板块价值研究 | 8/8(287只/25板块) · BP 中性化 ICIR 1.67 |
| 价值选股端到端(LLM生成) | verify_value_selection(3/3 段) · 见下方诚实结论 |
| 价值作为过滤/择时叠加层 | verify_value_overlay · 纯价值≈买持; 价值+MA20趋势更差(抖出轨, +7.74%); 趋势确认入场+价值离场 +18.70% |
| 跨周期稳健性(BP) | verify_value_cycle · IC 4/4 年为正(1.54~1.90); 选股组合 2/4 跑赢(2023/2024弱市赢, 2025/2026成长输) |
| 价值 regime 条件化开关 | verify_value_regime · GROSS 纯价值+46%>宽基+29%, 但开关+38%未跑赢纯价值(简单SH指数规则过度转向宽基); NET 同序 |
| 价值 regime 开关升级 | verify_value_regime2 · 价值价差自指开关=纯价值+46%(29/44期持价值) 跑赢SH指数开关+44.8% |
| value_tilt 硬裁决 | value_hard_rule · 策略引用价值因子+headwind → 强制hold(即使signal=True); 动量策略不强制; 实测通过 |
| 因子×景气周期矩阵 | verify_factor_cycle_2018 · BP IC 四期皆正(唯一); MOMENTUM/MOMENTUM_20=反转(负IC); VOLATILITY=低波动异象 |
| 组合级价值tilt+分层回测 | verify_portfolio_framework/optimize(2500幸存池) · 分层 D 2.823>最佳单 C 2.719>买持 1.986(净 2.520>2.389>1.985); tilt(GROSS F 2.818≤D/E 2.784/G 2.758, NET F 2.505<D) → 不再推崇; 两脚本已彻底一致(D/F 同值) |
| HP=5 断点机制 | verify_hp5_mechanism · HP=5 分层 GROSS 3.065>最佳单 2.649(模型仍占优) 但 NET 2.381<2.466(被成本击穿, 成本拖累+33.13%, 换手0.302 vs 价值0.086) → 断点是'纯换手成本'非模型; HP=20 成本拖累仅16.6% 净仍优 → 分层用HP≥20 |
| 组合重平衡器接进主闭环 | ResearchLoop.portfolio_paper · RebalancePlanner(接portfolio_value_alloc) 读账户现金/持仓→目标组合→reconcile→逐笔paper_order(7只全部成交, 持仓7/现金4583) ; verify_portfolio_paper_loop |
| 权重寻优(训练→验证) | verify_portfolio_optimize · 训练最优OOS 1.411>等权1.345(略优) 但<简单tilt 1.439, 上界1.473 → 样本内~4.4%, 寻优价值有限 |
| 组合值tilt分配器(生产) | portfolio_value_alloc(三路多数决→w_value) + market_breadth · verify_portfolio_tilt_alloc 确定性全过 |
| 价值 tilt 接进决策门 | value_tilt_state 感知 → risk_on 时 value_headwind, 决策门 hold 并引"价值短期跑输" |
| 补抓 2018-2022 历史K线 | prefetch_kline_history 三轮已全部完成(5191只, kline_2018 1→3338) · 真熊市跨周期已解锁 |
| 真 LLM 端到端 | LLM 用研究因子 MOMENTUM_5 生成策略，决策门 LLM 推理 hold |
| 垂直切片(回测引擎) | ✅ 自检过 |
| 保护引擎 | 10/10 |
| Agent Gateway 冒烟 | 36/36 |
| codec | 21/21 |

## 当前状态

- ✅ **全市场基本面建库完成**：5164/5191 只(99.5%)。全市场价值研究**终验 4/4**。
- ✅ **数据时效已根治**：as_of 从 2026-07-03 → **2026-08-27**（数据最新）。三源回退+硬超时+update_codes 缺口窗口+_as_of 基本面感知（提交 `2dae4fa`）。
- ✅ **每日自动更新落地**：`update_daily.py` + Windows 计划任务 `StockClassroom-DailyUpdate`（周一至五 **17:00**，app 关闭也跑），项目固定 venv `.update-venv/`。4 步：量化池K线/基本面/纸面盘/账户净值快照。
- ✅ 数据已本地化(读路径只读缓存)，见 `verify_local_cache.py` 4/4。

## 数据库库存 & 数据打理 (2026-08-25)

**6 库**（均 `data/`，`integrity_check` 全 ok）：
| 库 | 内容 | 截止 |
|---|---|---|
| `kline.db` (1.09 GB) | 日线年度分区 `kline_2000..2026` + `kline_daily` **视图**（UNION ALL 分区）；周线/筹码/龙虎榜/北向/板块/涨停/涨跌家数 | **2026-08-26** (5,206 只, 08-27 池 287 只已补) |
| `fundamental.db` (706 MB) | `fundamental` 单表：code/date/pe_ttm/pb | 2026-08-27 (池 287 只, 全市场 08-24 5,165 只) |
| `macro.db` | `series` 10 指标 + `regime`（仅最新日） | 2026-08-24 |
| `stock_cache.db` (908 KB) | `stock_spot` 实时快照 | ⚠️ 2026-07-23（刷不动） |
| `sim_trade.db` / `agent.db` | 模拟账户(含 account_nav 净值快照) / Agent 任务 | — |

**本次打理**：
- 删弃用死表 `kline_daily_legacy`（3.41M 行，纯冗余；代码里 `datacenter/panel.py:225` 早已跳过它、视图/写入路径均不含它）。**删前**把分区缺失的 **4,235 条**日线（含平安银行 `000001` 全历史 2000-2024 缺口）无损迁入分区，验证 0 条丢失。
- `VACUUM` kline.db：**1642 → 1088 MB（-554 MB）**；stock_cache.db **4144 → 908 KB**（78% 碎片）。
- 备份 `data/kline.db.bak`（1.72 GB）保留，确认无误后可删。

**已知外部限制**：`stock_spot`/`fund_flow` 均走**东财接口，被反爬掐断**（`akshare_source` 注 `2026-07-08 Connection aborted`），当前无法刷新；日线/基本面/宏观由新浪等通道照常更到昨日。

## 全市场价值/质量因子终验(5149 只可研究)

| 因子 | IC | ICIR | 解读 |
|------|-----|------|------|
| **BP**(账面市值比) | 0.041 | **1.54** | 全市场最强价值因子，低PB→高收益 |
| EP(盈利收益率) | 0.023 | 0.83 | 中等价值信号 |
| ROE(质量) | -0.004 | -0.23 | 跨市场不显著(质量-ROE 偏板块内，如银行池强) |

覆盖 65%（小盘/新股估值稀疏）。

## 诚实记录 / 待办

- **LLM key 已配置** `backend/configs/settings.json`(deepseek，**非 git 跟踪**)；端到端入口 `verify_llm_run.py`。
- **诚实修正**：此前后台全量抓取曾因 `build_full_pool` 旧路径启动即崩溃，已修复并重新启动(见 `00a4694`)。
- **口径**：`run_backtest` 与 gateway 本同口径；统一为小数仅为消除"存百分数→再×100"歧义。
- **已知限制**：截面 IC≠单标的择时；**截面 IC≠长期多头组合跑赢宽基买持**(价值 IC 真实但弱、短周期；成长领涨的 risk-on 里价值跑输宽基，见下方诚实结论)；全市场抓取无批量接口(逐股)；财报估值用每日 PE/PB 天然点时间。
- **价值选股诚实结论(2026-08)**：BP 全市场 IC 0.042/ICIR 1.40(@周, 多空+2.27%)，但长持多头"低PB选股组合" +29%~+44% vs 等权买持基准 +51.34% → **未稳定跑赢**；价值 alpha 短周期(月度多空转负 -6.52%)、2026 年价值组合 -4~-9% vs 基准 +3%；决策门返回 hold。→ 价值因子作为*截面 tilt 信号*有效，但纯多头低PB组合不能像宽基一样吃到成长上涨；后续应把价值作为**多因子/择时过滤**而非独立满仓选股信号。
- **价值作为过滤/择时叠加层(证伪)**：单独价值择时 ≈ 买持(10只 +24.06% vs +23.96%, 5/10跑赢, 无可靠超额)；加 `CLOSE>MA20` 趋势叠加反而**更差**(抖出轨切碎:+7.74%, B笔16-34 vs A笔2-11)；"趋势确认入场+价值离场"(D) 也仅 +18.70% 不敌纯价值。→ 价值是弱的独立信号, 朴素 MA20 趋势叠加不助益。
- **跨周期稳健性(补抓后含真熊市 2018/2022)**：`prefetch_kline_history.py` 补抓 2016-2022 后，`verify_value_cycle_2018.py`(2500池) 实测：**IC 4/4 期皆为正**(2018 0.047 / 2019-21 0.026 / 2022 0.090 ICIR1.60 / 2023-26 0.055) → "IC 真实但弱、跨周期普适(含真熊市)"**强成立**；**选股组合 2/4 跑赢买持——恰是 2018/2022 两个熊市**(2018: 组合 -26.20% vs 宽基 -31.54%；2022: +0.43% vs -10.83%, 多空 +25.21%)，在成长/修复期(2019-21/2023-26)跑输。**结论: 价值=防御/轮动倾斜(熊市抗跌、成长踏空), 非独立超额; 已被两个真熊市彻底验证。**
- **价值 regime 条件化开关(升级)**: 朴素 SH指数趋势开关(弱→价值/强→宽基)在 2023-now **未跑赢纯价值**(GROSS 开关+38% vs 纯价值+46%)——过度转向宽基。**升级后用『价值价差滞后动量』做自指信号**(`verify_value_regime2`): 价值自身在工作→持价值, 否则持宽基, 结果=纯价值(+46%, 29/44期持价值)并跑赢 SH指数开关(+44.8%)。**结论: 用"价值是否在被验证"作开关, 比指数趋势更贴价值防御窗口。** 方法警告: value-vs-broad NET 随窗口/基准定义翻转。
- **value_tilt 硬裁决(已落地)**: `value_hard_rule` 在**策略引用价值因子(EP/BP/ROE) 且 value_tilt=headwind** 时强制性返回 hold(即使信号为真), favorable/neutral 放行。语义=防御/轮动: 成长领涨市强制暂缓价值多仓。在"因子×景气周期矩阵"里价值 BP 是**唯一四期 IC 皆正**的因子(防御层), 动量/波动为负IC(A股动量=反转、波动=低波动异象)。
- **引擎 RSI bug(已修)**: `factor_research._factor_panel` 曾检查 `fid=="rsi14"` 而实际为 `"rsi_14"`(带下划线) → RSI 研究被静默当成 momentum_20 算。已改 `fid in ("rsi14","rsi_14")`; 修复后 RSI_14 IC +0.035/ICIR 0.52(区别于动量 +0.068/1.02)。
- **补抓 2018-2022 历史 K 线(已完成)**: `prefetch_kline_history.py`(新浪全历史, 并发+单写连接, 可恢复) 分三轮补齐——①2016-2021 全市场(5191只, kline_2018 1→3338只) ②2022 顶补 ③2022 早段缺口(跳过判据改为检查 2022-01~06)。现在 2018-2022 全有广度。
- 后续候选：①把价值作为**多因子框架的防御层**做组合级权重(按景气期调价值tilt, 而非单票); ②value_tilt 硬裁决扩展到**组合级**(整个重平衡决策, 不只单票paper单); ③市场宽度信号(广度<50%→价值)做第三路开关验证。

## 2026-10-12 未落库改动盘点 + 密钥门禁 + 管道健康（C-01 ~ C-04）

> 背景：工作区积压 **44 项**未提交改动（29 修改 + 15 新增）。盘点时发现**已提交状态（HEAD）
> 本身是坏的**，见下。

### C-01 分类提交：44 项 → 13 个语义 commit

`git log --oneline -13`（新起 13 个提交，**未 push**）：

| # | commit | 内容 |
|---|---|---|
| 1 | `refactor(paths)` | 12 个模块统一走 `backend/api/paths.py` 的 DATA_DIR/KLINE_DB/PAPER_RUNS_PATH（frozen 安全） |
| 2 | `fix(agent)` | kill-switch 真正吊销 token（原 `revoke_token_record(0)` 是空操作） |
| 3 | `fix(pipeline)` | 手动触发改用 `update_daily.run()` 9 步闭环（原走旧单步入口，会漏 8 个步骤） |
| 4 | `fix(scheduler)` | 调度线程开机即起 + 默认时刻 17:00 |
| 5 | `fix(system)` | bootstrap 大表跳过 COUNT + 基本面表名 `fundamental_daily`→`fundamental` |
| 6 | `fix(trainer)` | `current_bar` 漏调 `()` + 参数整数校验 + `engine.open_orders`→`engine.orders` |
| 7 | `feat(trade)` | 下单参数校验 + 限价单保留挂单/顺带撮合 + 刷新价格对挂单撮合 |
| 8 | `chore(version)` | 版本号统一 5.1.0（pyproject 一直停在 0.3.0） |
| 9 | `feat(web)` | favicon + 零值不再染色 + 数据中心基本面"已就绪"兜底 |
| 10 | `feat(scripts)` | fund_flow 补漏 `--stale` + intraday 探测器崩溃自愈 |
| 11 | `fix(trainer-engine)` | 做空平仓余额方向（**如实收录，空头账务仍不正确**，见待办 T-ENC-01） |
| 12 | `fix(trader)` | LLM 调用指数退避重试（本次授权实施） |
| 13 | `fix(pipeline)` | 关键步骤失败应使 `ok=false` + 修复从未生效的通知通道（本次授权实施） |

**⚠️ 关键发现：HEAD 本身起不来。** `backend/api/server.py:74` 调
`scheduler_bp.ensure_started()`，但该函数**只存在于工作区、从未提交** →
已提交状态 `create_app()` 会 `AttributeError`，**后端根本启动不了**。
验证：`git grep -n ensure_started HEAD` 只命中调用点、无定义；工作区实跑
`create_app()` → OK（177 条路由）。提交 #4 已补齐，HEAD 现在自洽。

**保留未提交（15 项，均有意如此）**：
- 13 个 `scripts/_probe_*.py` / `_test_*.py` → 判为**一次性探测脚本**，判据：
  ① `.gitignore` 第 25-31 行**主动忽略**根目录 `/_*.py`、`/_test_*.py`（项目约定：下划线前缀=一次性）；
  ② 已入库的同类长期工具**不带下划线**（`scripts/probe_fund_flow.py`、`probe_intraday.py`，AGENTS.md 还写进 Key Files）；
  ③ 时间戳聚簇于 2026-09-26 06:11~09:16（约 3 小时），其中 `_probe_tdx/_tdx2/_tdx3` 22 分钟内连改 4 版；
  ④ 全仓库（含 docs）grep **零引用**。
  处置建议：**保持 untracked**（不移动 —— `archive/` 未被 .gitignore 忽略，移过去只是换个地方）。
  **不采纳**在 `.gitignore` 加 `scripts/_*.py`：该规则会无差别吞掉将来 `scripts/_utils.py` 之类**有引用**的模块（静默漏提交）。
- `backend/tushare_source.py` + `scripts/rebuild_tushare.py` → **待办**：未接进
  `update_daily`/pipeline，且 `pyproject.toml` 未声明 `tushare` 依赖（公开仓库里放一个
  import 即失败的模块是负资产）。**接好线 + 声明依赖后再入库**。
  另注：`settings.example.json` 目前**没有** tushare token 槽位，接线时一并补模板。

### C-02 密钥门禁（唯一真源：`<shared_workspace>/tools/check_secrets.py`）

本仓不再自带实现（原 `scripts/check_secrets.py` 已删除，避免双份逻辑）。门禁命令：

```bash
# 提交前（pre-commit 可用）
python "<shared_workspace>/tools/check_secrets.py" . --staged-only
# 推送前（必跑）
python "<shared_workspace>/tools/check_secrets.py" . --history
```

实测（2026-10-12，提交后复跑）：

| 模式 | 结果 | 退出码 |
|---|---|---|
| 工作区/已跟踪 | 383 文件，**0 命中**（高危 0 / 中危 0 / 低危 0） | **0** |
| `--staged-only` | 0 命中（暂存区为空） | **0** |
| `--history` | 383 文件 + **331 个提交**，0 命中 | **0** |
| 错误用法（`--staged-only --history`） | 互斥组拒绝 | **2** |

- 门禁契约：**0=干净 / 1=有命中 / 2=工具故障或用法错误**（2 与 1 分开，避免"工具坏了"被误判成"发现密钥"）。
- `backend/configs/settings.json` 仍**未被跟踪且被 .gitignore:44 忽略** ✓；
  跟踪文件里无 `.env` / `*.pem` / `id_rsa` / `.npmrc` ✓。
- 交叉核查（sec-backup-guard）：该文件在**全部 ref 的 26 个 blob 版本**里 `api_key` 均为空串或无该字段
  → **历史上从未提交过真实 key**；现网真实 DeepSeek key(35) / Tushare token(56) 全 ref `-S` 搜索命中数 **0**。
- 门禁自身修了一个真 bug：Windows GBK 控制台打印 emoji 会 `UnicodeEncodeError`，
  把"干净"误判成退出码 1 → 已改 ASCII 标记 + `reconfigure(errors="replace")`
  （本仓 383 文件 0 命中的结论即在此修复后才成立）。

### C-03 数据资产 / 磁盘

`data/` 合计 **14.16 GB**（15,203,041,280 bytes）：

| 库 | 大小 | 关键表（行数 / 最新日期） |
|---|---|---|
| `minute.db` | **8.16 GB** | `kline_min5` **86,419,554 行**，max(dt)=**202610121500** ✓ |
| `kline.db` | **5.14 GB** | `kline_daily` 视图 13,894,870 行；`kline_2026` max=**20261012** ✓；`fund_flow_daily` 13,703,473(max=20261009)；`chip_distribution` 1,361,900(2026-10-09)；`margin_daily` 6,680,484(max=20261008)；`limit_up` 1,549(20261009)；`north_flow` 2,765(2026-10-09)；`etf_daily` 1,471,750(max=20261008) |
| `fundamental.db` | 0.70 GB | `fundamental` 7,444,903 行，max=**2026-10-12** ✓ |
| `fund_arb.db` | 0.13 GB | `fund_nav` 849,794 / `lof_daily` 612,341，max=**2026-10-12** ✓ |
| `ai_trader.db` | 0.03 GB | `trader_decision` 584 / `trader_memory` 2,101 / `trader_profile` 20 |
| `macro.db` | ~0 | `regime` 192(max=20261012) / `series` 50,903(max=20261009) |
| `stock_cache.db` | ~0 | `stock_spot` 5,534(max=**2026-10-09**) |
| `sim_trade.db` | ~0 | `account_nav` 891(max=20261012) / `orders`、`trades` 各 333 |
| `alpha.db` / `agent.db` | ~0 | 研究/网关产物（`agent_tokens` 59） |

**空表**（AGENTS.md 已记 `daily_basic`/`share_float` 为空，实测确认）：
`daily_basic` 0、`share_float` 0、`dividend` 0、`name_history` 0、`fund_flow` 0 —— 正是 tushare 想接的那几张。

**磁盘**：`D:` 剩余 **44.13 GB**（PM 接手时 44.2 GB，几乎无变化）。`data/` 14.17 GB + `web/` 2.17 GB
（`node_modules` + Rust `target`）+ `package/` 0.27 GB + `.update-venv/` 0.17 GB。
`archive/` **仅 6 个文件 ~0.2 MB**（`pyqt5-legacy-2026-09-05.zip` 201 KB + 5 个 md）→ **无可清理大件**。
→ 结论：**没有可安全清理的大体积垃圾**；真正的空间压力来自 `minute.db`(8.16 GB) 的每日增长
（5min 线 1211 只，日增量约 12 个交易日 × 1211 × 48 根）。等 PM 决策是否降频/裁历史。

### C-04 数据管道健康（2026-10-12 那次 run）

`update_marker.json` 里 `ok: true`，但 `steps{}` 记录了 8 个异常步骤 —— **`ok` 与实际严重脱钩**。

**① `ok: true` 为什么是误导 —— 两个独立原因**
1. 顶层 `ok` 只由"整轮有没有异常抛到最外层"决定；步骤内部异常被 `try/except` 吞掉后
   只写进 `steps{}`、**从不参与 ok 判定**。
2. 更严重：`update_daily` 的**通知通道从来没发出去过**。它写的是
   `from notify import push`，而本脚本把 ROOT 和 ROOT/backend 都塞进 sys.path →
   `notify.py` 被当**顶层模块**导入，其内部相对导入 `from .api.paths import DATA_DIR` 直接
   `ImportError: attempted relative import with no known parent package`，
   又被 `except Exception: pass` **静默吞掉**。全仓库仅此一处写错
   （`jobman.py` 用的是正确的 `from backend import notify`）。
   → **即使 ok 曾经为 false，也不会有任何告警**。已修（commit #13，并改为写 warning 日志）。

**② AI 操盘手 3/3 全失败 —— 根因：运行时 LLM 连接失败（非 Key/账号/代码）**
- 日志：三个交易员逐字同构 `LLM 调用失败: Connection error.`（19:59:08 ~ 20:02:31），
  同一次 run 里第 4 个独立调用方 `stock_deep` 也是 `Connection error.` → 4 个调用方同时段全灭。
- Key 存在且格式正常（`sk-`+32，len 35）；用**管道自己的解释器**（`.update-venv`）实跑同一条
  `LLMClient().complete()` → **成功（6.47s）** → 排除 Key/账号/DB/代码。
- 旧重试只有 3 次 × 1.5s ≈ **5 秒**，对 DNS 抖动/连接重置无抵抗力。
- **慢性病，不是偶发**：17 个交易日里 **4 天（24%）3/3 全灭**（10-12 / 09-22 / 09-14 / 09-11），
  另有 4 天 1/3 失败。
- 已修（commit #12）：默认 5 次尝试 / 130s 预算 / 只重试 APIConnection+APITimeout+RateLimit。

**③ fund_flow 5205 + etf 1624 全失败 —— 瞬时源阻断，非接口变更**
- 跨 run 时间线（读 `data/logs/update_daily_*.log`）：**09-21~10-09 期间这两步天天 0 失败**
  （etf 更新 1624/1624；资金流更新 5205/5205），**只有 10-12 全灭**（etf 另在 09-14 全灭一次）。
  → **不是慢性、不是接口变更**。
- `update_daily` 日志中**没有**"时间预算用尽"告警 → 不是预算中止路径。
- etf 的 1624 次失败全部发生在**同一秒内**（`20:03:07` 的 `[50/1624]`…`[250/1624]`，elapsed 2.2s）
  → 每个 `_fetch` **瞬时抛异常**；fund_flow 约 1.5s/只。
- 现在实测两个取数函数**都正常**：`ak_fetch_etf_kline('510300')` → 3491 行/2.83s；
  `ak_fetch_fund_flow('600519')` → 4026 行/3.50s。
- 同一次 run 里 **新浪(日线)✅ / baostock(分钟)✅ / 同花顺(板块)✅ / fund_arb✅**，
  而 **东财系全挂**（fund_flow、lhb_margin `datacenter-web.eastmoney.com` HTTPS 失败、
  market_data 的 north_flow/lhb/limit_up 全 0）→ **判定：10-12 晚间东财系被阻断/不可达**。
- ⚠️ **根因无法事后取证**：`data_manager.update_etf_kline/update_fund_flow` 的
  `except Exception: rows = []` **丢弃异常、不写日志**，只把计数 +1。
  → 建议（未授权，待 PM 定）：把前 N 个异常的类型+消息记一次日志，否则下次仍只能猜到"源挂了"。

**④ audit 与本次 run 看似矛盾 —— 是"运行前审计"落进了运行后的 marker**
- `catchup.audit()` 在 `_run_inner` **开头**执行，读的是**上一次** run 的 marker 取 `last_run`
  （`last_run_info` 用 `finished`/`started`），并对窗口最后一个交易日 `ref=2026-10-12` 判缺失。
- 所以 `last_run=2026-10-11T17:01:36` + `ref=2026-10-12` **不矛盾**：前者是"上一轮"，后者是"本轮参考日"。
- 它报的 5 张表缺 10-12，是 **17:00 开跑前**的真实状态；跑完后 market_daily/board_daily 已补上
  10-12 ✓，而 limit_up(仍 20261009)、margin_daily(仍 20261008)、industry_pe(仍 20261009)、
  lhb_daily(仍 2026-10-09) **仍陈旧**。
- **真正的缺口**：`run_catchup()` 只在**非交易日**执行（`if today not in cal`）；
  交易日跑完**没有任何事后复核**，audit 的 missing 清单既没被补、也没被复检。
  → 即"补全审计在交易日只用于放大拉取窗口，不驱动补全"。

**⑤ 数据新鲜度结论（下游可用性）**

| 状态 | 数据 |
|---|---|
| 🟢 **可信、当日(2026-10-12)** | `kline_2026`/`kline_daily`、`kline_min5`(15:00)、`kline_weekly/monthly`、`fundamental`、`board_daily`、`market_daily`、`fund_arb`(lof_daily/fund_nav)、`regime`、`account_nav`、`paper_portfolio`(v1/rank2) |
| 🟡 **陈旧 1 交易日**（2026-10-09） | `fund_flow_daily`(← **stock-ml 的 FF 过滤信号读它**)、`limit_up`、`lhb_daily`、`industry_pe`、`north_flow`、`high_low`、`chip_distribution`、`sector_board`/`board_list`、`stock_spot`、`macro.series` |
| 🔴 **陈旧 ≥2 交易日** | `margin_daily`(2026-10-08)、`etf_daily`(20261008) |
| ⚫ **空表** | `daily_basic`、`share_float`、`dividend`、`name_history`、`fund_flow` |

**⑥ 本次已授权的两处修复（各自独立 commit + 自测）**
- commit #12 `fix(trader)` 指数退避重试：**44 项断言全通过**（不联网/假时钟/注入假 LLM）。
  真实 `decide()` 非流式路径（= 10-12 生产实际走的路径）：失败 2 次 → 第 3 次成功，退避实测
  `[2.12, 4.61]s`；全失败 → 恰好 5 次调用、退避 `[2.25, 4.11, 16.56, 52.09]s`；
  4xx → 只调 1 次零等待；流式已吐字 → 不重试；小预算 6s → 3 次即收手且累计恰好 6.00s。
  **算术提示**：5 次尝试只等 4 次 = 2+5+15+45 = **67s**（130s 是上限，第 5 档 60s 需 max_attempts≥6）。
- commit #13 `fix(pipeline)` 关键步骤 `ok=false` + 修通知通道：**44 项断言全通过**。
  **回归**：喂入 10-12 的**真实 steps** → ok 由 true 变 **false**，
  `critical_failed=[trader, etf, fund_flow]`，另识别出 lhb_margin/stock_deep/industry_pe/
  kline(5/5548 部分)/board；而 market_data(全 0)/fundamental(轮换空跑)/minute(rc=0) **不误报**；
  真实 `notify.push` 落盘 1 条 `level=error`、title「每日自动化关键步骤失败：trader、etf、fund_flow」。

## 2026-10-13 第二轮：PM 裁决 2~6 + T-DATA-02 / T-DATA-03

> PM 验收通过 C-01~C-04 后下达 7 项裁决 + 2 项新任务。本段记录执行结果与实测数据。

### 裁决 2：13 个探测脚本移出仓库（`scripts/scratch/` 约定）
移到**仓库外** `E:\小光工作区备份\stock-classroom_scratch_archive\`（13 个：`_probe_*` 9 + `_test_*` 4）——
既不销毁探测方法，也不让 `git status` 长期有噪声。**计数更正**：PM 记的是 10+4=14，实测 9+4=**13**
（另 2 个未跟踪文件是 tushare 那对，按先前裁决保持原样等接线，不属 scratch）。

**新约定**：将来一次性脚本放 `scripts/scratch/`，`.gitignore` 用**目录级**规则 `scripts/scratch/`。
刻意**不用** `scripts/_*.py` —— 那会静默吞掉将来 `scripts/_utils.py` 之类"有引用"的模块。

### 裁决 3：重试次数 5 → 6（算术自洽）
上一版按 PM 给参实现，但 **5 次尝试只会等待 4 次 = 2+5+15+45 = 67s**，第 5 档 60s 用不到，
"130s 预算"是永远够不到的上限。改 6 后等待 5 次 = **127s ≈ 预算 130s**。
> 诚实说明：10-12 故障窗口 **≥3.5 分钟**，**67s 和 127s 都活不过那一次** ——
> 真正管用的是"连接/读取分离超时"（见裁决 6），不是次数。

### 裁决 4：三类补充告警（批准保留）+ 三条约束（已固化进代码注释与测试）
- (a) 每步**最多一条**描述 → 整轮**合并为一条通知**（2 个异常步骤 → detail 恰好 1 个 `；`）
- (b) 非关键命中一律 **warn 级、不影响 ok**；只有 critical + 整体失败才 `ok=false`
- (c) `fundamental` 轮换空跑形状 `{updated:0, skipped:N, rotate:0}` 天然不命中 → 无周期性假告警；
  **刻意不按步骤名拉白名单**，否则它真正的 `{'error': ...}` 会被一起藏掉（已加测试锁定该行为）

### 裁决 5 / T-DATA-02：取数异常记前 3 条并入库
`data_manager._record_fetch_error()`：每步最多记 **前 3 条**（code + 异常类型 + 消息）写 warning，
**不逐条记**（5205 条会刷爆日志）；`update_etf_kline` / `update_fund_flow` 返回值新增 `err_samples`；
`update_daily` 把它纳入步骤 key 白名单 → 落进 `data/update_marker.json`；`_step_bad` 命中时把
**第一条样例**拼进告警文案（告警本身即可定位）。
**复现验证**：把 `akshare_source` 的两个取数函数替换为必失败版本 → 5 只全失败只记 3 条样例
（`510300|RuntimeError: Connection aborted...`）+ 3 条 warning。

### T-DATA-03：非交易日"假 ok"已修
早退分支原来自行写 `out['ok'] = True` 并直接落盘、**绕过 `_finalize_run`** → 那天补全失败也记成成功。
现改为 `return _finalize_run(out, lg, t0)`；`_finalize_run` 把 `out['catchup']` 一并纳入判定；
`CRITICAL_STEPS` 增加 `'catchup'`（触发面窄：只有 `run_catchup` 抛异常才写 `{'error':...}`，
正常/部分补全不误报；但"停机后补全失败"意味着数据**静默陈旧**，必须 ok=false）。

### 裁决 6：LLM 耗时分布实测（用于定 per-request timeout）

**A. 整次决策耗时**（`ai_trader.db`，n=534，`status=done` 且有 `finished_at`）
```
p50=69.0s  p75=90.0s  p90=123.0s  p95=144.3s  p99=193.7s  max=751.0s  mean=77.4s
```
→ 这是**整次决策**（含 40~60s 上下文构建 + 多轮 LLM + 下单），**不能当单次请求耗时**。

**B. 单次请求实测**（真实 18 工具集 + p90 体积上下文 25,173 字符 + `max_tokens=2600`）
```
短工具轮  n=5   p50=2.00s  p95=5.76s  max=6.45s  mean=3.03s
流式      n=2   TTFT=1.77~1.91s，总 1.91~1.98s
```
**C. 长生成**（`complete`, `max_tokens=2600`）：18.17s / 33.91s —— 可见输出仅 330/418 字符，
时间几乎全花在**思考 token** 上。

**D. 缺口**：`trader_decision.trace` 只有 `tool`/`args`、**没有单次调用耗时** → 历史上无法从库归因，只能实测。

**建议**（等 PM 定值）：用**连接/读取分离超时**而非单一总超时 ——
"p95 的 2~3 倍"两个口径都不适用（套决策级 p95=144s → 290~430s 太松；套单请求 p95=5.8s → 12~17s
会误杀 33.9s 的合法长生成）。正确做法：
```python
httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)
```
- **`connect=10s` 才是治 10-12 那味药**：连接期挂起 10s 即中止，不再由 SDK 默认值拖住
  （"预算只在失败后检查、单次挂起就不会触发重试"正是靠它解决）
- `read=180s`：覆盖理论最坏（2600 token 中文 @ ~15 tok/s ≈ 173s），是实测长生成 max 的 5.3 倍
- 边界：6 次尝试最坏 = 6×10s + 127s ≈ **187s**，与"180s 硬上限"意图吻合
- **流式需单独考虑**（首帧仅 ~1.9s、长生成期间持续有帧，不适合同一个总超时）

### 🔴 新发现 1（P1）：强制提交决策的 `tool_choice` 在思考模式下**必然 400**
实测同一 prompt/工具规格：
```
1) tool_choice={"type":"function","function":{"name":"submit_decision"}} -> 400 BadRequestError
   "Thinking mode does not support this tool_choice"
2) 不带 tool_choice（同 prompt/工具） -> OK 2.55s，模型自己调了 submit_decision
3) tool_choice="auto"                -> OK 1.58s
```
而生产 `backend/trader/agent.py` 的**强制提交路径**正是写法 1；`settings.json` 的
`model=deepseek-flash` 是思考模式 → **该兜底路径 100% 失败**，且异常被 `except Exception` 吞掉只
`emit` 一行，外层只看到"操盘手未能给出正式决策"。与库里对得上：
```
error 统计：42 × 操盘手未能给出正式决策   ← 最高频
           20 × Connection error
            3 × 402 Insufficient Balance   ← 新发现 2
            1 × WinError 10054
含 tool_choice 的显式报错：0 条（被吞，从未落库）；status=done 但 thinking 为空：7/538
```
→ **修法（未授权，等 PM）**：删掉 `tool_choice=`（或改 `"auto"`），依靠 prompt 里已有的
"请现在调用 submit_decision" + 单工具 spec —— 实测模型**会**调。

### 🔴 新发现 2（P2）：DeepSeek 余额曾耗尽
`3 × "Error code: 402 - Insufficient Balance"` —— 有 3 次决策因余额不足失败。当前余额正常
（本轮实测调用全部成功）。**402 与网络故障性质不同，不应混在同一套重试策略里**，建议单列监控。

### 本段验收（33 项断言全 PASS）
不联网；`akshare_source` 取数函数替换为必失败版本以复现 10-12 现场；`notify`/`marker` 落临时目录，
**不碰 data/**。提交：`6029129` / `5e803ab` / `50b3ef2`。

### 已知残留 / 待办

- **T-ENC-01（P1）**：`trainer_engine` 空头账务符号修正 + `backend/api/blueprints/trainer.py:118`
  `side` 缺枚举白名单（现在传 `"foo"` 也会被当空头）+ 空头往返单元测试。
  正确写法：整段 if/else + `balance -= exit_commission` 可换成 `self.balance += order.pnl`。
- **T-DATA-01（P1，待 PM 开工）**：交易日跑完缺事后复核。方案要点：在 `_finalize_run` 之前加一步
  "复核关键表新鲜度"，直接复用 `catchup.DAILY_TABLES` + 已有 `audit()`，缺口就地把 `ok=false` 并进通知。
  （直接影响 stock-ml 的 FF 过滤信号 —— `fund_flow_daily` 陈旧 1 个交易日。）
- **T-LLM-01（新，P1）**：强制提交 `tool_choice` 400 + per-request 分离超时，建议合并一个 commit，等授权。
- **T-LLM-02（新）**：`trader_decision.trace` 里补记单次 LLM 调用耗时（否则永远只能实测、无法从历史归因）。
- **T-ODO-01**：`backend/tushare_source.py` + `scripts/rebuild_tushare.py` 接进 pipeline 并声明
  `tushare` 依赖后再入库（当前保持 untracked）。
- **T-ENV-01（已转 dev-env-health）**：`C:\Python314` 的 `import pydantic` 因用户级孤儿
  `pydantic_core 2.41.4` SystemError（系统级是配套的 2.41.5）→ 用该解释器起开发后端时所有 LLM 功能炸；
  **不影响管道**（管道走 `.update-venv`，依赖自洽，已实测真实 LLM 调用成功）。
- **✅ 已修（本段）**：T-DATA-02（取数异常记前 3 条样例并入库）、T-DATA-03（非交易日早退分支走 `_finalize_run`）。
- **⛔ 推送仍是阻断状态**：PM 已批准推送，门禁 `--history` 复跑 **files=383 commits=332 0 命中 EXIT=0**，
  本地领先 316 提交、可快进；但 `git push origin master` 报
  `Failed to connect to github.com port 443 after 21089 ms`（**github.com:443 被单独阻断**：
  `ssh.github.com:443` 与 `api.github.com:443` 均通；本机无 SSH 私钥、无任何代理端口在监听）。
  **远端 0 变更**，等 PM 选定通路（开代理 / 换机器 / 网关放通）。

---

*说明见 [RESEARCH_AGENT.md](RESEARCH_AGENT.md)。*
