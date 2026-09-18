# -*- coding: utf-8 -*-
"""rebuild_chip.py — 全市场筹码分布首拉/重算(最近 N 天, 多进程).

新浪K线 + JS计算(每进程独立 py_mini_racer, 多进程必须).
用法:
  python scripts/rebuild_chip.py               # 全市场 250 天
  python scripts/rebuild_chip.py --days 500
  python scripts/rebuild_chip.py --codes 600036,000001
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PROCS = int(os.environ.get("CHIP_PROCS", "6"))


def main():
    from data_manager import _chip_worker
    import multiprocessing as mp
    import sqlite3

    args = sys.argv[1:]
    days = 250
    codes_arg = None
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
        if a == "--codes" and i + 1 < len(args):
            codes_arg = [c.strip() for c in args[i + 1].split(",") if c.strip()]

    if codes_arg:
        codes = codes_arg
    else:
        con = sqlite3.connect(os.path.join(ROOT, "data", "kline.db"))
        codes = [str(r[0]) for r in con.execute(
            "SELECT code FROM stock_list WHERE status='active' "
            "AND substr(code,1,2) IN ('00','30','60','68') ORDER BY code").fetchall()]
        con.close()
    print(f"=== 筹码分布重算: {len(codes)} 只 × {days} 天 | PROCS={PROCS} ===", flush=True)

    t0 = time.time()
    chunks = [codes[i::PROCS] for i in range(PROCS)]
    chunks = [ch for ch in chunks if ch]
    ok = fail = rows_n = 0
    with mp.Pool(len(chunks)) as pool:
        results = pool.starmap(_chip_worker, [(ch, days) for ch in chunks])
    for r in results:
        ok += r["ok"]
        fail += r["fail"]
        rows_n += r["rows"]
    print(f"=== 完成: ok={ok} fail={fail} rows={rows_n:,} ({time.time()-t0:.0f}s) ===", flush=True)

    con = sqlite3.connect(os.path.join(ROOT, "data", "kline.db"))
    r = con.execute("SELECT COUNT(*), COUNT(DISTINCT code), MAX(date) FROM chip_distribution").fetchone()
    con.close()
    print(f"=== chip_distribution: {r[0]:,} 行 / {r[1]} 只 / 最新 {r[2]} ===", flush=True)


if __name__ == "__main__":
    main()