# -*- coding: utf-8 -*-
"""rebuild_lhb_margin.py — 龙虎榜 + 融资融券全历史首拉.

龙虎榜: 东财 stock_lhb_detail_em 按季度批次(2010-01 起), 写入 lhb_daily.
融资融券: 上交所+深交所按交易日(2010-03-31 起), 写入 margin_daily, 多线程.
幂等(INSERT OR REPLACE), 可续跑.

用法:
  python scripts/rebuild_lhb_margin.py              # 全量(龙虎榜+融资融券)
  python scripts/rebuild_lhb_margin.py --lhb-only
  python scripts/rebuild_lhb_margin.py --margin-only
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

START_LHB = "20100101"
START_MARGIN = "20100331"
WORKERS = int(os.environ.get("LM_WORKERS", "8"))


def _trade_dates() -> list:
    """交易日列表(从本地 trade_calendar.json, 回退 akshare)."""
    p = os.path.join(ROOT, "data", "trade_calendar.json")
    try:
        with open(p, encoding="utf-8") as f:
            return sorted(str(d) for d in json.load(f))
    except Exception:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        return sorted(str(d)[:10] for d in df["trade_date"])


def run_lhb():
    from data_manager import init_lhb_margin_tables, update_lhb_range
    init_lhb_margin_tables(rebuild=True)
    today = datetime.now().strftime("%Y%m%d")
    # 按季度批次
    batches = []
    y, q = int(START_LHB[:4]), 1
    while True:
        qs = "%d%02d01" % (y, (q - 1) * 3 + 1)
        # 季度末
        if q == 1:
            qe = "%d0331" % y
        elif q == 2:
            qe = "%d0630" % y
        elif q == 3:
            qe = "%d0930" % y
        else:
            qe = "%d1231" % y
        if qs > today:
            break
        batches.append((qs, min(qe, today)))
        q += 1
        if q > 4:
            q = 1
            y += 1
    print(f"=== 龙虎榜: {len(batches)} 个季度批次 ===", flush=True)
    t0 = time.time()
    total = 0
    for i, (s, e) in enumerate(batches):
        try:
            n = update_lhb_range(s, e)
            total += n
            print(f"  [{i+1}/{len(batches)}] {s}~{e}: {n} 行 (累计 {total})", flush=True)
        except Exception as ex:
            print(f"  [{i+1}/{len(batches)}] {s}~{e} 失败: {str(ex)[:60]}", flush=True)
        time.sleep(0.5)
    print(f"=== 龙虎榜完成: {total:,} 行 ({time.time()-t0:.0f}s) ===", flush=True)


def run_margin():
    from data_manager import init_lhb_margin_tables, update_margin_dates
    from akshare_source import ak_fetch_margin_day
    import sqlite3
    init_lhb_margin_tables()
    cal = _trade_dates()
    today = datetime.now().strftime("%Y-%m-%d")
    dates = [d for d in cal if START_MARGIN[:4] + "-" + START_MARGIN[4:6] + "-" + START_MARGIN[6:] <= d <= today]
    # 跳过已有日期(续跑)
    conn = sqlite3.connect(os.path.join(ROOT, "data", "kline.db"))
    done_dates = set(str(r[0]) for r in conn.execute("SELECT DISTINCT date FROM margin_daily"))
    conn.close()
    dates = [d for d in dates if d.replace("-", "") not in done_dates]
    print(f"=== 融资融券: {len(dates)} 个待拉交易日(已跳过 {len(done_dates)}) | WORKERS={WORKERS} ===", flush=True)
    t0 = time.time()
    ok = fail = rows_n = 0
    done = 0

    def _one(d):
        ds = d.replace("-", "")
        rows = ak_fetch_margin_day(ds)
        return d, rows

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(_one, d): d for d in dates}
        for f in as_completed(futs):
            d = futs[f]
            done += 1
            try:
                d, rows = f.result(timeout=180)
            except Exception:
                rows = []
            if rows:
                ok += 1
                rows_n += len(rows)
                conn = __import__("sqlite3").connect(
                    os.path.join(ROOT, "data", "kline.db"), timeout=60)
                conn.executemany(
                    "INSERT OR REPLACE INTO margin_daily "
                    "(code,date,name,rzye,rzmre,rzche,rqye,rqmcl,rqchl,rzrqye) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                conn.commit()
                conn.close()
            else:
                fail += 1
            if done % 100 == 0 or done == len(dates):
                el = time.time() - t0
                spd = done / el if el else 0
                eta = (len(dates) - done) / spd if spd else 0
                print(f"  [{done}/{len(dates)}] ok={ok} fail={fail} rows={rows_n:,} "
                      f"{spd:.1f}/s ETA {eta:.0f}s", flush=True)
    print(f"=== 融资融券完成: ok={ok} fail={fail} rows={rows_n:,} ({time.time()-t0:.0f}s) ===", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    do_lhb = "--margin-only" not in args
    do_margin = "--lhb-only" not in args
    if do_lhb:
        run_lhb()
    if do_margin:
        run_margin()
    # 校验
    import sqlite3
    conn = sqlite3.connect(os.path.join(ROOT, "data", "kline.db"))
    for t, dc in (("lhb_daily", "trade_date"), ("margin_daily", "date")):
        try:
            r = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT {dc}), MIN({dc}), MAX({dc}) FROM {t}").fetchone()
            print(f"=== {t}: {r[0]:,} 行 / {r[1]} 天 / {r[2]} ~ {r[3]} ===", flush=True)
        except Exception as e:
            print(t, "校验失败:", e)
    conn.close()