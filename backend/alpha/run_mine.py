# -*- coding: utf-8 -*-
"""因子挖掘 CLI —— 遗传搜索 A 股因子公式，样本外检验，出报告。

用法：
    python -m backend.alpha.run_mine --codes 300 --start 2022-01-01 --end 2024-12-31 \
        --pop 300 --gens 40 --topk 20 --out data/alpha_mine_result.json

流程：
  1) kline.db 取股票池（近端成交额 Top-N）+ 面板数据；
  2) 派生特征（截面标准化、因果）+ open-to-open 目标收益 + 涨跌停掩码；
  3) 8:2 切分，遗传搜索（**只在训练段打分**）；
  4) Top 公式做样本外（OOS）检验 + 相关性去重 + 多因子合成对照；
  5) 结果写 JSON，并打印可读报告。
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


def _evaluate_factory(feats: Dict[str, np.ndarray], target: np.ndarray, masks: Dict[str, np.ndarray],
                      sl: slice, top_k: int, bench: np.ndarray, hold: int,
                      cache: Dict[Tuple[str, ...], Tuple[float, dict]]):
    """返回评估函数。cache 必须 train/oos 分开传（否则样本外会命中训练的缓存）。"""

    def fn(tokens: List[str]) -> Tuple[float, dict]:
        key = tuple(tokens)
        if key in cache:
            return cache[key]
        sig = interpret(tokens, feats)
        if sig is None:
            res = (-3.0, {"invalid": 1.0})
        else:
            m = R.evaluate(sig, target, masks, sl, top_k=top_k, bench_daily=bench, hold=hold)
            res = (float(m.get("fitness", -3.0)), m)
        cache[key] = res
        return res
    return fn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300, help="股票池大小（按成交额取 Top）")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--pop", type=int, default=300)
    ap.add_argument("--gens", type=int, default=40)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--topk", type=int, default=20, help="组合每日持仓只数")
    ap.add_argument("--hold", type=int, default=1, help="持有天数（>1 用重叠建仓，显著降换手）")
    ap.add_argument("--train-ratio", type=float, default=0.8)
    ap.add_argument("--top", type=int, default=10, help="报告前 N 条公式")
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "alpha_mine_result.json"))
    args = ap.parse_args()

    t0 = time.time()
    codes = P.pick_universe(limit=args.codes, as_of=args.start)
    print(f"[1/5] 股票池 {len(codes)} 只（按 {args.start} 之前的成交额排序，避免选择偏误），"
          f"加载面板 {args.start} ~ {args.end} …", flush=True)
    pan = P.load_panel(codes, args.start, args.end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    print(f"      面板 {len(codes)} 只 × {len(dates)} 个交易日 "
          f"({dates[0]} ~ {dates[-1]}) {time.time() - t0:.0f}s", flush=True)

    print("[2/5] 构造特征 / 目标 / 掩码 …", flush=True)
    feats = P.build_features(fields)
    target = P.build_target(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats["_TRADABLE"]
    bench = R.bench_series(target, masks)          # 等权股票池基准
    feature_names = tuple(n for n in P.FEATURE_NAMES)
    split = P.split_index(dates, args.train_ratio)
    b_ann = float(np.prod(1 + bench[:split]) ** (R.TRADING_DAYS / max(1, split)) - 1)
    b_oos = float(np.prod(1 + bench[split:]) ** (R.TRADING_DAYS / max(1, len(dates) - split)) - 1)
    print(f"      训练段 {dates[0]}~{dates[split - 1]}（{split} 日）| "
          f"样本外 {dates[split]}~{dates[-1]}（{len(dates) - split} 日）", flush=True)
    print(f"      基准（等权池）年化：训练 {b_ann * 100:+.1f}% | 样本外 {b_oos * 100:+.1f}%", flush=True)

    train_cache: Dict[Tuple[str, ...], Tuple[float, dict]] = {}
    oos_cache: Dict[Tuple[str, ...], Tuple[float, dict]] = {}
    train_fn = _evaluate_factory(feats, target, masks, slice(0, split), args.topk, bench, args.hold, train_cache)
    oos_fn = _evaluate_factory(feats, target, masks, slice(split, len(dates)), args.topk, bench, args.hold, oos_cache)

    print(f"[3/5] 遗传搜索：种群 {args.pop} × {args.gens} 代（训练段打分）…", flush=True)
    ga = GASearch(features=feature_names, evaluate_fn=train_fn,
                  population=args.pop, generations=args.gens, max_nodes=args.max_nodes)
    result = ga.run()
    top_cands: List[Candidate] = result.best[: max(args.top * 4, 40)]
    print(f"      完成：{result.n_eval} 次公式求值，用时 {time.time() - t0:.0f}s", flush=True)

    print("[4/5] Top 公式样本外检验 + 相关性去重 …", flush=True)
    sig_of: Dict[Tuple[str, ...], np.ndarray] = {}

    def sig(tokens: List[str]) -> np.ndarray:
        key = tuple(tokens)
        if key not in sig_of:
            s = interpret(tokens, feats)
            sig_of[key] = s if s is not None else np.zeros_like(target)
        return sig_of[key]

    def corr_fn(a: List[str], b: List[str]) -> float:
        return abs(R.signal_correlation(sig(a), sig(b)))

    rows = []
    for c in top_cands:
        m = c.metrics if c.metrics else {}
        oos = oos_fn(c.tokens)[1]
        rows.append({"tokens": c.tokens, "formula": decode(c.tokens),
                     "train": {k: round(float(v), 4) for k, v in m.items() if isinstance(v, (int, float))},
                     "oos": {k: round(float(v), 4) for k, v in oos.items() if isinstance(v, (int, float))}})
    rows.sort(key=lambda r: -(r["train"].get("fitness", -9)))
    kept = dedupe([Candidate(r["tokens"], r["train"].get("fitness", -9), r["train"]) for r in rows],
                  corr_fn, top=args.top, max_corr=0.85)
    kept_keys = {tuple(c.tokens) for c in kept}
    kept_rows = [r for r in rows if tuple(r["tokens"]) in kept_keys]

    combo_rows = []
    if kept_rows:
        for k in (3, 5):
            use = kept_rows[:k]
            if not use:
                continue
            combo = R.combine_signals([sig(r["tokens"]) for r in use])
            tr = R.evaluate(combo, target, masks, slice(0, split), top_k=args.topk, bench_daily=bench, hold=args.hold)
            oo = R.evaluate(combo, target, masks, slice(split, len(dates)), top_k=args.topk, bench_daily=bench, hold=args.hold)
            combo_rows.append({"k": k, "formulas": [r["formula"] for r in use],
                               "train": {kk: round(float(v), 4) for kk, v in tr.items()},
                               "oos": {kk: round(float(v), 4) for kk, v in oo.items()}})

    print("[5/5] 写报告 …", flush=True)
    out = {"meta": {"codes": len(codes), "days": len(dates), "start": dates[0], "end": dates[-1],
                    "split_date": dates[split], "top_k": args.topk, "hold": args.hold,
                    "population": args.pop,
                    "generations": args.gens, "max_nodes": args.max_nodes,
                    "evaluations": result.n_eval, "elapsed_sec": round(time.time() - t0, 1),
                    "bench_ann_train": round(b_ann, 4), "bench_ann_oos": round(b_oos, 4),
                    "universe_as_of": args.start,
                    "search": "GA(numpy)",
                    "fitness": "IC_IR + 0.35*clip(Sortino_excess) - void penalty"},
           "top_formulas": kept_rows, "combos": combo_rows,
           "best_history": [round(float(x), 4) for x in result.history]}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    def line(tag: str, m: Dict[str, float]) -> str:
        return (f"{tag} IC {m.get('ic', 0):+.4f} | IC_IR {m.get('ic_ir', 0):+.3f} | "
                f"年化 {m.get('ann', 0) * 100:+7.1f}% | 超额年化 {m.get('ex_ann', 0) * 100:+7.1f}% | "
                f"夏普 {m.get('sharpe', 0):5.2f} | 超额Sortino {m.get('ex_sortino', 0):5.2f} | "
                f"回撤 {m.get('maxdd', 0) * 100:5.1f}% | "
                f"换手 {m.get('turnover', 0):.2f} | 胜率 {m.get('win_rate', 0) * 100:.1f}%")

    print("\n" + "=" * 100)
    print(f"因子挖掘结果（{len(codes)} 只 × {len(dates)} 日，Top{args.topk} 组合，成本单边 5bp）")
    print(f"基准等权池年化：训练 {b_ann * 100:+.1f}% | 样本外 {b_oos * 100:+.1f}%")
    print("=" * 100)
    for i, r in enumerate(kept_rows, 1):
        print(f"\n#{i}  {r['formula']}")
        print("   训练 " + line("", r["train"]))
        print("   样本外 " + line("", r["oos"]))
    for c in combo_rows:
        print(f"\n多因子合成（Top{c['k']} 等权 rank 合成）")
        print("   训练 " + line("", c["train"]))
        print("   样本外 " + line("", c["oos"]))
    print(f"\n报告已写入 {args.out}（总用时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
