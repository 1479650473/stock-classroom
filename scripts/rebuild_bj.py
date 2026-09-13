# -*- coding: utf-8 -*-
"""rebuild_bj.py — 补齐**北交所**（含原新三板精选层）全历史日线，入 kline.db。

背景：库里此前完全没有北交所股票（83/87/43/920 共 0 只），导致
  ① 「最小市值 N 只」这类微盘策略永远选不到北交所标的；
  ② 与公开实证（知乎文章同窗口 +35%）无法对齐 —— 对方的全市场包含北交所。
本脚本按官方北交所名单逐只拉取，与库内既有口径完全一致：
  - 前复权（qfq）开高低收；`volume` 单位为**股**，`amount` 单位为**元**；
  - `turnover` 存**百分数**（新浪原始是小数，×100，已用 000001 逐值比对确认一致）；
  - 日期 `YYYYMMDD` 字符串，写入 `kline_YYYY` 年度分表（`kline_daily` 是视图）。

用法：
    python scripts/rebuild_bj.py                      # 全部（可中断续跑）
    python scripts/rebuild_bj.py --workers 6 --force  # 重拉
    python scripts/rebuild_bj.py --codes 920000,832000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def bj_universe() -> list[tuple[str, str, str]]:
    """北交所股票名单 → [(code, name, listed_date)]"""
    import akshare as ak

    df = ak.stock_info_bj_name_code()
    out: list[tuple[str, str, str]] = []
    for _, r in df.iterrows():
        code = str(r["证券代码"]).zfill(6)
        name = str(r["证券简称"]).strip()
        ld = str(r.get("上市日期") or "").strip().replace("-", "")
        out.append((code, name, ld))
    return out


def fetch_one(code: str, retries: int = 3) -> list[tuple]:
    """拉一只北交所股票的全历史 → [(code,date,o,h,l,c,vol,amt,turnover%)]"""
    import akshare as ak
    import pandas as pd

    for i in range(retries):
        try:
            df = ak.stock_zh_a_daily(symbol=f"bj{code}", adjust="qfq")
            if df is None or len(df) == 0:
                return []
            d = df.copy()
            d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y%m%d")
            rows = []
            for _, b in d.iterrows():
                try:
                    vol = float(b.get("volume", 0) or 0)
                    amt = float(b.get("amount", 0) or 0)
                    close = float(b["close"])
                    if not amt and vol:
                        amt = close * vol
                    turn = float(b.get("turnover", 0) or 0) * 100.0   # 新浪给小数 → 百分数
                    rows.append((code, str(b["date"]), float(b["open"]), float(b["high"]),
                                 float(b["low"]), close, int(vol), amt, turn))
                except Exception:
                    continue
            return rows
        except Exception as e:
            if i == retries - 1:
                print(f"  ! {code} 失败: {type(e).__name__} {str(e)[:80]}", flush=True)
                return []
            time.sleep(0.8 * (i + 1) + random.random())
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4, help="并发数（多进程，每进程独立 V8）")
    ap.add_argument("--mode", default="proc", choices=["proc", "thread"],
                    help="proc=多进程（默认，安全）；thread=线程（V8 会崩，仅小样本用）")
    ap.add_argument("--codes", default="", help="只跑这些代码（逗号分隔）")
    ap.add_argument("--force", action="store_true", help="已有数据的也重拉")
    ap.add_argument("--chunk", type=int, default=40, help="每多少只落一次库")
    ap.add_argument("--out", default=os.path.join(str(ROOT), "data", "bj_rebuild.json"))
    args = ap.parse_args()

    from data_manager import get_kline_db, _bulk_insert_kline, _rebuild_kline_view

    t0 = time.time()
    print("拉取北交所名单…", flush=True)
    uni = bj_universe()
    print(f"名单 {len(uni)} 只", flush=True)
    if args.codes:
        want = {c.strip().zfill(6) for c in args.codes.split(",") if c.strip()}
        uni = [u for u in uni if u[0] in want]

    con = get_kline_db()
    done = {str(c) for (c,) in con.execute("SELECT code FROM stock_list WHERE board='bj'")}
    if not args.force:
        # 已有最新数据的跳过（续跑）：以库内最新交易日为参照
        last_day = str(con.execute("SELECT MAX(date) FROM kline_daily WHERE code LIKE '9%' "
                                   "OR code LIKE '8%' OR code LIKE '4%'").fetchone()[0] or "")
        fresh = {str(c) for (c,) in con.execute(
            "SELECT DISTINCT code FROM kline_daily WHERE date=? AND (code LIKE '9%' OR code "
            "LIKE '8%' OR code LIKE '4%')", (last_day,))}
        skipped = [u for u in uni if u[0] in fresh]
        uni = [u for u in uni if u[0] not in fresh]
        if skipped:
            print(f"跳过已最新 {len(skipped)} 只（库内 {last_day}）", flush=True)

    total_rows = 0
    ok_codes, empty_codes, fail_codes = [], [], []
    buf: list[tuple] = []
    done_n = 0

    def flush():
        nonlocal buf, total_rows
        if not buf:
            return
        n, _ = _bulk_insert_kline(con, buf)
        total_rows += n
        buf = []

    def save(code, name, ld, rows):
        """把一只股票的结果落库（含 stock_list 元数据）。"""
        nonlocal buf
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not rows:
            return
        buf.extend(rows)
        ok_codes.append(code)
        con.execute(
            "INSERT INTO stock_list(code,name,board,status,listed_date,updated_at,last_date,total_days) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET "
            "name=excluded.name, board='bj', status='active', listed_date=excluded.listed_date, "
            "updated_at=excluded.updated_at, last_date=excluded.last_date, total_days=excluded.total_days",
            (code, name, "bj", "active", ld or None, now, str(rows[-1][1]), len(rows)))

    if args.mode == "thread":
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {ex.submit(fetch_one, code): (code, name, ld) for code, name, ld in uni}
            for fut in as_completed(futs):
                code, name, ld = futs[fut]
                try:
                    rows = fut.result()
                except Exception:
                    rows = []
                done_n += 1
                if rows:
                    save(code, name, ld, rows)
                elif code not in done:
                    empty_codes.append(code)
                if done_n % 25 == 0:
                    flush(); con.commit()
                    print(f"  进度 {done_n}/{len(uni)}｜累计 {total_rows} 行｜{time.time()-t0:.0f}s", flush=True)
                if len(buf) >= 3000:
                    flush(); con.commit()
    else:
        # 多进程：py_mini_racer(V8) 在线程并发下会崩进程（实测 6 并发即崩），
        # 但每进程各自持有独立 V8 上下文是安全的。
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool
        todo = [u for u in uni]
        while todo:
            batch = todo[: args.workers * 4]
            todo = todo[len(batch):]
            left = list(batch)
            for attempt in range(2):
                if not left:
                    break
                try:
                    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as ex:
                        futs = {ex.submit(fetch_one, code): (code, name, ld) for code, name, ld in left}
                        remain: list[tuple] = []
                        for fut in as_completed(futs):
                            code, name, ld = futs[fut]
                            try:
                                rows = fut.result()
                            except Exception:
                                rows = []
                            done_n += 1
                            if rows:
                                save(code, name, ld, rows)
                            elif code not in done:
                                remain.append((code, name, ld))
                            if done_n % 25 == 0:
                                flush(); con.commit()
                                print(f"  进度 {done_n}/{len(uni)}｜累计 {total_rows} 行｜{time.time()-t0:.0f}s", flush=True)
                            if len(buf) >= 3000:
                                flush(); con.commit()
                        left = remain
                except BrokenProcessPool:
                    flush(); con.commit()
                    print(f"  ! 子进程崩溃（V8），降并发重试剩余 {len(left)} 只", flush=True)
                    args.workers = max(1, args.workers // 2)
                    time.sleep(2)
            for code, name, ld in left:
                empty_codes.append(code)
            flush(); con.commit()
    _rebuild_kline_view(con)
    try:
        con.execute("ANALYZE")
        con.commit()
    except Exception:
        pass

    n_bj = con.execute("SELECT COUNT(*) FROM stock_list WHERE board='bj'").fetchone()[0]
    rows_bj = con.execute("SELECT COUNT(*) FROM kline_daily WHERE code IN "
                          "(SELECT code FROM stock_list WHERE board='bj')").fetchone()[0]
    con.close()
    res = {"listed": len(uni), "ok": len(ok_codes), "empty": len(empty_codes),
           "failed_codes": fail_codes, "rows_inserted": total_rows,
           "bj_codes_in_db": n_bj, "bj_rows_in_db": rows_bj,
           "elapsed_sec": round(time.time() - t0, 1),
           "empty_codes": empty_codes[:30]}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
