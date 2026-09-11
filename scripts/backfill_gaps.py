# -*- coding: utf-8 -*-
"""backfill_gaps.py — 补拉指定年份缺失的股票(新浪 qfq 多进程, 无 baostock 补漏).

用法:
  python scripts/backfill_gaps.py --year 2023            # 补 2023 缺数据的 active 股票
  python scripts/backfill_gaps.py --codes 600036,000001  # 指定股票全历史
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PROCS = int(os.environ.get("BACKFILL_PROCS", "6"))


def _proc_worker(codes: list) -> dict:
    import akshare as ak
    import random
    from data_manager import get_kline_db, _bulk_insert_kline
    from codec import normalize_a_code, ak_symbol
    from akshare_source import _normalize_kline_rows

    ok = fail = rows = 0
    failed = []
    for i, code in enumerate(codes):
        try:
            stored = normalize_a_code(code, "stock")
            symbol = ak_symbol(code, "stock")
            df = None
            for attempt in range(3):
                try:
                    time.sleep(random.uniform(0.3, 1.0))
                    df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
                except Exception:
                    df = None
                if df is not None and not df.empty:
                    break
            if df is None or df.empty:
                failed.append(code)
                fail += 1
                continue
            try:
                data = _normalize_kline_rows(stored, df, days=4000)
            except Exception:
                data = []
            if not data:
                failed.append(code)
                fail += 1
                continue
            conn = get_kline_db()
            try:
                ins, _ = _bulk_insert_kline(conn, data, replace=True)
                conn.commit()
                rows += ins
                ok += 1
            finally:
                conn.close()
        except Exception:
            failed.append(code)
            fail += 1
        if (i + 1) % 100 == 0 or i + 1 == len(codes):
            print(f"    [proc {os.getpid()}] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    return {"ok": ok, "fail": fail, "rows": rows, "failed": failed}


def main():
    import sqlite3
    args = sys.argv[1:]
    year = None
    codes_arg = None
    days = None
    for i, a in enumerate(args):
        if a == "--year" and i + 1 < len(args):
            year = int(args[i + 1])
        if a == "--codes" and i + 1 < len(args):
            codes_arg = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])

    db = os.path.join(ROOT, "data", "kline.db")
    con = sqlite3.connect(db)
    if codes_arg:
        codes = codes_arg
    elif days:
        # 最新日期落后于最近 N 个交易日参考日的 active 股票(漏更/限流失败)
        latest = con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
        recent = [r[0] for r in con.execute(
            "SELECT DISTINCT date FROM kline_daily WHERE code='sh000300' AND date<=? "
            "ORDER BY date DESC LIMIT ?", (latest, days))]
        if not recent:
            recent = [latest]
        ref = recent[0]
        codes = [str(r[0]) for r in con.execute(
            "SELECT s.code FROM stock_list s WHERE s.status='active' AND s.code NOT LIKE 'sh%' "
            "AND s.code NOT LIKE 'sz%' AND COALESCE(s.last_date, '') < ? ORDER BY s.code",
            (ref,)).fetchall()]
        # stock_list.last_date 可能滞后, 以 kline_daily 实际最新为准
        stale = [c for c in codes if not con.execute(
            "SELECT 1 FROM kline_daily WHERE code=? AND date>=? LIMIT 1", (c, ref)).fetchone()]
        codes = stale
        print(f"  参考最新交易日: {ref}, 按最新日期补 {len(codes)} 只", flush=True)
    elif year:
        tbl = f"kline_{year}"
        codes = [str(r[0]) for r in con.execute(
            f"SELECT DISTINCT code FROM stock_list WHERE status='active' AND code NOT IN "
            f"(SELECT DISTINCT code FROM {tbl}) ORDER BY code").fetchall()]
    else:
        print("需要 --year / --days / --codes")
        sys.exit(1)
    con.close()
    print(f"=== 补拉 {len(codes)} 只 (PROCS={PROCS}) ===", flush=True)
    t0 = time.time()
    ok = fail = rows = 0
    failed_all = []
    chunks = [codes[i::PROCS] for i in range(PROCS)]
    chunks = [c for c in chunks if c]
    with mp.Pool(len(chunks)) as pool:
        for res in pool.imap_unordered(_proc_worker, chunks):
            ok += res["ok"]
            fail += res["fail"]
            rows += res["rows"]
            failed_all.extend(res["failed"])
    print(f"=== 完成: ok={ok} fail={fail} rows={rows} 耗时 {time.time()-t0:.0f}s ===", flush=True)
    if failed_all:
        print("失败:", ",".join(failed_all[:50]), flush=True)


if __name__ == "__main__":
    main()