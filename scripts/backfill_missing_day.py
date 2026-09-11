# -*- coding: utf-8 -*-
"""backfill_missing_day.py — 补齐「某一天只有部分股票有数据」的残缺交易日。

背景：`update_daily.py` 的全市场增量按「库内最新日期 → 今天」的**全局**缺口决定回看窗口，
当某天只落了部分股票时（实测 2026-09-11：5194 只里只有 1689 只），缺口算出来是 0，
之后每天都会认为"已是最新"，永远不会补。

本脚本按**逐股票**判断：找出「上一交易日有数据、目标日没有数据」的股票，只补这些，
每 200 只落一次库（进度可见、可中断续跑）。

用法：
    python scripts/backfill_missing_day.py                 # 目标日=库内最新日期
    python scripts/backfill_missing_day.py --date 20260911 --workers 16 --chunk 200
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="目标日期 YYYYMMDD（默认=库内最新日期）")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--chunk", type=int, default=200, help="每多少只落一次库")
    ap.add_argument("--days", type=int, default=8, help="每只股票抓取的 bar 数")
    args = ap.parse_args()

    from data_manager import get_kline_db, _bulk_insert_kline
    from akshare_source import ak_fetch_kline

    con = get_kline_db()
    target = args.date or str(con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0])
    dates = [str(r[0]) for r in con.execute(
        "SELECT DISTINCT date FROM kline_daily WHERE date<? ORDER BY date DESC LIMIT 2", (target,))]
    prev = dates[0] if dates else None          # dates 是 DESC，第一个才是紧邻的上一交易日
    have = {str(r[0]) for r in con.execute(
        "SELECT DISTINCT code FROM kline_daily WHERE date=?", (target,))}
    active = [str(r[0]) for r in con.execute(
        "SELECT code FROM stock_list WHERE status='active' OR status IS NULL")]
    prev_codes = {str(r[0]) for r in con.execute(
        "SELECT DISTINCT code FROM kline_daily WHERE date=?", (prev,))} if prev else set()
    todo = [c for c in active if c in prev_codes and c not in have]
    con.close()
    print(f"目标日 {target}（上一交易日 {prev}）：已有 {len(have)} 只，待补 {len(todo)} 只", flush=True)
    if not todo:
        return

    t0 = time.time()
    done = ok = fail = rows_added = 0
    for i in range(0, len(todo), args.chunk):
        chunk = todo[i:i + args.chunk]
        batch = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(ak_fetch_kline, c, args.days): c for c in chunk}
            for f in as_completed(futs):
                done += 1
                try:
                    rows = f.result(timeout=25) or []
                except Exception:
                    rows = []
                if rows:
                    ok += 1
                    batch.extend(rows)
                else:
                    fail += 1
        if batch:
            conn = get_kline_db()
            inserted, _skip = _bulk_insert_kline(conn, batch, replace=True)
            conn.commit()
            conn.close()
            rows_added += int(inserted or 0)
        print(f"  [{done}/{len(todo)}] ok={ok} fail={fail} 新增行={rows_added} "
              f"用时 {time.time() - t0:.0f}s", flush=True)
    con = get_kline_db()
    final = con.execute("SELECT COUNT(DISTINCT code) FROM kline_daily WHERE date=?", (target,)).fetchone()[0]
    con.close()
    print(f"完成：{target} 覆盖 {final} 只（补前 {len(have)}），新增 {rows_added} 行，"
          f"用时 {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
