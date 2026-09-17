# -*- coding: utf-8 -*-
"""fix_volume_zero.py — 修复 volume=0 污染(腾讯源旧 bug 写入) — 用新浪源重拉覆盖.

受影响: 股票行 close>0 但 volume=0 (指数 sh/sz 前缀的 volume=0 属正常, 跳过).
用法: python scripts/fix_volume_zero.py
"""
import multiprocessing as mp
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

DB = os.path.join(ROOT, "data", "kline.db")
PROCS = 8


def _worker(codes: list) -> dict:
    from rebuild_kline_unified import _proc_worker
    return _proc_worker(codes)


def main():
    con = sqlite3.connect(DB)
    c = con.cursor()
    codes = set()
    for t in [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'kline_[0-9][0-9][0-9][0-9]'")]:
        try:
            for r in c.execute(f"SELECT DISTINCT code FROM {t} WHERE (volume=0 OR volume IS NULL) AND close>0"):
                code = str(r[0])
                if not (code.startswith("sh") or code.startswith("sz")):
                    codes.add(code)
        except Exception:
            pass
    con.close()
    codes = sorted(codes)
    print(f"=== 待修复 {len(codes)} 只 (新浪重拉覆盖) ===", flush=True)
    t0 = time.time()
    ok = fail = 0
    chunks = [codes[i::PROCS] for i in range(PROCS)]
    chunks = [ch for ch in chunks if ch]
    with mp.Pool(len(chunks)) as pool:
        for res in pool.imap_unordered(_worker, chunks):
            ok += res["ok"]
            fail += res["fail"]
    print(f"=== 完成: ok={ok} fail={fail} 耗时 {time.time()-t0:.0f}s ===", flush=True)

    # 验证
    con = sqlite3.connect(DB)
    c = con.cursor()
    n = 0
    for t in ["kline_2023", "kline_2024", "kline_2025", "kline_2026"]:
        n += c.execute(f"SELECT COUNT(*) FROM {t} WHERE (volume=0 OR volume IS NULL) AND close>0 "
                       f"AND code NOT LIKE 'sh%' AND code NOT LIKE 'sz%'").fetchone()[0]
    print(f"=== 剩余 volume=0 股票行: {n} ===", flush=True)
    con.close()


if __name__ == "__main__":
    main()