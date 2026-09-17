# -*- coding: utf-8 -*-
"""rebuild_kline_unified.py — 统一重建 K 线库 (qfq 基准=最新 + volume=股/amount=元).

背景(2026-09-11 审计):
  现库基准混乱: 2016-2022 段 qfq(基准=2026-07) vs 2023+ 段(各时点 qfq≈真实价), 2022/2023 边界断层 ~24%;
  volume 单位 2016-2022=股(新浪) vs 2023+=手(东财/腾讯), amount 口径不一.
主通道: akshare 新浪 stock_zh_a_daily(qfq) — qfq 基准=最新、volume=股/amount=元(真实).
  注意: 新浪接口内部用 py_mini_racer(V8) 解析, 多线程并发构造 MiniRacer 会 native 崩溃 →
        必须多进程(每进程单线程串行拉取) 或 单线程串行. 本脚本用多进程 Pool.
补漏通道: baostock qfq(基准与新浪一致) 串行补拉主通道失败的股票.
指数: akshare 新浪 stock_zh_index_daily 全历史(指数无除权) → kline_YYYY(带 sh/sz 前缀) + 重建 hs300.json.

用法:
  python scripts/rebuild_kline_unified.py            # 全量(股票+指数)
  python scripts/rebuild_kline_unified.py --limit 20 # 冒烟
  python scripts/rebuild_kline_unified.py --codes 600036,000001 --stocks-only
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

PROCS = int(os.environ.get("REBUILD_PROCS", "8"))
DAYS = 4000  # 2015-01-01 至今约 2837 交易日, 4000 留缓冲(新浪全历史 tail)
FAILED: list = []


# ══════════════════════════════════════════════════════════════
#  子进程 worker (每进程单线程, 规避 py_mini_racer V8 并发崩溃)
# ══════════════════════════════════════════════════════════════
def _proc_worker(codes: list) -> dict:
    import akshare as ak
    from data_manager import get_kline_db, _bulk_insert_kline
    from codec import normalize_a_code, ak_symbol

    ok = fail = rows = 0
    failed = []
    for i, code in enumerate(codes):
        try:
            stored = normalize_a_code(code, "stock")
            symbol = ak_symbol(code, "stock")
            df = None
            for attempt in range(3):
                try:
                    time.sleep(random.uniform(0.2, 0.9))
                    df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
                except Exception:
                    df = None
                    time.sleep(1.0 * (attempt + 1))
                if df is not None and not df.empty:
                    break
            if df is None or df.empty:
                failed.append(code)
                fail += 1
                print(f"    EMPTY {code}: df={type(df).__name__ if df is not None else 'None'} "
                      f"empty={df.empty if df is not None else '-'} err={getattr(df,'_err','')}", flush=True)
                continue
            from akshare_source import _normalize_kline_rows
            try:
                data = _normalize_kline_rows(stored, df, days=DAYS)
            except Exception as e:
                data = []
                print(f"    NORMFAIL {code}: {type(e).__name__}: {str(e)[:80]}", flush=True)
            if not data:
                failed.append(code)
                fail += 1
                continue
            conn = get_kline_db()
            try:
                ins, _ = _bulk_insert_kline(conn, data, replace=True)
                conn.commit()
                rows += ins
            finally:
                conn.close()
            ok += 1
        except Exception:
            failed.append(code)
            fail += 1
        if (i + 1) % 50 == 0 or i + 1 == len(codes):
            print(f"    [proc {os.getpid()}] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    _flush(force=True)   # 结束前 flush 残留缓冲(否则每进程最后 <30000 行丢失)
    return {"ok": ok, "fail": fail, "rows": rows, "failed": failed}


def _proc_indexes(codes: list) -> dict:
    """指数: 新浪全历史(单进程). codes 带 sh/sz 前缀."""
    import akshare as ak
    from data_manager import get_kline_db, _bulk_insert_kline
    from akshare_source import _normalize_index_code

    out = []
    for code in codes:
        stored = _normalize_index_code(code)
        try:
            time.sleep(random.uniform(0.3, 1.0))
            df = ak.stock_zh_index_daily(symbol=stored)
            if df is None or df.empty:
                print(f"  {code}: 空", flush=True)
                continue
            df["date"] = df["date"].astype(str)
            rows = []
            for _, bar in df.iterrows():
                try:
                    rows.append((stored, bar["date"].replace("-", ""), float(bar["open"]),
                                 float(bar["high"]), float(bar["low"]), float(bar["close"]),
                                 int(float(bar["volume"])), float(bar.get("amount") or 0.0), 0.0))
                except (ValueError, KeyError):
                    continue
            conn = get_kline_db()
            try:
                ins, _ = _bulk_insert_kline(conn, rows, replace=True)
                conn.commit()
                out.append((code, ins))
            finally:
                conn.close()
        except Exception as e:
            print(f"  {code}: 失败 {type(e).__name__}: {str(e)[:60]}", flush=True)
    return {"rows": out}


def _proc_baostock(codes: list) -> dict:
    """baostock 补漏(串行, 带硬超时)."""
    from akshare_source import _run_with_timeout
    from data_manager import get_kline_db, _bulk_insert_kline

    ok = fail = rows = 0

    def _fetch(code: str) -> list:
        import baostock as bs
        sym = ("sh." if code[0] in "569" else ("bj." if code[0] in "489" else "sz.")) + code

        def _inner():
            lg = bs.login()
            if lg.error_code != "0":
                return []
            try:
                out = []
                for seg in (("2015-01-01", "2020-12-31"), ("2021-01-01", "2026-12-31")):
                    rs = bs.query_history_k_data_plus(
                        sym, "date,code,open,high,low,close,volume,amount,turn",
                        start_date=seg[0], end_date=seg[1], frequency="d", adjustflag="2")
                    if rs.error_code != "0":
                        continue
                    while rs.next():
                        r = rs.get_row_data()
                        try:
                            out.append((code, r[0].replace("-", ""), float(r[2]), float(r[3]),
                                        float(r[4]), float(r[5]), int(float(r[6])), float(r[7]), float(r[8])))
                        except (ValueError, IndexError):
                            continue
                return out
            finally:
                try:
                    bs.logout()
                except Exception:
                    pass

        return _run_with_timeout(_inner, 25) or []

    for i, code in enumerate(codes):
        data = _fetch(code)
        if data:
            conn = get_kline_db()
            try:
                ins, _ = _bulk_insert_kline(conn, data, replace=True)
                conn.commit()
                rows += ins
                ok += 1
            finally:
                conn.close()
        else:
            fail += 1
        if (i + 1) % 50 == 0 or i + 1 == len(codes):
            print(f"    [baostock {os.getpid()}] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    return {"ok": ok, "fail": fail, "rows": rows}


def run_stocks(codes: list, limit: int = None) -> dict:
    import multiprocessing as mp
    codes = codes[:limit] if limit else codes
    t0 = time.time()
    print(f"=== 股票重拉(新浪qfq主通道, 多进程): {len(codes)} 只 | PROCS={PROCS} ===", flush=True)
    chunks = [codes[i::PROCS] for i in range(PROCS)]
    chunks = [c for c in chunks if c]
    ok = fail = rows = 0
    failed: list = []
    with mp.Pool(len(chunks)) as pool:
        for res in pool.imap_unordered(_proc_worker, chunks):
            ok += res["ok"]
            fail += res["fail"]
            rows += res["rows"]
            failed.extend(res["failed"])
    print(f"=== 股票重拉完成: ok={ok} fail={fail} rows={rows} 耗时 {time.time()-t0:.0f}s ===", flush=True)
    if failed:
        print(f"=== baostock 补漏 {len(failed)} 只 ===", flush=True)
        t1 = time.time()
        fchunks = [failed[i::PROCS] for i in range(PROCS)]
        fchunks = [c for c in fchunks if c]
        with mp.Pool(len(fchunks)) as pool:
            for res in pool.imap_unordered(_proc_baostock, fchunks):
                pass
        print(f"=== baostock 补漏完成 耗时 {time.time()-t1:.0f}s ===", flush=True)
        FAILED.extend(failed)
    return {"ok": ok, "fail": fail, "rows": rows}


def run_indexes() -> dict:
    print("=== 指数重拉(新浪) ===", flush=True)
    t0 = time.time()
    res = _proc_indexes(INDEXES)
    print(f"=== 指数重拉完成: {res['rows']} 耗时 {time.time()-t0:.0f}s ===", flush=True)
    return {"rows": res["rows"]}


def rebuild_hs300():
    """从 kline_daily 重建 data/hs300.json."""
    from backend.api.paths import DATA_DIR
    import json
    from data_manager import get_kline_db
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT date, close FROM kline_daily WHERE code='sh000300' ORDER BY date").fetchall()
    conn.close()
    if not rows:
        print("sh000300 无数据, 跳过 hs300.json", flush=True)
        return
    dates = [f"{r[0][:4]}-{r[0][4:6]}-{r[0][6:]}" for r in rows]
    closes = [float(r[1]) for r in rows]
    p = os.path.join(DATA_DIR, "hs300.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"code": "sh000300", "name": "沪深300", "dates": dates, "closes": closes}, f)
    print(f"hs300.json 重建: {len(dates)} 天 ({dates[0]} ~ {dates[-1]})", flush=True)


def load_codes() -> list:
    from data_manager import get_kline_db
    conn = get_kline_db()
    rows = conn.execute(
        "SELECT DISTINCT code FROM stock_list WHERE status='active' ORDER BY code").fetchall()
    conn.close()
    return [str(r[0]) for r in rows]


INDEXES = ["sh000001", "sh000300", "sh000016", "sh000688", "sz399001", "sz399006"]


if __name__ == "__main__":
    args = sys.argv[1:]
    codes_arg = None
    limit = None
    index_only = "--index-only" in args
    stocks_only = "--stocks-only" in args
    for i, a in enumerate(args):
        if a == "--codes" and i + 1 < len(args):
            codes_arg = [c.strip() for c in args[i + 1].split(",") if c.strip()]
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
    if not index_only:
        codes = codes_arg or load_codes()
        run_stocks(codes, limit=limit)
    if not stocks_only:
        run_indexes()
    rebuild_hs300()
    print("完成", flush=True)