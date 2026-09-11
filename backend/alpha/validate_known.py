# -*- coding: utf-8 -*-
"""流程自检：把**已知有效**的公开因子喂进同一套回测，看能不能被识别出来。

这是诊断"是搜索问题还是评估口径问题"的关键一步：
  - 如果已知因子（20 日反转、低换手、低波动、小市值代理…）在这套口径下
    IC 正常为正、超额也正常 → 评估管线没问题，之前挖不出来是**搜索/因子空间**的问题；
  - 如果连已知因子都测出 IC≈0 或方向反常 → 是**口径/数据/对齐**有 bug，先修管线。

用法：python -m backend.alpha.validate_known --codes 300 --start 2016-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, List, Tuple

import numpy as np

from . import panel as P
from . import reward as R
from .dsl import decode, interpret

#: 已知因子（token 为 Polish 前缀记法）与预期方向
KNOWN: Dict[str, Tuple[List[str], str]] = {
    "20日反转": (["NEG", "RET20"], "多头偏向跌得多的（A股短期反转，预期 IC>0）"),
    "5日反转": (["NEG", "RET5"], "同上，更短周期"),
    "20日动量": (["RET20"], "多头偏向涨得多的（预期 IC<0，与反转互斥）"),
    "60日趋势": (["TREND60"], "相对 MA60 的趋势强度"),
    "低波动": (["NEG", "STD20", "RET1"], "低波动溢价（预期 IC>0）"),
    "高波动": (["STD20", "RET1"], "对照"),
    "低换手": (["NEG", "TURN_RATIO"], "低换手溢价（预期 IC>0）"),
    "高换手": (["TURN_RATIO"], "对照：投机度高"),
    "RSI 反转": (["NEG", "RSI14"], "超买回落"),
    "缩量": (["NEG", "AMT_TREND"], "成交额趋势向下"),
    "小市值代理": (["NEG", "LOG_AMT20"], "成交额小 ≈ 市值小（预期 IC>0）"),
    "大市值代理": (["LOG_AMT20"], "对照"),
    "反转+低波": (["ADD", "NEG", "RET20", "NEG", "STD20", "RET1"], "两因子等权相加"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--start-folds", default="2020-12-01", help="逐段统计的起点（与 10 折验证对齐）")
    args = ap.parse_args()

    t0 = time.time()
    codes = P.pick_universe(limit=args.codes, as_of=args.start)
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
          f"等权池全期年化 {pool_ann:+.1f}%（{time.time() - t0:.0f}s）\n")

    # 与 10 折验证同口径的 6 个月分段（用于看因子在各阶段的稳定性）
    seg_start = next((i for i, d in enumerate(dates) if d[:6] >= args.start_folds.replace("-", "")), 0)
    segs: List[Tuple[int, int, str]] = []
    i = seg_start
    while i < len(dates):
        j = i
        ym = dates[i][:6]
        while j < len(dates) and _same_half(dates[j], ym):
            j += 1
        segs.append((i, j, f"{dates[i]}~{dates[j - 1]}"))
        i = j

    # 长周期前视收益（20 日前视），用于区分"信号慢 + 目标太短"导致的 IC≈0
    open_ = fields["open"]
    fwd1 = target.copy()
    fwd20 = np.zeros_like(open_)
    if open_.shape[1] > 21:
        o1 = open_[:, 1:-20]
        o2 = open_[:, 21:]
        ok = (o1 > 0) & (o2 > 0)
        tmp = np.zeros_like(o1)
        tmp[ok] = o2[ok] / o1[ok] - 1.0
        fwd20[:, :-21] = tmp
    hdr = (f"{'因子':<12}{'IC(1日)':>10}{'IC(20日)':>10}{'年化':>9}{'超额年化':>10}"
           f"{'超额Sortino':>12}{'回撤':>8}{'换手':>7}   分段超额(6个月)")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for name, (tokens, _note) in KNOWN.items():
        sig = interpret(tokens, feats)
        if sig is None:
            print(f"{name:<12}  公式非法：{decode(tokens)}")
            continue
        m = R.evaluate(sig, target, masks, slice(0, len(dates)), top_k=args.topk,
                       bench_daily=bench, hold=args.hold)
        seg_ex = []
        for lo, hi, _label in segs:
            ms = R.evaluate(sig, target, masks, slice(lo, hi), top_k=args.topk,
                            bench_daily=bench, hold=args.hold)
            seg_ex.append(ms["ex_ann"])
        ic20 = float(np.mean(R._rank_ic(sig, fwd20, masks["_tradable"] > 0.5)))
        segs_str = " ".join(f"{x * 100:+.0f}" for x in seg_ex)
        pos = sum(1 for x in seg_ex if x > 0)
        print(f"{name:<12}{m['ic']:>+10.4f}{ic20:>+10.4f}{m['ann'] * 100:>8.1f}%"
              f"{m['ex_ann'] * 100:>9.1f}%{m['ex_sortino']:>+12.2f}{m['maxdd'] * 100:>7.1f}%"
              f"{m['turnover']:>7.2f}   {segs_str}  ({pos}/{len(seg_ex)} 段为正)")
        rows.append({"name": name, "formula": decode(tokens), "ic": m["ic"], "ic_ir": m["ic_ir"],
                     "ann": m["ann"], "ex_ann": m["ex_ann"], "ex_sortino": m["ex_sortino"],
                     "turnover": m["turnover"], "seg_ex": seg_ex, "seg_positive": pos,
                     "n_seg": len(seg_ex)})

    print(f"\n判定参考：全期 IC 若普遍 |IC| < 0.01 且方向不定 → 评估口径有问题；"
          f"若反转/低换手/小市值呈稳定正 IC 与正超额 → 管线正常，是搜索没找到。")
    print(f"（用时 {time.time() - t0:.0f}s）")


def _same_half(d: str, ym: str) -> bool:
    """半年一段：1-6 月 / 7-12 月。"""
    y, m = d[:4], int(d[4:6])
    y0, m0 = ym[:4], int(ym[4:6])
    return y == y0 and ((m - 1) // 6) == ((m0 - 1) // 6)


if __name__ == "__main__":
    main()
