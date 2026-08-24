# -*- coding: utf-8 -*-
"""补抓 2018-2021 历史 K 线(新浪 stock_zh_a_daily 全历史) — 解锁真正的熊市跨周期价值验证。

背景: kline_2018..kline_2021 各年仅 ~1 只股(当年只抓了单票), 导致 2018/2019-21 深熊无法做全市场
     跨周期研究。本脚本对每个活跃股补抓该区间 K 线 → 写入对应的 kline_YYYY 年度分表。

原理(契合 data_manager):
  * ak_fetch_kline(code, days=2500) 用新浪 stock_zh_a_daily 取**全历史**再 tail(days) → 覆盖 2016→now。
  * 只把 fetched 行的年份落在 2016-2021 的行写入 kline_YYYY(表已存在, 不重建视图, 避免并发 DDL 冲突)。
  * INSERT OR REPLACE 幂等; 按代码 MIN(date)>='20180101' 判断是否缺 2018-2021 → 可恢复(重跑跳过已补齐)。
  * 并发抓取(ThreadPoolExecutor) + 单写连接串行写入(threading.Lock), WAL。
运行: C:/Python314/python.exe backend/strategy/prefetch_kline_history.py
环境: 可 KLINE_BACKFILL_LIMIT=<N> 限制只抓前 N 只(冒烟); 默认全市场活跃池。
"""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

# akshare_source 从 backend/ 导入(相对), 故把 backend 加进 sys.path 已足够
from akshare_source import ak_fetch_kline  # noqa: E402
from strategy.data import get_kline_db_path  # noqa: E402
from strategy.factor_selector import build_full_pool  # noqa: E402

BACKFILL_YEARS = {str(y) for y in range(2016, 2022)}  # 2016-2021(留 buffer 供前向 MA/动量 warmup)
MISSING_THRESHOLD = "20180101"
DAYS = 2500
WORKERS = int(os.environ.get("KLINE_BACKFILL_WORKERS", "12"))

_wlock = threading.Lock()
_write_conn = None


def _get_write_conn():
    global _write_conn
    if _write_conn is None:
        _write_conn = sqlite3.connect(get_kline_db_path(), timeout=60, check_same_thread=False)
        _write_conn.execute("PRAGMA journal_mode=WAL")
        _write_conn.execute("PRAGMA synchronous=NORMAL")
    return _write_conn


def _min_kline_date(code: str) -> str:
    try:
        c = sqlite3.connect(get_kline_db_path(), timeout=30)
        r = c.execute("SELECT MIN(date) FROM kline_daily WHERE code=?", (code,)).fetchone()
        c.close()
        return r[0] or "99999999"
    except Exception:
        return "99999999"


def _write_stock(rows) -> int:
    """把某个股 fetched 行中落在 BACKFILL_YEARS 的行写入 kline_YYYY(表已存在, 不重建视图)。"""
    if not rows:
        return 0
    by_year: dict[str, list] = {}
    for r in rows:
        y = str(r[1])[:4]
        if y in BACKFILL_YEARS:
            by_year.setdefault(y, []).append(tuple(r) if len(r) >= 9 else tuple(r) + (0,))
    if not by_year:
        return 0
    n = 0
    with _wlock:
        conn = _get_write_conn()
        for y, batch in by_year.items():
            tbl = f"kline_{y}"
            try:
                conn.executemany(f"INSERT OR REPLACE INTO {tbl} "
                                 f"(code,date,open,high,low,close,volume,amount,turnover) "
                                 f"VALUES (?,?,?,?,?,?,?,?,?)", batch)
                n += len(batch)
            except sqlite3.Error as e:
                print(f"    [写失败 kline_{y}] {str(e)[:50]}", flush=True)
        conn.commit()
    return n


def backfill_one(code: str) -> tuple:
    """单只: 若缺 2018-2021 则抓取+写入。返回 (code, 新增行数, 状态)。"""
    if _min_kline_date(code) <= MISSING_THRESHOLD:
        return code, 0, "skip"          # 已回补到 2018, 跳过(可恢复)
    try:
        rows = ak_fetch_kline(code, days=DAYS)
    except Exception as e:
        return code, 0, "fetch_err:" + str(e)[:40]
    if not rows:
        return code, 0, "empty"
    rows = [r for r in rows if r[1] < "20220101"]  # 只写 2021 及以前(2022+ 已完整, 避免多余 IO)
    added = _write_stock(rows)
    return code, added, "ok"


def main() -> int:
    limit_env = os.environ.get("KLINE_BACKFILL_LIMIT")
    pool = build_full_pool()
    if limit_env:
        pool = pool[: int(limit_env)]
    print(f"=== 补抓 2018-2021 历史 K 线(新浪全历史) ===", flush=True)
    print(f"池: {len(pool)} 只 | WORKERS={WORKERS} | DAYS={DAYS} | 补抓年份 2016-2021", flush=True)
    t0 = time.time()
    done_fetch = done_write = errors = skipped = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(backfill_one, c): c for c in pool}
        for f in as_completed(futs):
            try:
                code, added, status = f.result()
            except Exception as e:
                code, added, status = "?", 0, "task_err:" + str(e)[:30]
            done_fetch += 1
            if status == "skip":
                skipped += 1
            elif status == "ok":
                done_write += 1
                done_fetch0 = done_write + errors  # 实际发起抓取数
            else:
                errors += 1
            if added:
                print(f"  +{added:5d} 行  {code}", flush=True)
            if done_fetch % 200 == 0:
                el = time.time() - t0
                spd = done_fetch / el if el > 0 else 0
                print(f"  [进度 {done_fetch}/{len(pool)}] 补写{done_write} 跳过{skipped} "
                    f"失败{errors} {spd:.1f}只/s ETA {max(0,(len(pool)-done_fetch))/spd if spd>0 else 0:.0f}s", flush=True)

    print(f"\n完成: 抓取{len(pool)} 补写{done_write} 跳过{skipped} 失败{errors} "
          f"总耗时 {time.time()-t0:.0f}s", flush=True)
    # 校验: 2018-2021 年度广度
    conn = _get_write_conn()
    try:
        for y in (2018, 2019, 2020, 2021):
            n = conn.execute(f"SELECT COUNT(DISTINCT code) FROM kline_{y}").fetchone()[0]
            print(f"  kline_{y}: {n} 只", flush=True)
    except Exception as e:
        print(f"  校验失败: {e}", flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
