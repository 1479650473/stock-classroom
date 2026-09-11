# -*- coding: utf-8 -*-
"""零信号对照（null baseline）—— 检验"超额"是不是构造本身带来的。

做法：不放任何因子，直接用随机分数矩阵当信号（等价于"每天随机选 20 只"），
跑同一套回测（Top-K、持有 5 天重叠建仓、单边 5bp、与等权池比）：
  - 若随机组合也显著为正 → 所谓"超额"来自集中持仓的风格暴露与成本假设，不是因子；
  - 若随机组合 ≈ -成本（默认约 -3%~-4%/年）→ 回测口径自洽，可以拿来当零假设基准。

用法：python -m backend.alpha.diagnose_null --codes 300 --start 2016-01-01 --end 2025-12-31 --seeds 3
"""
from __future__ import annotations

import argparse
import time
from typing import List

import numpy as np

from . import panel as P
from . import reward as R


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    t0 = time.time()
    codes: List[str] = P.pick_universe(limit=args.codes, as_of=args.start)
    pan = P.load_panel(codes, args.start, args.end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats = P.build_features(fields)
    target = P.build_target(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats["_TRADABLE"]
    bench = R.bench_series(target, masks)
    pool_ann = (float(np.prod(1 + bench)) ** (R.TRADING_DAYS / len(bench)) - 1) * 100
    print(f"面板 {len(codes)} 只 × {len(dates)} 日（{dates[0]}~{dates[-1]}），"
          f"等权池全期年化 {pool_ann:+.1f}%（{time.time() - t0:.0f}s）")

    rng = np.random.default_rng(42)
    rows = []
    for i in range(args.seeds):
        noise = rng.standard_normal(target.shape).astype(np.float32)
        m = R.evaluate(noise, target, masks, slice(0, len(dates)), top_k=args.topk,
                       bench_daily=bench, hold=args.hold)
        rows.append(m)
        print(f"  种子{i}：年化 {m['ann'] * 100:+7.1f}% | 超额年化 {m['ex_ann'] * 100:+7.1f}% | "
              f"超额Sortino {m['ex_sortino']:+.2f} | IC {m['ic']:+.4f} | 换手 {m['turnover']:.2f}")
    if rows:
        ex = np.mean([r["ex_ann"] for r in rows]) * 100
        print(f"随机选股平均超额年化 {ex:+.1f}%（应约等于 -换手成本，若显著为正说明口径有偏）")


if __name__ == "__main__":
    main()
