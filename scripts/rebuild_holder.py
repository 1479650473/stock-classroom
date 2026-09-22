# -*- coding: utf-8 -*-
"""rebuild_holder.py — 股东户数 + 基金持仓(季度, 2015-2026 全报告期).

数据源(akshare):
  - 股东户数: stock_zh_a_gdhs(报告期) — 全市场, 2015+ 
  - 基金持仓: stock_report_fund_hold("基金持仓", 报告期) — 全市场, 2015+
用法:
  python scripts/rebuild_holder.py            # 全报告期
  python scripts/rebuild_holder.py --recent 4 # 最近 4 期
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
DB = os.path.join(ROOT, "data", "kline.db")

START = "20150331"


def _report_dates() -> list:
    """2015-03-31 起所有季度报告期(到今年最近已过季度末)."""
    out = []
    today = date.today()
    y = 2015
    while y <= today.year:
        for md in ("0331", "0630", "0930", "1231"):
            d = f"{y}{md}"
            if d <= today.strftime("%Y%m%d"):
                out.append(d)
        y += 1
    return out


def _init_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS holder_count (
        code TEXT, report_date TEXT, name TEXT,
        holder_count INTEGER, holder_count_prev INTEGER, holder_change INTEGER,
        holder_change_pct REAL, avg_mv REAL, avg_shares REAL,
        total_mv REAL, total_shares REAL, announce_date TEXT,
        PRIMARY KEY (code, report_date))""")
    con.execute("""CREATE TABLE IF NOT EXISTS fund_hold (
        code TEXT, report_date TEXT, name TEXT,
        fund_count INTEGER, hold_shares REAL, hold_value REAL,
        hold_change_pct REAL, change_shares REAL,
        PRIMARY KEY (code, report_date))""")
    con.commit()


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _i(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def fetch_holder(rd: str) -> list:
    import akshare as ak
    df = ak.stock_zh_a_gdhs(symbol=rd)
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            rows.append((
                str(r.iloc[0]), rd, str(r.iloc[1]),
                _i(r.iloc[4]), _i(r.iloc[5]), _i(r.iloc[6]), _f(r.iloc[7]),
                _f(r.iloc[11]), _f(r.iloc[12]), _f(r.iloc[13]), _f(r.iloc[14]),
                str(r.iloc[15]),
            ))
        except Exception:
            continue
    return rows


def fetch_fund(rd: str) -> list:
    import akshare as ak
    df = ak.stock_report_fund_hold(symbol="基金持仓", date=rd)
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            rows.append((
                str(r.iloc[2]), rd, "",
                _i(r.iloc[3]), _f(r.iloc[4]), _f(r.iloc[5]),
                _f(r.iloc[6]), _f(r.iloc[8]),
            ))
        except Exception:
            continue
    return rows


def main():
    args = sys.argv[1:]
    recent = 0
    for i, a in enumerate(args):
        if a == "--recent" and i + 1 < len(args):
            recent = int(args[i + 1])

    dates = _report_dates()
    if recent:
        dates = dates[-recent:]
    print(f"=== 报告期: {len(dates)} 期 ({dates[0]} ~ {dates[-1]}) ===", flush=True)

    con = sqlite3.connect(DB, timeout=120)
    _init_tables(con)
    # 续跑: 跳过已完整的报告期(两表都有数据)
    done = set()
    for (d,) in con.execute("SELECT report_date FROM holder_count GROUP BY report_date"):
        done.add(str(d))
    todo = [d for d in dates if d not in done]
    print(f"待拉: {len(todo)} 期 (已完成 {len(done)})", flush=True)

    t0 = time.time()
    h_total = f_total = 0
    for i, rd in enumerate(todo):
        # 股东户数
        try:
            rows = fetch_holder(rd)
            if rows:
                con.executemany(
                    "INSERT OR REPLACE INTO holder_count VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                con.commit()
                h_total += len(rows)
        except Exception as e:
            print(f"  [{rd}] holder EXC: {str(e)[:60]}", flush=True)
        time.sleep(1)
        # 基金持仓
        try:
            rows = fetch_fund(rd)
            if rows:
                con.executemany(
                    "INSERT OR REPLACE INTO fund_hold VALUES (?,?,?,?,?,?,?,?)", rows)
                con.commit()
                f_total += len(rows)
        except Exception as e:
            print(f"  [{rd}] fund EXC: {str(e)[:60]}", flush=True)
        time.sleep(1)
        print(f"  [{i+1}/{len(todo)}] {rd}: holder+{h_total} fund+{f_total} ({time.time()-t0:.0f}s)", flush=True)

    for t in ("holder_count", "fund_hold"):
        r = con.execute(f"SELECT COUNT(*), COUNT(DISTINCT code), MIN(report_date), MAX(report_date) FROM {t}").fetchone()
        print(f"=== {t}: {r[0]:,} 行 / {r[1]} 只 / {r[2]} ~ {r[3]} ===", flush=True)
    con.close()


if __name__ == "__main__":
    main()