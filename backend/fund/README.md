# backend/fund — 基金套利（LOF 折溢价）

收盘后扫描 LOF 的**折溢价套利**机会：场内价格 vs 单位净值，扣掉申购/赎回/佣金/转托管/滑点后的净空间，
并给出**门槛**（购买起点、日累计限额、申购/赎回状态）与费率分档。

## 两条腿

| 方向 | 操作 | 主要成本 |
|------|------|----------|
| **溢价**（场内价 > 净值） | 场外按净值申购 → T+2 份额到账 + 转托管 T+1 → 场内卖出 | 申购费（外扣，支持折扣）、卖出佣金（含最低）、滑点、转托管费 |
| **折价**（场内价 < 净值） | 场内买入 → T+1 转托管到场外 → 赎回 | 买入佣金（含最低）、**赎回费按持有天数分档**（7 天内通常 1.5%）、转托管费 |

折价腿默认按「最短持有」算（保守），同时给出「持满 N 天后费率降档」的方案。

## 数据源（注意本机限制）

| 数据 | 接口 | 说明 |
|------|------|------|
| LOF 名单 + 实时快照 | 新浪 `fund_etf_category_sina("LOF基金")` | 360 只，代码带 sz/sh 前缀 |
| 场内日线（不复权） | 腾讯 `stock_zh_a_hist_tx(adjust="")` | 该接口 `amount` 字段是**成交量(手)** → ×100 = 份 |
| 单位净值（全历史） | 东财 `fund_open_fund_info_em(indicator="单位净值走势")` | 一次请求给全序列 |
| 赎回费率分档 | 东财 `fund_fee_em(indicator="赎回费率")` | 「小于7天/大于等于7天，小于365天…」 |
| 申购门槛/状态/费率 | 东财 `fund_purchase_em()` | 全表 2.7 万只：申购/赎回状态、购买起点、日累计限定金额、手续费 |

⚠️ **东财行情服务器（push2 系）在本机不可达**（直连被重置、走代理也不稳）→ akshare 的
`fund_lof_spot_em` / `fund_etf_spot_em` / `fund_lof_hist_em` / `stock_zh_a_hist` 等**不可用**；
本模块走 新浪 + 腾讯 + 东财 fund.eastmoney.com 组合（与项目其它模块的三源回退一致）。

## 口径

- **折溢价率 = 场内收盘价 ÷ 单位净值 − 1**，两边都取**原始值**（分红除权时价格与净值同步下降，比值仍可比；
  用前复权价反而会破坏比值）。
- 净值与价格**按日期对齐**：净值滞后（QDII 常见 1~2 天）时显示滞后天数并打标签。
- 「净空间」= 相对投入本金的收益率（费用已扣）；「年化」= 单次收益 × 250/占用天数（**线性折算**，
  3 天窗口不用复利；页面上限 999% 显示）。
- 默认成本参数（页面「成本参数」可改，全站口径跟着变）：
  佣金万 2.5（最低 5 元）、申购费按公布费率（折扣 1.0；0.1 = 1 折）、转托管 0 元、卖出滑点 1 跳（0.001 元）。
  基金**免印花税**。

## 自动化（每天自动更新）

| 时间 | 触发 | 做什么 |
|------|------|--------|
| 交易日 **17:00** | Windows 计划任务 `StockClassroom-DailyUpdate` → `update_daily.py` 第 ㉒ 步 | 名单 + 申购门槛 + 日线增量 + 净值增量 + 费率轮换（与全市场数据更新一起跑） |
| 每天 **22:30** | Windows 计划任务 `StockClassroom-FundArbSync` → `backend/fund_arb_sync.bat` | 补当日净值（17:00 时基金净值通常还没公布，约 19:00 后才出）；失败自动重试一次 |
| 随时 | 页面右上「同步数据 / 刷新费率」 | 手动触发（走 jobman 任务中心，进度可见） |

日志：`data/logs/fund_arb_sync.log`（晚间任务）、`data/logs/update_daily_YYYYMMDD.log`（每日全量）。
失败会进 `notify` 通知（前端 NotifyBell）。

**口径：价格与净值按「同一天」对齐**（`store.latest_snapshot`）——从最新价格日往回找第一个也有净值的交易日；
当日净值未公布时自动回退到最近对齐日并在界面标注「净值未出·回退 N 日」，
避免出现「价格 T + 净值 T-1」的错配折溢价率。

## CLI

```bash
python -m backend.fund.sync --backfill            # 首次全量（日线 2018+、净值全量、费率、申购表）
python -m backend.fund.sync --daily               # 每日增量（名单 + 日线 + 净值 + 申购表）
python -m backend.fund.sync --fees                # 刷新费率（默认只刷 30 天以上未更新的）
python -m backend.fund.sync --stats               # 数据状态
```

`update_daily.py` 第 ㉒ 步已接入每日增量 + 费率轮换（失败进当天的异常汇总通知）。

## 表（`data/fund_arb.db`）

- `lof_list(code, name, exchange)` — 来自新浪名单
- `lof_daily(code, date, open, high, low, close, volume, amount)` — 未复权；volume=份、amount=元（按收盘估）
- `fund_nav(code, nav_date, nav, growth)` — 单位净值
- `fund_fee(code, buy_tiers, redeem_tiers)` — JSON 分档
- `fund_purchase(code, name, ftype, nav, nav_date, purchase_status, redeem_status, min_amount, daily_limit, fee_rate)`
- `arb_meta(key, value)` — 同步状态

## API

- `GET  /api/fund-arb/overview` — 概览（机会计数 / Top 榜 / 数据状态）
- `GET  /api/fund-arb/list` — 机会表（`direction` / `min_space` / `only_open` + 成本参数透传）
- `GET  /api/fund-arb/fund/<code>` — 明细（费率表 / 门槛 / 成本拆解 / 历史折溢价 + 分位）
- `POST /api/fund-arb/sync` — 同步（job，`mode=daily|fees|backfill|list`）
