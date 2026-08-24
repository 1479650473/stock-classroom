# 后台量化研究代理层 (`backend/agent` + `backend/strategy`)

> 说明文档 · 版本 v4.2+ · 最后更新: 2026-08-24

在 GUI 桌面之外，本层实现一个 **LLM 驱动的研究闭环**（生成 → 回测 → 复盘 → 择优 → paper），
是项目向"**大模型驱动的 A 股量化交易员**"升华的核心。复用既有 `strategy/`(回测)、`macro/`(全球宏观)、
`catalog/`(目录)、`trade_engine/`(模拟撮合)，通过一个**能力分级、可审计、paper-only** 的 Agent Gateway 暴露。

> 设计参照 QuantDinger v5.0.17，按"单用户桌面 + SQLite"裁剪，**不照搬**其重基建(Postgres/双Redis/Celery/Docker)。

---

## 一、闭环架构

```
① 宏观(regime)           macro/  → 全球股市/汇率/利率/商品/波动 regime
        ↓
② 选标的域               catalog → 25 粗板块 → 代表股; 或宏观条件化(macro_sector)
        ↓
③ 因子研究(论证)         factor_research/factor_selector
        ├─ 技术因子:  动/反转/波动/RSI 多窗口 → 截面 IC/ICIR + 自动选参(ICIR阈值分档)
        └─ 价值/质量: EP/BP/ROE(东财每日估值) → 跨板块 IC/ICIR + 行业中性化
        ↓  (输出【研究论证的优先因子】 dsl_key/方向/IC/ICIR/置信度)
④ 生成策略                LLMBackend(真LLM) 或 StubBackend(确定性) →【声明式 JSON 契约】
        ↓
⑤ 回测                   backtest.py + protection.py (T+1/涨跌停/整数手/全费用/次日开盘);
                          gap 感知成交价(跳空破止损→按开盘); 声明式 DSL 条件树
        ↓
⑥ LLM 复盘修订            review(): 依指标调 entry/exit/止盈止损/移动止损 → 再回测
        ↓ (多轮)
⑦ 择优                    score(metrics) 取最优轮
        ↓
⑧ AI 决策门               decision_gate: {action,score,confidence,horizon,risk_level,reason}
                          —— 仅"上 paper 盘"那瞬调用(回测不调用保确定性); 非 enter 暂缓下单
        ↓
⑨ paper 盘               TradeEngine 模拟撮合(独立 AI 账户, 默认 paper-only, kill-switch 熔断)
```

**核心升华**：不是"LLM 一次性生成策略"，而是"**LLM 参与研究循环**"——研究(IC/ICIR)论证因子 → 生成 → 回测诚实度量 → 复盘改进 → 择优 → 决策门 → paper。

---

## 二、主要模块

### `backend/agent/` — 网关 + 研究闭环
| 文件 | 职责 |
|------|------|
| `gateway.py` | 能力分级 **R/W/B/T**，鉴权/审计/幂等/限流/token CRUD |
| `store.py` | `data/agent.db` 六表(agent_tokens/audit/jobs/idempotency/strategies/watchlist) |
| `jobs.py` | 异步回测 job(queued→running→succeeded/failed) + SSE 流 |
| `services.py` | 薄层复用 strategy/macro/trade_engine，不走 HTTP |
| `mcp_server.py` | MCPServer(18 个 R+B 工具，默认不暴露交易) |
| `llm_client.py` | OpenAI 兼容，读 `settings.json`；空 key 抛错回退 Stub |
| `gateway_client.py` | HTTP 消费 `/api/agent/v1` |
| `research_loop.py` | **闭环 Runner**：宏观→选域→因子研究→生成→回测→复盘→择优→paper |
| `decision_gate.py` | 结构化决策门(StubGate/LLMGate) |
| `macro_sector.py` | 宏观 regime→25 板块→代表股(确定性启发式，可被 LLM 取代) |
| `verify_*.py` | 验证脚本 |

### `backend/strategy/` — 策略契约 + 回测 + 因子研究
| 文件 | 职责 |
|------|------|
| `spec.py` | StrategySpec 声明式 JSON；`KNOWN_FACTORS` + `DSL_OPS` 白名单(`validate()` 硬拒未知因子/操作符，防"静默死策略") |
| `backtest.py` | T+1/涨跌停/整数手/全费用/次日开盘成交；保护引擎；**gap 感知成交价** |
| `protection.py` | 保护引擎：gap 感知、intrabar_mode 三档、trailing_stop、time_limit |
| `factors.py` | 逐 bar 因子(技术 + 研究因子 + 价值/质量) |
| `factor_research.py` | 截面因子研究：IC/ICIR/IC正率/滚动IC/5档分组/多空/单调性/相关性/稳定性 |
| `factor_data.py` / `factor_selector.py` | 因子数据加载 + 选择器(ICIR 阈值**自动选参** + 分档置信度) |
| `metrics.py` | 回测指标(收益/回撤/胜率统一**小数**口径，0.05=5%) |
| `prefetch_value_pool.py` / `verify_value_wide.py` | 基本面预抓 + 跨板块价值研究验证 |

### `backend/` — 数据层
| 文件 | 职责 |
|------|------|
| `fundamental.py` | 东财每日估值(PE_TTM/PB) → **EP/BP/ROE**，点时间无前视；`data/fundamental.db` |
| `codec.py` | 代码规范化(股票裸码/指数前缀/000001 歧义不猜) |
| `resilience.py` | 数据源韧性：RateLimiter/retry_with_backoff/UA 轮换 |
| `factor_engine/dsl.py` | DSL 条件求值(字符串阈值先数值化——LLM 常输出 `"0"`，否则恒 False) |
| `macro/` | 全球宏观 context 层(M0.5) |

---

## 三、因子库

### 技术因子(研究 + 策略共用，均在 DSL 词表)
- **动量** `MOMENTUM_5/10/20/40/60`（close/close[N]-1）
- **反转** `REVERSAL_5/10/20`（-动量）
- **波动** `VOLATILITY_5/10/20/60`（收益率 std）
- **超买超卖** `RSI_14`（Wilder）
- 另有 MA/MACD/BOLL/量比/价格位置/金叉死叉 等 43 因子

### 价值/质量因子(基本面，可研究 + 可进策略)
- **EP** = 1/PE_TTM（盈利收益率，越高越便宜）
- **BP** = 1/PB（账面市值比，越高越便宜）
- **ROE** = PB/PE_TTM（隐含净资产收益率，质量）
- 来源：`stock_value_em`(东财每日估值)，**点时间无前视**(某日估值=该日成交)

### 因子选择器(自动选参)
`factor_selector.recommend()`：在标的域池跑候选因子 IC/ICIR，按门槛(`min_ic/min_icir/min_coverage`)过滤 +
**ICIR 分档**(high≥1.0 / medium≥0.5 / weak≥0.3 / reject<0.3)给出置信度 strength，自动写入
`{dsl_key, direction, ic, icir, confidence, threshold, ...}` 供生成端使用；不达标返回 None → 回退样例策略。

价值因子标定(全市场实证, `factor_selector`)：
- `VALUE_BANDS`(1.0/0.5/0.3 分档) + `VALUE_DEFAULTS`(min_ic 0.004——价值 IC 量级小于价量因子)，
  门槛依据 **全市场 5149 只** 实证：**BP ICIR 1.54(high) / EP 0.83(medium) / ROE -0.23(reject, 跨行业不可比)**。
- `classify_value_records(vres)` 批量附 confidence/strength/direction 并返回最优；`recommend_value(codes,...)`
  选出最强价值因子；`validate_value_selection(contract)` 白名单硬校验**价值选股**契约
  `{factor∈{EP,BP,ROE}, direction∈{high,low}, hold_top_k_pct∈[0.01,0.5], rebalance_bars≥5, risk}`。
- `research_loop` 2c 产出 `context["recommended_value_factor"]`(分类后) + LLM `_prompt` 注入价值证据块。

### 因子有效性三层分离(IC ≠ 组合 ≠ 基准) — 最重要方法论
评价一个量化因子**不要混为一谈**，三层回答的是**不同问题**，结论可能互相冲突：

| 层 | 度量 | 问题 | 价值因子(低PB)实测(2024→now) |
|----|------|------|------|
| ① **信号层** | IC / ICIR(截面 rank 相关→点时间短前向收益) | **按因子排序能否预测收益**? | IC≈0.04~0.07 为正、rank 稳定(自相关≈0.99) → **真但弱** |
| ② **组合层** | 多头选股组合(持有前 K% 等权, 定期调仓, 含成本) | **该因子做多头组合能赚多少**? | 前20%低PB组合 +29%~+44%(含调仓成本) |
| ③ **基准层** | 等权买持(整个池) | **相对宽基买持有无超额**? | 等权买持 +51.34% → **组合跑输基准 ~16%** |

**教训(用实际数据支撑)**：
- **IC 为正 ≠ 多头组合跑赢宽基**：价值 IC 真(便宜>贵, 周多空价差 +2.27%)，但成长领涨的 risk-on 里
  价值跑输宽基 beta(2026 基准 +2.97% 而价值组合 -4~-9%)——**风格轮动/价值陷阱**。
- **价值 alpha 是短周期**：月度(长持有)多空价差转负(-6.52%)，被调仓成本/期限侵蚀；周周期才为正。
- **单标的择时≠截面选股**：价值作单票择时 ≈ 买持(无超额)；加 `CLOSE>MA20` 趋势叠加反而**更差**(抖出轨切碎择时，
  `verify_value_overlay` 实测:纯价值 +24.06% ≈ 买持 +23.96%; 价值+趋势(进出) +7.74%)。保留一个「趋势确认入场+价值离场」(避免抖出) +18.70%, 仍不敌纯价值。
- **结论用语必须分层**：不要只说"因子有效/无效"。要说清**在哪一层**(信号/组合/基准)有效、**口径**(周/月)、**窗口**(regime)。
  "价值因子有效(IC 真但弱、短周期)" 与 "价值选股组合长期未稳定跑赢买持(成长领涨窗口)" 是两件不冲突的事。

**相关口径**：`factor_selector` 把价值研究结果(IC/ICIR/confidence) 交给 LLM；但**生成端必须知道这只说明"信号层",
组合层可能跑输**——决策门(第⑧步)是独立审校, `verify_value_selection` 里决策门返回 hold 正是对"价值短期跑输"的保护。

---

## 四、安全模型

- **声明式 JSON 契约**：只产数据，不写任意代码(无 eval/exec/沙箱)。`validate()` 硬拒未知因子/未知 DSL 操作符。
- **能力分级 R/W/B/T**(去掉 N/C——本应用无凭据流转)；token 前缀 `sc_agent_` 只存 sha256；**代理绝不能自签 token**。
- **paper-only 默认 + 一键 kill-switch 熔断**；本部署无实盘路径。
- **决策门回测不调用**(保确定性)，仅"上 paper 盘"一瞬调用。
- **回测诚实**：gap 感知成交价(跳空破止损→按开盘)、点时间基本面无前视、全费用、T+1。

---

## 五、数据

| 库 | 内容 |
|----|------|
| `data/kline.db` | 日 K/股票列表/筹码(~5200 只，≥120 根) |
| `data/macro.db` | 全球宏观 11 指标 + regime(50k+ 行) |
| `data/fundamental.db` | 东财每日估值(全市场，点时间) |
| `data/agent.db` | 网关状态(已 gitignore) |
| `data/sim_trade.db` | paper 模拟账户 |

**数据本地化(避免重复拉取)**：所有数据**抓取后落盘 SQLite**，后续读路径**只读本地、绝不联网**。
- 基本面：`fetch_fundamental → store(fundamental.db)`；`has_vals` 跳过已缓存；研究/回测读路径
  `load_universe_frames/study_value_factors/attach_kline_fundamentals` **默认只读缓存**(`fetch_missing=False`)，
  **不触发抓取**；抓取只在显式预抓(`prefetch_value_pool.py`)或 `fetch_missing=True` 时发生。
- 宏观：`macro/snapshot.py`(fetch→store) 落 macro.db；`macro_regime()` 只读 macro.db(`SELECT ... FROM series`)。
- 日 K/目录：`load_klines`/`catalog.select` 只读 kline.db。由 `verify_local_cache.py`(spy 计数)证明读路径 0 次联网。

---

## 六、验证(全部本地,K线已缓存)

```bash
C:/Python314/python.exe backend/agent/smoke_test.py          # Agent Gateway+MCP 36/36
C:/Python314/python.exe backend/agent/verify_research_loop.py  # 研究闭环(Stub) 11/11
C:/Python314/python.exe backend/agent/verify_m2.py           # 宏观选板块+IC/ICIR+决策门 34/34
C:/Python314/python.exe backend/strategy/verify_value_strategy.py  # 价值策略(EP/BP 回测) 4/4
C:/Python314/python.exe backend/strategy/verify_value_wide.py    # 跨板块价值研究 8/8; VALUE_POOL_FULL=1 全市场
C:/Python314/python.exe backend/strategy/run_vertical_slice.py   # 回测引擎自检
C:/Python314/python.exe backend/strategy/verify_local_cache.py  # 数据本地化(读路径不联网) 4/4
C:/Python314/python.exe backend/agent/verify_llm_run.py     # 真 LLM 端到端(需 settings.json 配 key)
C:/Python314/python.exe backend/strategy/verify_value_selection.py  # 价值选股(LLM生成+截面回测+决策门) timeout 600
C:/Python314/python.exe backend/strategy/verify_value_overlay.py    # 价值作为过滤/择时叠加层(纯价值/价值+趋势/纯动量/买持)
C:/Python314/python.exe backend/strategy/verify_value_cycle.py      # 跨周期稳健性(2023-2026 逐年 IC/多空/组合/基准) timeout 600
```

## 七、诚实约束 / 已知限制

- **全市场基本面抓取是硬约束**：东财估值只能逐股抓(~2.5s/只 → 5191 只约 2.5-3h)，无批量接口；故用**可恢复预抓**(`prefetch_value_pool.py`, `VALUE_POOL_FULL=1`)流式缓存。
- **截面 IC ≠ 单标的择时**：研究因子(选哪只票)作单票信号未必盈利——闭环靠"回测→复盘"迭代发现并改进。
- **截面 IC ≠ 长期多头组合跑赢宽基买持**(见"因子有效性三层分离")：价值 IC 真但弱、短周期；成长领涨的 risk-on
  里多头低PB组合跑输等权买持(2024→now 组合 +29~44% vs 基准 +51%)。
- **价值 alpha 是短周期**：周周期多空价差 +2.27%(正)，月度(长持有)转负(-6.52%)；被调仓成本/期限侵蚀。
- **价值是弱的独立信号**：作单票择时 ≈ 买持(无超额)；加 `CLOSE>MA20` 趋势叠加反而更差(抖出轨)。
- **跨周期测试受限(数据现实)**：**2022 年末 K 线才有广度**(2018-2021 各年仅 ~1 只股有 K 线)。故无 2018/2022 深熊
  样本；"跨周期稳健性"仅覆盖 **2023→now**(`verify_value_cycle`, 价值 IC 跨年一致为正但弱, 选股组合跨年多数跑输)。
  要补真正的深熊跨周期，需先补抓 2018/2019-21 全市场历史 K 线(未来工作)。
- **metrics 统一小数**口径(0.537=+53.7%)；`run_backtest` 与 gateway 本就同口径，改动仅为消除"存百分数→消费者再×100"的歧义。
- **LLM key** 存 `backend/configs/settings.json`(非 git 跟踪)。
- 财报/估值注意披露时点；本实现用**东财每日估值**天然点时间(某日 PE/PB 即该日成交)，规避披露滞后。

---
*任务进度见 [TASK_LOG.md](TASK_LOG.md)。*
