# -*- coding: utf-8 -*-
"""预抓多板块股票池的东财每日估值(基本面) → data/fundamental.db。

构建跨板块平衡研究池: 每板块取前 N 只活跃股(小板块全取) → ~300 只。
已缓存跳过(可恢复), 失败 retry。适合后台跑: 
  C:/Python314/python.exe backend/strategy/prefetch_value_pool.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy import catalog as cat          # noqa: E402
from backend.fundamental import fetch_fundamental, has_vals, init_db, DB_PATH  # noqa: E402

PER_SECTOR = int(os.environ.get("VALUE_POOL_PER_SECTOR", "12"))
SLEEP = float(os.environ.get("VALUE_POOL_SLEEP", "1.0"))


def build_pool(per_sector: int = PER_SECTOR) -> list:
    codes = []
    for s in cat.sectors():
        try:
            items = cat.select(sector=s, status="active")
        except Exception:
            items = []
        codes += [i["code"] for i in items][:per_sector]
    return sorted(set(codes))


def main():
    init_db()
    pool = build_pool()
    print(f"多板块研究池: {len(pool)} 只 | 每板块 ≤ {PER_SECTOR}", flush=True)
    todo = [c for c in pool if not has_vals(c)]
    done = [c for c in pool if has_vals(c)]
    print(f"已缓存 {len(done)}, 待抓 {len(todo)}", flush=True)
    t0 = time.time()
    ok = len(done)
    for i, c in enumerate(todo, 1):
        r = fetch_fundamental(c)
        if r:
            ok += 1
        print(f"  [{i}/{len(todo)}] {c}: {'+%d 天' % len(r) if r else '失败'} "
              f"累计{ok}/{len(pool)} 耗时{time.time()-t0:.0f}s", flush=True)
        time.sleep(SLEEP)
    print(f"=== 完成 {ok}/{len(pool)} | {DB_PATH} | 耗时 {time.time()-t0:.0f}s ===", flush=True)


if __name__ == "__main__":
    main()
