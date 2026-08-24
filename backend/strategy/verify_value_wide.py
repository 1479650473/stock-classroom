# -*- coding: utf-8 -*-
"""价值/质量因子研究验证 — 多板块/全市场池(原始 vs 行业中性化)。

运行:
  C:/Python314/python.exe backend/strategy/verify_value_wide.py          # 多板块池(每板块≤12)
  VALUE_POOL_FULL=1 C:/Python314/python.exe backend/strategy/verify_value_wide.py  # 全市场(原始)
前置: 已跑 prefetch_value_pool.py 缓存基本面(fundamental.db, 已缓存越多覆盖越高)。
输出: 池规模 + EP/BP/ROE 原始与中性化 IC/ICIR/覆盖/多空。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_selector import (  # noqa: E402
    study_value_factors, build_wide_pool, build_full_pool, VALUE_CANDIDATES)
from backend.strategy import catalog as cat  # noqa: E402
from backend.fundamental import has_vals, DB_PATH  # noqa: E402

FULL = os.environ.get("VALUE_POOL_FULL", "0") == "1"


def main():
    results = []
    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("── 价值/质量因子研究 ──")
    if FULL:
        pool = build_full_pool(120)
        label = f"全市场池(原始, {len(pool)} 只)"
    else:
        pool = build_wide_pool(12)
        label = f"多板块池(每板块≤12, {len(pool)} 只)"
    print(f"研究池: {label} | 基本面DB {DB_PATH}")
    secs = len(cat.sectors())
    cached = sum(1 for c in pool if has_vals(c))
    print(f"板块数 {secs} | 已缓存基本面 {cached}/{len(pool)}")
    chk("池规模 ≥ 200", len(pool) >= 200, f"{len(pool)} 只")
    if FULL:
        msg = "已建库" if cached / max(len(pool), 1) >= 0.95 else "抓取中"
        print(f"      [全市场{msg}] 基本面已缓存 {cached}/{len(pool)}")
    else:
        chk("基本面覆盖 ≥ 60%", cached / max(len(pool), 1) >= 0.6, f"{cached}/{len(pool)}")
    # 研究只用已缓存(避免触发抓取)
    pool_cached = [c for c in pool if has_vals(c)]

    start, end = "2024-01-01", "2026-06-01"
    print("\n── 原始(不中性化) ──")
    raw = study_value_factors(pool_cached, start, end, neutralize_industry=False)
    for v in raw:
        chk(f"EP/BP/ROE[{v['dsl_key']}] 原始IC/ICIR",
            isinstance(v.get("ic"), float) and len(v.get("research", {}).get("groupCurves", [])) == 5,
            f"IC={v['ic']:.3f} ICIR={v['icir']:.2f} 覆盖={v['coverage']:.0%} 多空净={v['net_long_short']:+.2%}")

    if not FULL:
        print("\n── 行业中性化(去板块效应, 需有板块标注) ──")
        neut = study_value_factors(pool_cached, start, end, neutralize_industry=True)
        for v in neut:
            chk(f"EP/BP/ROE[{v['dsl_key']}] 中性化IC/ICIR",
                isinstance(v.get("ic"), float) and v.get("neutralized") is True,
                f"IC={v['ic']:.3f} ICIR={v['icir']:.2f} 覆盖={v['coverage']:.0%} 多空净={v['net_long_short']:+.2%}")
    else:
        print("  (全市场池多数无板块标注 → 跳过中性化; 中性化见多板块模式)")

    ok = all(x[1] for x in results)
    print(f"\n价值/质量研究: {sum(1 for x in results if x[1])}/{len(results)} 通过 (覆盖 {cached}/{len(pool)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
