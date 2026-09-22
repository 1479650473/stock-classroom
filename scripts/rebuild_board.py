# -*- coding: utf-8 -*-
"""rebuild_board.py — 概念/行业板块指数全历史首拉(THS, 375概念+90行业).

用法:
  python scripts/rebuild_board.py                # 全量
  python scripts/rebuild_board.py --recent 10    # 最近 10 天增量
  python scripts/rebuild_board.py --names 人工智能,半导体
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main():
    from data_manager import init_board_tables, cache_board_list, update_board_daily
    args = sys.argv[1:]
    recent = 0
    for i, a in enumerate(args):
        if a == "--recent" and i + 1 < len(args):
            recent = int(args[i + 1])

    init_board_tables()
    n = cache_board_list()
    print(f"=== 板块列表: {n} 个 ===", flush=True)
    t0 = time.time()
    res = update_board_daily(recent_days=recent, workers=8,
                             progress=lambda m, p=None: print("  " + str(m), flush=True))
    print(f"=== 完成: {res} ({time.time()-t0:.0f}s) ===", flush=True)

    import sqlite3
    con = sqlite3.connect(os.path.join(ROOT, "data", "kline.db"))
    r = con.execute("SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) FROM board_daily").fetchone()
    print(f"=== board_daily: {r[0]:,} 行 / {r[1]} 板块 / {r[2]} ~ {r[3]} ===", flush=True)
    con.close()


if __name__ == "__main__":
    main()