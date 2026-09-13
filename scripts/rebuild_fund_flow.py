# -*- coding: utf-8 -*-
"""rebuild_fund_flow.py — 全市场个股资金流(日频)全量首拉/重建.

东财 daykline 接口(lmt=0 全历史, 起点约2010年). 幂等(INSERT OR REPLACE), 可断点续跑
(失败列表重跑 --codes). 今日东财 IP 反爬时全部失败 → 稍后重跑即可(脚本可续跑).

用法:
  python scripts/rebuild_fund_flow.py              # 全量(active A股)
  python scripts/rebuild_fund_flow.py --limit 20   # 冒烟
  python scripts/rebuild_fund_flow.py --codes 600036,000001,000858
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PROCS = int(os.environ.get("FF_PROCS", "6"))
DB = os.path.join(ROOT, "data", "kline.db")


def _proc_worker(codes: list) -> dict:
    from akshare_source import ak_fetch_fund_flow
    import sqlite3

    ok = fail = rows = 0
    failed = []
    for i, code in enumerate(codes):
        try:
            data = ak_fetch_fund_flow(code)
            if not data:
                failed.append(code)
                fail += 1
                continue
            con = sqlite3.connect(DB, timeout=60)
            con.executemany(
                "INSERT OR REPLACE INTO fund_flow_daily "
                "(code,date,close,change_pct,main_net,main_ratio,super_net,super_ratio,"
                "large_net,large_ratio,medium_net,medium_ratio,small_net,small_ratio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
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


def _proc_worker_slow(codes: list, interval: float) -> dict:
    """低频单进程拉取(适配东财反爬): 每只间隔 interval 秒, 失败重试 2 次."""
    from akshare_source import ak_fetch_fund_flow
    import sqlite3

    ok = fail = rows = 0
    failed = []
    for i, code in enumerate(codes):
        data = []
        for attempt in range(2):
            data = ak_fetch_fund_flow(code)
            if data:
                break
            time.sleep(interval * 2)
        if not data:
            failed.append(code)
            fail += 1
            continue
        try:
            con = sqlite3.connect(DB, timeout=60)
            con.executemany(
                "INSERT OR REPLACE INTO fund_flow_daily "
                "(code,date,close,change_pct,main_net,main_ratio,super_net,super_ratio,"
                "large_net,large_ratio,medium_net,medium_ratio,small_net,small_ratio) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
            con.commit()
            con.close()
            ok += 1
            rows += len(data)
        except Exception:
            failed.append(code)
            fail += 1
        time.sleep(interval)
        if (i + 1) % 100 == 0 or i + 1 == len(codes):
            print(f"    [slow] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    return {"ok": ok, "fail": fail, "rows": rows, "failed": failed}


def main():
    from data_manager import init_fund_flow_tables

    args = sys.argv[1:]
    limit = None
    codes_arg = None
    interval = 0.0
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        if a == "--codes" and i + 1 < len(args):
            codes_arg = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        if a == "--interval" and i + 1 < len(args):
            interval = float(args[i + 1])

    init_fund_flow_tables()
    if codes_arg:
        codes = codes_arg
    else:
        con = sqlite3.connect(DB)
        codes = [str(r[0]) for r in con.execute(
            "SELECT code FROM stock_list WHERE status='active' "
            "AND substr(code,1,2) IN ('00','30','60','68') ORDER BY code").fetchall()]
        con.close()
    if limit:
        codes = codes[:limit]

    t0 = time.time()
    if interval > 0:
        # 低频单进程模式(适配东财反爬): 每只间隔 interval 秒
        print(f"=== 资金流低频拉取: {len(codes)} 只 | 间隔 {interval}s ===", flush=True)
        res = _proc_worker_slow(codes, interval)
        ok, fail, rows = res["ok"], res["fail"], res["rows"]
        failed_all = res["failed"]
    else:
        print(f"=== 资金流全历史拉取: {len(codes)} 只 | PROCS={PROCS} ===", flush=True)
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
        print("失败:", ",".join(failed_all[:80]), flush=True)

    con = sqlite3.connect(DB)
    n_code = con.execute("SELECT COUNT(DISTINCT code) FROM fund_flow_daily").fetchone()[0]
    n_row = con.execute("SELECT COUNT(*) FROM fund_flow_daily").fetchone()[0]
    mn = con.execute("SELECT MIN(date) FROM fund_flow_daily").fetchone()[0]
    mx = con.execute("SELECT MAX(date) FROM fund_flow_daily").fetchone()[0]
    con.close()
    print(f"=== fund_flow_daily: {n_code} 只 / {n_row:,} 行 / {mn} ~ {mx} ===", flush=True)


if __name__ == "__main__":
    main()