# -*- coding: utf-8 -*-
"""rebuild_market_daily.py — 从日K本地派生每日涨停/跌停家数(全历史), 重建 market_daily.

涨停判定(按板块阈值 + 容差):
  主板(60/00) 10% | 创业板(30)/科创板(68) 20% | 北交所(8/4/92) 30% | ST 主板 5%
  新股/特殊(无法回溯) → 用阈值近似, 误差极小
用法: python scripts/rebuild_market_daily.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "kline.db")


def main():
    t0 = time.time()
    days = 0   # >0: 只重算最近 N 天(每日增量, 每只取 N+1 行)
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    con = sqlite3.connect(DB, timeout=300)
    c = con.cursor()

    # ST 名单(当前名称近似)
    st_codes = set(str(r[0]) for r in c.execute(
        "SELECT code FROM stock_list WHERE name LIKE '%ST%'"))
    print(f"ST 股票: {len(st_codes)} 只 | 模式: {'最近%d天' % days if days else '全量'}", flush=True)

    if not days:
        # 重建表
        c.execute("DROP TABLE IF EXISTS market_daily")
        c.execute("""CREATE TABLE market_daily (
            date TEXT PRIMARY KEY, lu_count INTEGER, ld_count INTEGER, total_count INTEGER)""")
        con.commit()

    # 全市场日K(股票)
    codes = [str(r[0]) for r in c.execute(
        "SELECT DISTINCT code FROM kline_daily WHERE code NOT LIKE 'sh%' AND code NOT LIKE 'sz%' ORDER BY code")]
    print(f"股票: {len(codes)} 只", flush=True)

    from collections import defaultdict
    lu = defaultdict(int)
    ld = defaultdict(int)
    total = defaultdict(int)
    done = 0
    for code in codes:
        is_st = code in st_codes
        if code.startswith(("30", "68")):
            lim = 0.20
        elif code.startswith(("8", "4", "92")):
            lim = 0.30
        else:
            lim = 0.05 if is_st else 0.10
        # 最近 N+1 行(需要 prev close)
        if days:
            rows = c.execute(
                "SELECT date, close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT ?",
                (code, days + 1)).fetchall()
            rows = list(reversed(rows))
        else:
            rows = c.execute("SELECT date, close FROM kline_daily WHERE code=? ORDER BY date", (code,)).fetchall()
        prev = None
        for date, close in rows:
            if prev and prev > 0 and close > 0:
                pct = close / prev - 1
                total[date] += 1
                if pct >= lim - 0.003:
                    lu[date] += 1
                elif pct <= -(lim - 0.003):
                    ld[date] += 1
            prev = close
        done += 1
        if done % 1000 == 0:
            print(f"  [{done}/{len(codes)}] {time.time()-t0:.0f}s", flush=True)

    rows_out = [(d, lu.get(d, 0), ld.get(d, 0), total.get(d, 0)) for d in sorted(total.keys())]
    if days:
        # 增量: 只更新最近 N 天(保留旧行)
        c.executemany("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?)", rows_out)
    else:
        c.executemany("INSERT OR REPLACE INTO market_daily VALUES (?,?,?,?)", rows_out)
    con.commit()
    r = c.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM market_daily").fetchone()
    print(f"=== market_daily: {r[0]} 天 / {r[1]} ~ {r[2]} ({time.time()-t0:.0f}s) ===", flush=True)
    for row in c.execute("SELECT * FROM market_daily ORDER BY date DESC LIMIT 3"):
        print("  ", row)
    con.close()


if __name__ == "__main__":
    main()