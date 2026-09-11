# -*- coding: utf-8 -*-
"""滚动窗口验证（walk-forward）—— 判断挖出来的因子是不是真的跨期稳定。

做法：把时间轴切成若干「训练窗口 → 紧接的测试窗口」（默认 train 24 个月 / test 6 个月，
逐 6 个月向前滚）。每一折**独立重新搜索**（不看测试段），然后在测试段评估：
  - 单公式：该折训练段 fitness 最高的那条；
  - 组合：该折训练段 Top-5 去重后的等权 rank 合成（更接近实际用法）。
汇总输出：各折样本外超额年化 / 超额 Sortino / IC / 换手，以及"为正的折数"。

注意：hold（持有天数）是结构性选择（重叠建仓把换手成本从 13%/年降到 2%/年），
在所有折里固定不变，不参与逐折挑选，避免"用测试段选参数"。
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
from .dsl import decode, interpret
from .search import Candidate, GASearch, dedupe


def month_add(ym: str, months: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    m2 = m - 1 + months
    return f"{y + m2 // 12:04d}-{m2 % 12 + 1:02d}"


def _c(ym: str) -> str:
    """'YYYY-MM' → 'YYYYMM'（面板里的日期是 YYYYMMDD，避免字符串比较按位错位）。"""
    return ym.replace("-", "")


def build_folds(dates: List[str], train_months: int = 24, test_months: int = 6,
                folds: int = 5) -> List[Tuple[int, int, int]]:
    """返回 [(train_lo, train_hi, test_hi)]：训练 [lo, hi)，测试 [hi, test_hi)。"""
    out: List[Tuple[int, int, int]] = []
    last_ym = f"{dates[-1][:4]}-{dates[-1][4:6]}"
    for k in range(folds):
        test_start_ym = month_add(last_ym, -test_months * (k + 1))
        train_start_ym = month_add(test_start_ym, -train_months)
        test_end_ym = month_add(test_start_ym, test_months)
        tr_lo = next((i for i, d in enumerate(dates) if d[:6] >= _c(train_start_ym)), None)
        tr_hi = next((i for i, d in enumerate(dates) if d[:6] >= _c(test_start_ym)), None)
        te_hi = next((i for i, d in enumerate(dates) if d[:6] >= _c(test_end_ym)), None)
        if tr_lo is None or tr_hi is None or te_hi is None:
            continue
        if tr_hi - tr_lo < 200 or te_hi - tr_hi < 40:
            continue
        out.append((tr_lo, tr_hi, te_hi))
    return list(reversed(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2021-07-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--pop", type=int, default=120)
    ap.add_argument("--gens", type=int, default=18)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--combo", type=int, default=5, help="合成用 Top-N 公式")
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "alpha_walkforward.json"))
    args = ap.parse_args()

    t0 = time.time()
    codes = P.pick_universe(limit=args.codes, as_of=args.start)
    pan = P.load_panel(codes, args.start, args.end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats_all = P.build_features(fields)
    target = P.build_target(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats_all["_TRADABLE"]
    bench = R.bench_series(target, masks)
    feats = {k: v for k, v in feats_all.items()}
    print(f"[1/3] 面板 {len(codes)} 只 × {len(dates)} 日（{dates[0]}~{dates[-1]}）"
          f" {time.time() - t0:.0f}s", flush=True)

    folds = build_folds(dates, args.train_months, args.test_months, args.folds)
    print(f"[2/3] 折数 {len(folds)}（train {args.train_months} 月 → test {args.test_months} 月，hold={args.hold}）",
          flush=True)

    rows = []
    for fi, (tr_lo, tr_hi, te_hi) in enumerate(folds, 1):
        d_tr = f"{dates[tr_lo]}~{dates[tr_hi - 1]}"
        d_te = f"{dates[tr_hi]}~{dates[te_hi - 1]}"
        cache: Dict[Tuple[str, ...], Tuple[float, dict]] = {}
        bench_train = np.concatenate([np.zeros(tr_lo, dtype=np.float32), bench[tr_lo:]])
        bench_oos = np.concatenate([np.zeros(tr_hi, dtype=np.float32), bench[tr_hi:]])
        cache_oos: Dict[Tuple[str, ...], Tuple[float, dict]] = {}

        def train_fn(tokens: List[str], _cache=cache, _sl=slice(tr_lo, tr_hi), _b=bench_train):
            key = tuple(tokens)
            if key in _cache:
                return _cache[key]
            sig = interpret(tokens, feats)
            if sig is None:
                res = (-3.0, {"invalid": 1.0})
            else:
                m = R.evaluate(sig, target, masks, _sl, top_k=args.topk, bench_daily=_b, hold=args.hold)
                res = (float(m.get("fitness", -3.0)), m)
            _cache[key] = res
            return res

        def oos_fn(tokens: List[str], _cache=cache_oos, _sl=slice(tr_hi, te_hi), _b=bench_oos):
            key = tuple(tokens)
            if key in _cache:
                return _cache[key]
            sig = interpret(tokens, feats)
            if sig is None:
                res = (-3.0, {"invalid": 1.0})
            else:
                m = R.evaluate(sig, target, masks, _sl, top_k=args.topk, bench_daily=_b, hold=args.hold)
                res = (float(m.get("fitness", -3.0)), m)
            _cache[key] = res
            return res

        ga = GASearch(features=tuple(P.FEATURE_NAMES), evaluate_fn=train_fn,
                      population=args.pop, generations=args.gens, max_nodes=args.max_nodes,
                      verbose=False)
        res = ga.run()
        cands: List[Candidate] = [c for c in res.best[: max(40, args.combo * 8)] if c.score > -9]

        def sig_of(tokens: List[str]) -> np.ndarray:
            s = interpret(tokens, feats)
            return s if s is not None else np.zeros_like(target)

        kept = dedupe(cands, lambda a, b: abs(R.signal_correlation(sig_of(a), sig_of(b))),
                      top=args.combo, max_corr=0.85)
        best = cands[0] if cands else None
        combo_sig = R.combine_signals([sig_of(c.tokens) for c in kept]) if kept else None

        row = {"fold": fi, "train": d_tr, "test": d_te, "n_eval": res.n_eval,
               "best_formula": decode(best.tokens) if best else "",
               "best_tokens": best.tokens if best else [],
               "kept": [decode(c.tokens) for c in kept]}
        if best:
            tr_m = train_fn(best.tokens)[1]
            oo_m = oos_fn(best.tokens)[1]
            row["best_train"] = {k: round(float(v), 4) for k, v in tr_m.items() if isinstance(v, (int, float))}
            row["best_oos"] = {k: round(float(v), 4) for k, v in oo_m.items() if isinstance(v, (int, float))}
        if combo_sig is not None:
            tr_c = R.evaluate(combo_sig, target, masks, slice(tr_lo, tr_hi), top_k=args.topk,
                              bench_daily=bench_train, hold=args.hold)
            oo_c = R.evaluate(combo_sig, target, masks, slice(tr_hi, te_hi), top_k=args.topk,
                              bench_daily=bench_oos, hold=args.hold)
            row["combo_train"] = {k: round(float(v), 4) for k, v in tr_c.items() if isinstance(v, (int, float))}
            row["combo_oos"] = {k: round(float(v), 4) for k, v in oo_c.items() if isinstance(v, (int, float))}
        rows.append(row)
        b_oos = row.get("best_oos", {}).get("ex_ann", 0) * 100
        c_oos = row.get("combo_oos", {}).get("ex_ann", 0) * 100
        print(f"  折{fi} {d_tr} → {d_te} | 单公式样本外超额 {b_oos:+6.1f}% | "
              f"Top{args.combo}合成 {c_oos:+6.1f}%（Sortino {row.get('combo_oos', {}).get('ex_sortino', 0):+.2f}，"
              f"IC {row.get('combo_oos', {}).get('ic', 0):+.4f}，换手 {row.get('combo_oos', {}).get('turnover', 0):.2f}）"
              f" {time.time() - t0:.0f}s", flush=True)

    bs = [r["best_oos"]["ex_ann"] for r in rows if "best_oos" in r]
    cs = [r["combo_oos"]["ex_ann"] for r in rows if "combo_oos" in r]
    cso = [r["combo_oos"]["ex_sortino"] for r in rows if "combo_oos" in r]
    cic = [r["combo_oos"]["ic"] for r in rows if "combo_oos" in r]
    summary = {
        "best_mean_ex_ann": float(np.mean(bs)) if bs else None,
        "best_median_ex_ann": float(np.median(bs)) if bs else None,
        "best_positive_folds": int(sum(1 for x in bs if x > 0)), "n_folds": len(bs),
        "combo_mean_ex_ann": float(np.mean(cs)) if cs else None,
        "combo_median_ex_ann": float(np.median(cs)) if cs else None,
        "combo_positive_folds": int(sum(1 for x in cs if x > 0)),
        "combo_mean_ex_sortino": float(np.mean(cso)) if cso else None,
        "combo_mean_ic": float(np.mean(cic)) if cic else None,
    }
    out = {"meta": {"codes": len(codes), "days": len(dates), "start": dates[0], "end": dates[-1],
                    "train_months": args.train_months, "test_months": args.test_months,
                    "folds": len(rows), "hold": args.hold, "top_k": args.topk,
                    "population": args.pop, "generations": args.gens, "combo_top": args.combo,
                    "elapsed_sec": round(time.time() - t0, 1), "search": "GA(numpy)"},
           "summary": summary, "folds": rows}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("\n" + "=" * 92)
    print(f"滚动窗口汇总（{len(rows)} 折，hold={args.hold}，Top{args.topk} 组合，与等权池比）")
    print("=" * 92)
    if cs:
        print(f"单公式样本外超额：均值 {summary['best_mean_ex_ann'] * 100:+.1f}% / 中位 "
              f"{summary['best_median_ex_ann'] * 100:+.1f}%，为正 {summary['best_positive_folds']}/{summary['n_folds']} 折")
        print(f"Top{args.combo}合成样本外超额：均值 {summary['combo_mean_ex_ann'] * 100:+.1f}% / 中位 "
              f"{summary['combo_median_ex_ann'] * 100:+.1f}%，为正 {summary['combo_positive_folds']}/{summary['n_folds']} 折"
              f" · 平均超额 Sortino {summary['combo_mean_ex_sortino']:+.2f} · 平均 IC {summary['combo_mean_ic']:+.4f}")
    print(f"报告：{args.out}（用时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
