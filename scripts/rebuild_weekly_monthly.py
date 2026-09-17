# -*- coding: utf-8 -*-
"""rebuild_weekly_monthly.py — 从日K聚合重建周K/月K (委托 data_manager.rebuild_period_kline).

用法:
  python scripts/rebuild_weekly_monthly.py              # 全量重建
  python scripts/rebuild_weekly_monthly.py --recent 60  # 仅重建最近60天(每日增量用)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main():
    from data_manager import rebuild_period_kline
    recent = 0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--recent" and i + 1 < len(args):
            recent = int(args[i + 1])
    res = rebuild_period_kline(recent_days=recent,
                               progress=lambda m, p=None: print("  " + str(m), flush=True))
    print(f"=== kline_weekly: {res['weekly']:,} 行 | kline_monthly: {res['monthly']:,} 行 "
          f"({res['elapsed']}s) ===", flush=True)


if __name__ == "__main__":
    main()
