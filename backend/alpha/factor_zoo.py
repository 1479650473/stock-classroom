# -*- coding: utf-8 -*-
"""因子动物园体检 —— 把面板里的每个特征（正/反两个方向）用同一套口径评估一遍。

评估口径（与 walk_forward / validate_known 完全一致，可直接比较）：
  IC(1日)      : 信号 vs 次日开盘到再次日开盘的收益（Spearman，全可交易样本）
  IC(20日前视) : 信号 vs 未来 20 日 open-to-open 收益
  IC(中性)     : 信号先对 [市值代理, 20日波动] 做截面回归取残差后的 IC
  超额年化     : Top-K 组合（持有 hold 天重叠建仓、单边 5bp 成本）相对等权股票池
  分段         : 半年一段的超额收益，看稳定性（几段为正）

用法：
  python -m backend.alpha.factor_zoo --codes 300 --start 2016-01-01 --end 2025-12-31
  python -m backend.alpha.factor_zoo --out data/factor_zoo.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List

import numpy as np

from ..api.paths import DATA_DIR
from . import panel as P
from . import reward as R

TRADING_DAYS = R.TRADING_DAYS


def _fwd(open_: np.ndarray, horizon: int) -> np.ndarray:
    """未来 horizon 日 open-to-open 收益（t 日信号 → t+1 开盘买 → t+1+h 开盘卖）。"""
    out = np.zeros_like(open_)
    if open_.shape[1] > horizon + 1:
        o1 = open_[:, 1:-horizon]
        o2 = open_[:, horizon + 1:]
        ok = (o1 > 0) & (o2 > 0)
        tmp = np.zeros_like(o1)
        tmp[ok] = o2[ok] / o1[ok] - 1.0
        out[:, :-horizon - 1] = tmp
    return out


def _segments(dates: List[str]) -> List[tuple]:
    segs, i = [], 0
    while i < len(dates):
        y, h = dates[i][:4], (int(dates[i][4:6]) - 1) // 6
        j = i
        while j < len(dates) and dates[j][:4] == y and (int(dates[j][4:6]) - 1) // 6 == h:
            j += 1
        segs.append((i, j, f"{dates[i]}~{dates[j - 1]}"))
        i = j
    return segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--top", type=int, default=20, help="打印前 N 名")
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "factor_zoo.json"))
    args = ap.parse_args()

    t0 = time.time()
    codes = P.pick_universe(limit=args.codes, as_of=args.start)
    pan = P.load_panel(codes, args.start, args.end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats = P.build_features(fields)
    target = P.build_target(fields)
    fwd20 = _fwd(fields["open"], 20)
    masks = P.trade_masks(fields)
    trad = feats["_TRADABLE"] > 0.5
    masks["_tradable"] = feats["_TRADABLE"]
    bench = R.bench_series(target, masks)
    nz = P.build_neutralizer(feats, trad)
    segs = _segments(dates)
    pool_ann = (float(np.prod(1 + bench)) ** (TRADING_DAYS / len(bench)) - 1) * 100
    print(f"面板 {len(codes)} 只 × {len(dates)} 日（{dates[0]}~{dates[-1]}），"
          f"等权池年化 {pool_ann:+.1f}%，分段 {len(segs)} 段（{time.time() - t0:.0f}s）\n")

    rows: List[Dict] = []
    for name in P.FEATURE_NAMES:
        base = feats.get(name)
        if base is None:
            continue
        for sign, tag in ((1.0, name), (-1.0, f"-{name}")):
            sig = (base * sign).astype(np.float32)
            sig_n = P.neutralize_apply(sig, nz)
            m = R.evaluate(sig, target, masks, slice(0, len(dates)), top_k=args.topk,
                           bench_daily=bench, hold=args.hold)
            mn = R.evaluate(sig_n, target, masks, slice(0, len(dates)), top_k=args.topk,
                            bench_daily=bench, hold=args.hold)
            ic20 = float(np.mean(R._rank_ic(sig, fwd20, trad)))
            icn = float(np.mean(R._rank_ic(sig_n, target, trad)))
            seg_ex = []
            for lo, hi, _lab in segs:
                ms = R.evaluate(sig, target, masks, slice(lo, hi), top_k=args.topk,
                                bench_daily=bench, hold=args.hold)
                seg_ex.append(round(ms["ex_ann"], 4))
            rows.append({"factor": tag, "ic": round(m["ic"], 5), "ic_ir": round(m["ic_ir"], 4),
                         "ic20": round(ic20, 5), "ic_neutral": round(icn, 5),
                         "ex_ann": round(m["ex_ann"], 4), "ex_neutral": round(mn["ex_ann"], 4),
                         "ex_sortino": round(m["ex_sortino"], 3), "turnover": round(m["turnover"], 3),
                         "maxdd": round(m["maxdd"], 4), "seg_ex": seg_ex,
                         "seg_pos": sum(1 for x in seg_ex if x > 0), "n_seg": len(seg_ex)})

    rows.sort(key=lambda r: -abs(r["ic"]))
    by_ic = sorted(rows, key=lambda r: -r["ic"])
    by_icn = sorted(rows, key=lambda r: -abs(r["ic_neutral"]))
    by_ex = sorted(rows, key=lambda r: -r["ex_ann"])

    def table(title: str, rs: List[Dict], n: int) -> None:
        print(f"\n== {title} ==")
        hdr = (f"{'因子':<14}{'IC':>9}{'IC_IR':>8}{'IC20':>9}{'IC中性':>9}"
               f"{'超额年化':>10}{'超额(中性)':>11}{'Sortino':>9}{'回撤':>8}{'换手':>7}{'分段为正':>9}")
        print(hdr)
        for r in rs[:n]:
            print(f"{r['factor']:<14}{r['ic']:>+9.4f}{r['ic_ir']:>+8.2f}{r['ic20']:>+9.4f}"
                  f"{r['ic_neutral']:>+9.4f}{r['ex_ann'] * 100:>9.1f}%{r['ex_neutral'] * 100:>10.1f}%"
                  f"{r['ex_sortino']:>+9.2f}{r['maxdd'] * 100:>7.1f}%{r['turnover']:>7.2f}"
                  f"{r['seg_pos']:>6}/{r['n_seg'] - 1:<2}")

    table(f"按 |IC| 排序（前 {args.top}）", rows, args.top)
    table(f"按 中性化 IC 绝对值排序（前 {args.top}）", by_icn, args.top)
    table(f"按 超额年化 排序（前 {args.top}）", by_ex, args.top)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"codes": len(codes), "days": len(dates), "start": dates[0],
                            "end": dates[-1], "top_k": args.topk, "hold": args.hold,
                            "pool_ann": round(pool_ann / 100, 4),
                            "elapsed_sec": round(time.time() - t0, 1)},
                   "factors": rows}, f, ensure_ascii=False, indent=1)
    print(f"\n共评估 {len(rows)} 个因子（含反向），报告：{args.out}（用时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
