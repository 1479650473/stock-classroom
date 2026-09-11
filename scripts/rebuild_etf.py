# -*- coding: utf-8 -*-
"""rebuild_etf.py — 全市场 ETF 全量历史 K 线首拉/重建.

主源新浪 fund_etf_hist_sina(qfq, volume=股/amount=元), 回退东财 fund_etf_hist_em(手→股).
多进程(每进程单线程)规避 py_mini_racer 并发问题. 幂等(INSERT OR REPLACE), 可断点续跑.

用法:
  python scripts/rebuild_etf.py            # 全量(列表 + 全部 ETF 历史)
  python scripts/rebuild_etf.py --limit 20 # 冒烟前 20 只
  python scripts/rebuild_etf.py --codes 510300,159919
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PROCS = int(os.environ.get("ETF_PROCS", "6"))
DB = os.path.join(ROOT, "data", "kline.db")


def _proc_worker(codes: list) -> dict:
    import akshare as ak  # noqa: F401  预热
    from akshare_source import ak_fetch_etf_kline
    import sqlite3

    ok = fail = rows = 0
    failed = []
    for i, code in enumerate(codes):
        try:
            data = ak_fetch_etf_kline(code)
            if not data:
                failed.append(code)
                fail += 1
                continue
            con = sqlite3.connect(DB, timeout=60)
            con.executemany(
                "INSERT OR REPLACE INTO etf_daily (code,date,open,high,low,close,volume,amount,turnover) "
                "VALUES (?,?,?,?,?,?,?,?,?)", data)
            con.commit()
            con.close()
            ok += 1
            rows += len(data)
        except Exception:
            failed.append(code)
            fail += 1
        if (i + 1) % 50 == 0 or i + 1 == len(codes):
            print(f"    [proc {os.getpid()}] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    return {"ok": ok, "fail": fail, "rows": rows, "failed": failed}


def main():
    from data_manager import init_etf_tables, cache_etf_list_from_akshare, get_etf_list

    args = sys.argv[1:]
    limit = None
    codes_arg = None
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        if a == "--codes" and i + 1 < len(args):
            codes_arg = [c.strip() for c in args[i + 1].split(",") if c.strip()]

    init_etf_tables()
    if codes_arg:
        codes = codes_arg
    else:
        n = cache_etf_list_from_akshare()
        print(f"=== ETF 列表缓存: {n} 只 ===", flush=True)
        codes = [r["code"] for r in get_etf_list()]
    if limit:
        codes = codes[:limit]
    print(f"=== ETF 全历史拉取: {len(codes)} 只 | PROCS={PROCS} ===", flush=True)

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
    print(f"=== ETF 完成: ok={ok} fail={fail} rows={rows} 耗时 {time.time()-t0:.0f}s ===", flush=True)
    if failed_all:
        print("失败:", ",".join(failed_all[:60]), flush=True)

    # 校验
    con = sqlite3.connect(DB)
    n_code = con.execute("SELECT COUNT(DISTINCT code) FROM etf_daily").fetchone()[0]
    n_row = con.execute("SELECT COUNT(*) FROM etf_daily").fetchone()[0]
    mx = con.execute("SELECT MAX(date) FROM etf_daily").fetchone()[0]
    con.close()
    print(f"=== etf_daily: {n_code} 只 / {n_row:,} 行 / 最新 {mx} ===", flush=True)


if __name__ == "__main__":
    main()