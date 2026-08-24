# -*- coding: utf-8 -*-
"""跨板块价值/质量因子研究验证 — 全市场/多板块池(原始 vs 行业中性化)。

运行: C:/Python314/python.exe backend/strategy/verify_value_wide.py
前置: 已跑 prefetch_value_pool.py 缓存多板块基本面(fundamental.db)。
输出: 池规模 + EP/BP/ROE 原始与中性化 IC/ICIR/覆盖/多空 + 板块中性化可用性。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_selector import study_value_factors, build_wide_pool  # noqa: E402
from backend.strategy import catalog as cat  # noqa: E402
from backend.fundamental import has_vals, DB_PATH  # noqa: E402


def main():
    results = []
    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("── 跨板块价值/质量因子研究 ──")
    pool = build_wide_pool(12)
    sec_counts = {}
    for s in cat.sectors():
        try:
            sec_counts[s] = len([i for i in cat.select(sector=s, status="active")])
        except Exception:
            pass
    print(f"研究池: {len(pool)} 只 | 板块数 {len(sec_counts)} | 基本面DB {DB_PATH}")
    cached = sum(1 for c in pool if has_vals(c))
    print(f"已缓存基本面: {cached}/{len(pool)}")
    chk("池规模 ≥ 200(多板块)", len(pool) >= 200, f"{len(pool)} 只")
    chk("基本面覆盖 ≥ 80%", cached / max(len(pool), 1) >= 0.8, f"{cached}/{len(pool)}")

    start, end = "2024-01-01", "2026-06-01"
    raw = study_value_factors(pool, start, end, neutralize_industry=False)
    neut = study_value_factors(pool, start, end, neutralize_industry=True)
    print("\n── 原始(不中性化) ──")
    for v in raw:
        chk(f"EP/BP/ROE[{v['dsl_key']}] 原始IC/ICIR",
            isinstance(v.get("ic"), float) and len(v.get("research", {}).get("groupCurves", [])) == 5,
            f"IC={v['ic']:.3f} ICIR={v['icir']:.2f} 覆盖={v['coverage']:.0%} 多空净={v['net_long_short']:+.2%}")
    print("\n── 行业中性化(去板块效应) ──")
    for v in neut:
        chk(f"EP/BP/ROE[{v['dsl_key']}] 中性化IC/ICIR",
            isinstance(v.get("ic"), float) and v.get("neutralized") is True,
            f"IC={v['ic']:.3f} ICIR={v['icir']:.2f} 覆盖={v['coverage']:.0%} 多空净={v['net_long_short']:+.2%}")

    ok = all(x[1] for x in results)
    print(f"\n跨板块价值/质量研究: {sum(1 for x in results if x[1])}/{len(results)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
