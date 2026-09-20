# scripts/ — 辅助脚本索引

> 主流程不在这里：**每日数据自动化**统一在 `backend/update_daily.py`
> （计划任务 `StockClassroom-DailyUpdate` → `backend/update_daily.bat`，17:00 触发）。
> 本目录是"补数据 / 重建 / 体检 / 一次性修复"用的工具箱，**都可反复运行、多数可中断续跑**。

## 常用（数据补缺）

| 脚本 | 用途 | 典型用法 |
|------|------|----------|
| `check_data_health.py` | **先跑这个**：数据格式/缺口/单位/重复的体检报告 | `python scripts/check_data_health.py` |
| `backfill_missing_day.py` | 补齐"某一天只有部分股票有数据"的残缺交易日（逐股票判断，分块落库可续跑） | `python scripts/backfill_missing_day.py --date 20260911 --workers 16` |
| `backfill_gaps.py` | 按年 / 按天数 / 指定代码补缺口（新浪 qfq 主源，baostock 补漏） | `python scripts/backfill_gaps.py --days 30` |
| `fill_fund_flow_missing.py` | 资金流直连补漏（绕过 akshare_source 封装，手工验证接口格式） | `python scripts/fill_fund_flow_missing.py` |
| `fix_volume_zero.py` | 修 `volume=0` 脏数据（腾讯源的已知 bug 写入） | `python scripts/fix_volume_zero.py --dry-run` |

## 全量重建（首次/大修时用）

| 脚本 | 重建对象 | 说明 |
|------|----------|------|
| `rebuild_kline_unified.py` | 全库日 K | 统一 qfq 基准=最新 + volume=股/amount=元；多进程 |
| `rebuild_bj.py` | **北交所全历史**（343 只） | 新浪 `stock_zh_a_daily(bjXXXXXX, qfq)`；**必须多进程**（V8 线程并发会崩）；幂等可续跑 |
| `rebuild_etf.py` | ETF 全量历史（1606 只） | 新浪 qfq 主源；update_daily ⑫ 步每日增量 |
| `rebuild_fund_flow.py` | 个股资金流（日频） | 东财 daykline 全历史；update_daily ⑬ 步增量 |
| `rebuild_lhb_margin.py` | 龙虎榜 + 融资融券 | 季度批次 / 按日 16 线程；update_daily ⑮ 步回补 |
| `rebuild_weekly_monthly.py` | 周 K / 月 K 聚合表 | 委托 `data_manager.rebuild_period_kline`；update_daily ⑭ 步增量 |
| `rebuild_chip.py` | 筹码分布（250 天，全市场） | 多进程、每进程独立 V8；update_daily ⑰ 步每日重算 |

## 探测与一次性

| 脚本 | 用途 |
|------|------|
| `probe_fund_flow.py` | 探测东财资金流接口反爬状态 + 测安全读取速率（改批量补数前先跑） |
| `generate_logo.py` | 生成项目 logo 资源（一次性；桌面图标母版见 `web/src-tauri/make_icon.py`） |

## 约定与坑

- **并发**：`py_mini_racer`(新浪 V8) 在**线程**并发下会崩进程（实测 6 并发即崩）→
  批量补数一律 `ProcessPoolExecutor` 多进程（每进程独立 V8），跑崩会自动降并发重试。
- **口径**：库内 `volume`=股、`amount`=元、`turnover`=百分数、日期 `YYYYMMDD`；
  改数据前先看 `AGENTS.md` 的"数据可靠性"与"股票池覆盖"两段。
- **新脚本请补进本表**，并写清"什么时候该用它"。
