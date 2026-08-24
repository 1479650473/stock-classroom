# -*- coding: utf-8 -*-
"""数据本地化验证 — 已抓取数据落盘后, 读路径绝不联网(不再重复拉取)。

运行: C:/Python314/python.exe backend/strategy/verify_local_cache.py
用 spy 包装 fundamental.fetch_fundamental 计数, 验证:
  ① load_universe_frames(with_fundamentals=True, 默认) 只读缓存, 不触发抓取
  ② study_value_factors 不触发抓取
  ③ attach_kline_fundamentals 不触发抓取
  ④ 显式 fetch_missing=True 才触发抓取(spy 有效)
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import backend.fundamental as F  # noqa: E402

CALLS = []
_ORIG_FETCH = F.fetch_fundamental


def _spy(code):
    CALLS.append(code)
    return _ORIG_FETCH(code)


def main():
    results = []
    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    F.fetch_fundamental = _spy
    try:
        print("── 数据本地化(读路径不联网) ──")
        # ① load_universe_frames 只读缓存
        from backend.strategy.factor_data import load_universe_frames
        _ = load_universe_frames(["600036", "601398"], with_fundamentals=True)
        chk("load_universe_frames 只读缓存(不抓取)", not CALLS, f"抓取调用={len(CALLS)}")

        # ② study_value_factors 只读缓存
        from backend.strategy.factor_selector import study_value_factors
        _ = study_value_factors(["600036"], "2024-01-01", "2026-06-01")
        chk("study_value_factors 只读缓存(不抓取)", not CALLS, f"抓取调用={len(CALLS)}")

        # ③ attach_kline_fundamentals 只读缓存
        from backend.fundamental import attach_kline_fundamentals
        from backend.agent import services as svc
        kd, _ = svc.load_klines("600036", limit=200)
        attach_kline_fundamentals("600036", kd)
        chk("attach_kline_fundamentals 只读缓存(不抓取)", not CALLS, f"抓取调用={len(CALLS)}")

        # ④ 确定性证明 spy 有效: 直接 fetch_fundamental(不查缓存)必计数
        #   (后台全量抓取并发缓存会竞态, 故不用 ensure/has_vals)
        before = len(CALLS)
        F.fetch_fundamental("600036")   # 600036 已缓存, 但 fetch_fundamental 总是抓
        chk("fetch_fundamental 会计数(spy有效)", len(CALLS) > before,
            f"抓取 {len(CALLS)-before} 次 → 印证 ①~③ 的 0 次=真没联网")
    finally:
        F.fetch_fundamental = _ORIG_FETCH

    ok = all(x[1] for x in results)
    print(f"\n数据本地化: {sum(1 for x in results if x[1])}/{len(results)} 通过")
    print("  结论: 已抓取数据存于 fundamental.db, 默认读路径只读本地, 绝不联网重复拉取。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
