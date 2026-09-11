# -*- coding: utf-8 -*-
"""组合因子验证 —— 用体检台挑出的「低波动 + 短期反转 + 远离高点」合成一个打分，
按 10 折滚动窗口（与 walk_forward 同口径）做样本外验证，并给出随机对照。

不用搜索，直接固定权重（等权 rank 合成），因此没有"挑选偏差"，检验的是
这批因子本身是否真的稳定。用法：
  python -m backend.alpha.composite_test --codes 300 --start 2016-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List, Tuple

import numpy as np

from ..api.paths import DATA_DIR
from . import panel as P
from . import reward as R
from .walk_forward import build_folds

#: 组合成分（体检台里"中性化后仍为正 + 分段稳定"的因子），等权
COMPOSITE: List[Tuple[str, float]] = [
    ("ATR14", -1.0),      # 低波动
    ("AMP", -1.0),        # 低振幅
    ("HIGH60_GAP", -1.0), # 远离 60 日高点（超跌/便宜）
    ("RET1", -1.0),       # 1 日反转
    ("TREND5", -1.0),     # 5 日均线乖离反转
    ("TURN_STD20", -1.0), # 换手率波动小
    ("VOL20", -1.0),      # 低波动（另一口径）
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--folds", type=int, default=10)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--neutralize", action="store_true", help="对组合分再做风格中性化")
    ap.add_argument("--components", default="", help='覆盖组合成分，如 "-RET1,-RET5,-HIGH60_GAP,-LOG_AMT20"')
    ap.add_argument("--spread", action="store_true", help="额外输出多空分位价差（市场中性口径）")
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "alpha_composite.json"))
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
    nz = P.build_neutralizer(feats, masks["_tradable"]) if args.neutralize else None

    comps = COMPOSITE
    if args.components:
        comps = []
        for part in args.components.split(","):
            part = part.strip()
            if not part:
                continue
            sign = -1.0 if part.startswith("-") else 1.0
            comps.append((part.lstrip("+-"), sign))
    sigs = [(feats[name] * sign).astype(np.float32) for name, sign in comps
            if feats.get(name) is not None]
    combo = R.combine_signals(sigs)
    full = R.evaluate(combo, target, masks, slice(0, len(dates)), top_k=args.topk,
                      bench_daily=bench, hold=args.hold, neutralize_fn=(lambda s: P.neutralize_apply(s, nz)) if nz else None)
    print(f"面板 {len(codes)} 只 × {len(dates)} 日，等权池年化 "
          f"{(float(np.prod(1 + bench)) ** (R.TRADING_DAYS / len(bench)) - 1) * 100:+.1f}%（{time.time() - t0:.0f}s）")
    tag = "（已中性化）" if args.neutralize else ""
    print(f"\n全期组合{tag}：IC {full['ic']:+.4f} | IC_IR {full['ic_ir']:+.3f} | 年化 {full['ann'] * 100:+.1f}% | "
          f"超额 {full['ex_ann'] * 100:+.1f}% | 超额Sortino {full['ex_sortino']:+.2f} | "
          f"回撤 {full['maxdd'] * 100:.1f}% | 换手 {full['turnover']:.2f}")

    if args.spread:
        def _spread(fn, q=0.2):
            trad = masks["_tradable"] > 0.5
            can = masks["can_buy"] > 0
            d = []
            for t in range(target.shape[1]):
                m = trad[:, t] & can[:, t]
                if m.sum() < 50:
                    continue
                idx = np.where(m)[0]
                v = fn(t)[idx]
                y = target[idx, t]
                k = max(5, int(len(idx) * q))
                o = np.argsort(-v)
                d.append(y[o[:k]].mean() - y[o[-k:]].mean())
            arr = np.array(d)
            return arr.mean() * R.TRADING_DAYS, arr.mean() / (arr.std() + 1e-12) * np.sqrt(R.TRADING_DAYS)
        a, sh = _spread(lambda t: combo[:, t])
        print("\n多空分位价差（前20% - 后20%，市场中性）：年化 {:.1%} | 夏普 {:+.2f}".format(a, sh))

    folds = build_folds(dates, args.train_months, args.test_months, args.folds)
    print(f"\n10 折样本外（每折只评估测试窗口，train 仅用于展示基准）：")
    rows = []
    for fi, (lo, hi, te) in enumerate(folds, 1):
        bench_tr = np.concatenate([np.zeros(lo, dtype=np.float32), bench[lo:]])
        bench_oo = np.concatenate([np.zeros(hi, dtype=np.float32), bench[hi:]])
        nzf = (lambda s: P.neutralize_apply(s, nz)) if nz else None
        tr = R.evaluate(combo, target, masks, slice(lo, hi), top_k=args.topk,
                        bench_daily=bench_tr, hold=args.hold, neutralize_fn=nzf)
        oo = R.evaluate(combo, target, masks, slice(hi, te), top_k=args.topk,
                        bench_daily=bench_oo, hold=args.hold, neutralize_fn=nzf)
        rows.append({"fold": fi, "train": f"{dates[lo]}~{dates[hi - 1]}", "test": f"{dates[hi]}~{dates[te - 1]}",
                     "train_ex": round(tr["ex_ann"], 4), "oos_ex": round(oo["ex_ann"], 4),
                     "oos_sortino": round(oo["ex_sortino"], 3), "oos_ic": round(oo["ic"], 5),
                     "oos_dd": round(oo["maxdd"], 4), "oos_turnover": round(oo["turnover"], 3)})
        print(f"  折{fi:>2} {rows[-1]['test']} | 训练超额 {tr['ex_ann'] * 100:+6.1f}% | "
              f"样本外超额 {oo['ex_ann'] * 100:+6.1f}% | Sortino {oo['ex_sortino']:+.2f} | "
              f"IC {oo['ic']:+.4f} | 回撤 {oo['maxdd'] * 100:5.1f}%")
    ex = [r["oos_ex"] for r in rows]
    ic = [r["oos_ic"] for r in rows]
    print(f"\n汇总：样本外超额 均值 {np.mean(ex) * 100:+.1f}% / 中位 {np.median(ex) * 100:+.1f}%，"
          f"为正 {sum(1 for x in ex if x > 0)}/{len(ex)} 折 | 平均 IC {np.mean(ic):+.4f} | "
          f"平均 Sortino {np.mean([r['oos_sortino'] for r in rows]):+.2f}")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"codes": len(codes), "days": len(dates), "start": dates[0], "end": dates[-1],
                            "components": [f"{'+' if s > 0 else '-'}{n}" for n, s in comps],
                            "neutralized": bool(args.neutralize), "top_k": args.topk, "hold": args.hold,
                            "elapsed_sec": round(time.time() - t0, 1)},
                   "full": {k: round(float(v), 5) for k, v in full.items()},
                   "folds": rows}, f, ensure_ascii=False, indent=1)
    print(f"报告：{args.out}（用时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
