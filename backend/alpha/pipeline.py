# -*- coding: utf-8 -*-
"""因子挖掘主流程（CLI 与 API 共用）+ 结果落库。

`mine(params)`：遗传搜索 → 样本外检验 → 相关性去重 → 多因子合成 → 写 alpha.db
`walk_forward(params)`：滚动窗口验证 → 写 alpha.db
两者都支持 `progress(dict)` 回调，用于 jobman SSE 推送进度。
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from . import panel as P
from . import reward as R
from . import store as S
from .dsl import decode, interpret
from .search import Candidate, GASearch, dedupe

DEFAULTS = {
    "codes": 300, "start": "2021-07-01", "end": "2025-12-31",
    "pop": 120, "gens": 18, "max_nodes": 12, "topk": 20, "hold": 5,
    "top": 8, "train_ratio": 0.8,
}


def _emit(progress: Optional[Callable], msg: str, pct: int = 0, **extra) -> None:
    if not progress:
        return
    try:
        progress({"msg": msg, "pct": pct, **extra})
    except Exception:
        pass


def _load(params: Dict) -> Tuple[List[str], List[str], Dict, np.ndarray, Dict, np.ndarray]:
    codes = P.pick_universe(limit=int(params["codes"]), as_of=str(params["start"]))
    pan = P.load_panel(codes, str(params["start"]), str(params["end"]))
    fields = pan["fields"]
    dates = pan["dates"]
    feats = P.build_features(fields)
    target = P.build_target(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats["_TRADABLE"]
    bench = R.bench_series(target, masks)
    return codes, dates, fields, target, masks, bench


def _eval_factory(feats, target, masks, sl, top_k, hold, bench,
                  cache: Dict[Tuple[str, ...], Tuple[float, dict]]):
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


def mine(params: Optional[Dict] = None, progress: Optional[Callable] = None) -> Dict:
    p = dict(DEFAULTS)
    p.update(params or {})
    t0 = time.time()
    run_id = S.create_run("mine", p)
    try:
        _emit(progress, f"选池 {p['codes']} 只 + 加载面板 {p['start']}~{p['end']} …", 5)
        codes, dates, _fields, target, masks, bench = _load(p)
        feats = P.build_features(_fields)
        split = P.split_index(dates, float(p["train_ratio"]))
        b_ann = float(np.prod(1 + bench[:split]) ** (R.TRADING_DAYS / max(1, split)) - 1)
        b_oos = float(np.prod(1 + bench[split:]) ** (R.TRADING_DAYS / max(1, len(dates) - split)) - 1)
        _emit(progress, f"面板 {len(codes)} × {len(dates)} 日；训练/样本外切分 {dates[split]}；"
                        f"基准年化 {b_ann * 100:+.1f}% / {b_oos * 100:+.1f}%", 20,
              universe=len(codes), days=len(dates), split_date=dates[split])

        train_cache: Dict[Tuple[str, ...], Tuple[float, dict]] = {}
        oos_cache: Dict[Tuple[str, ...], Tuple[float, dict]] = {}
        train_fn = _eval_factory(feats, target, masks, slice(0, split), int(p["topk"]),
                                 int(p["hold"]), bench, train_cache)
        oos_fn = _eval_factory(feats, target, masks, slice(split, len(dates)), int(p["topk"]),
                               int(p["hold"]), bench, oos_cache)

        ga = GASearch(features=tuple(P.FEATURE_NAMES), evaluate_fn=train_fn,
                      population=int(p["pop"]), generations=int(p["gens"]),
                      max_nodes=int(p["max_nodes"]), verbose=False)
        gen = {"n": 0}

        def on_gen(best):
            gen["n"] += 1
            _emit(progress, f"第 {gen['n']}/{p['gens']} 代 · 最优 fitness {best.score:.3f} · "
                            f"超额年化 {best.metrics.get('ex_ann', 0) * 100:+.1f}% · {decode(best.tokens)}",
                  20 + int(60 * gen["n"] / max(1, int(p["gens"]))),
                  best_formula=decode(best.tokens), best_score=round(float(best.score), 4))

        ga.on_generation = on_gen
        res = ga.run()

        _emit(progress, "样本外检验 + 相关性去重 + 多因子合成 …", 88)
        sig_of: Dict[Tuple[str, ...], np.ndarray] = {}

        def sig(tokens: List[str]) -> np.ndarray:
            key = tuple(tokens)
            if key not in sig_of:
                s = interpret(tokens, feats)
                sig_of[key] = s if s is not None else np.zeros_like(target)
            return sig_of[key]

        rows = []
        for c in res.best[: max(int(p["top"]) * 4, 40)]:
            m = c.metrics or {}
            oos = oos_fn(c.tokens)[1]
            rows.append({"tokens": c.tokens, "formula": decode(c.tokens),
                         "train": {k: round(float(v), 4) for k, v in m.items() if isinstance(v, (int, float))},
                         "oos": {k: round(float(v), 4) for k, v in oos.items() if isinstance(v, (int, float))}})
        rows.sort(key=lambda r: -r["train"].get("fitness", -9))
        kept = dedupe([Candidate(r["tokens"], r["train"].get("fitness", -9), r["train"]) for r in rows],
                      lambda a, b: abs(R.signal_correlation(sig(a), sig(b))),
                      top=int(p["top"]), max_corr=0.85)
        kept_keys = {tuple(c.tokens) for c in kept}
        kept_rows = [r for r in rows if tuple(r["tokens"]) in kept_keys]

        combos = []
        for k in (3, 5):
            use = kept_rows[:k]
            if len(use) < k:
                continue
            combo = R.combine_signals([sig(r["tokens"]) for r in use])
            tr = R.evaluate(combo, target, masks, slice(0, split), top_k=int(p["topk"]),
                            bench_daily=bench, hold=int(p["hold"]))
            oo = R.evaluate(combo, target, masks, slice(split, len(dates)), top_k=int(p["topk"]),
                            bench_daily=bench, hold=int(p["hold"]))
            combos.append({"k": k, "formulas": [r["formula"] for r in use],
                           "train": {kk: round(float(v), 4) for kk, v in tr.items()},
                           "oos": {kk: round(float(v), 4) for kk, v in oo.items()}})

        meta = {"codes": len(codes), "days": len(dates), "start": dates[0], "end": dates[-1],
                "split_date": dates[split], "top_k": int(p["topk"]), "hold": int(p["hold"]),
                "population": int(p["pop"]), "generations": int(p["gens"]),
                "max_nodes": int(p["max_nodes"]), "evaluations": res.n_eval,
                "elapsed_sec": round(time.time() - t0, 1),
                "bench_ann_train": round(b_ann, 4), "bench_ann_oos": round(b_oos, 4),
                "universe_as_of": str(p["start"]), "search": "GA(numpy)",
                "fitness": "2*IC_IR + 0.2*clip(Sortino_excess) - void penalty"}
        S.finish_run(run_id, "done", meta=meta,
                     summary={"combos": combos,
                              "best_oos_ex_ann": kept_rows[0]["oos"].get("ex_ann") if kept_rows else None},
                     history=[round(float(x), 4) for x in res.history])
        for i, r in enumerate(kept_rows, 1):
            S.add_formula(run_id, rank=i, tokens=r["tokens"], formula=r["formula"],
                          train=r["train"], oos=r["oos"], kept=1)
        for r in rows:
            if tuple(r["tokens"]) not in kept_keys:
                S.add_formula(run_id, rank=0, tokens=r["tokens"], formula=r["formula"],
                              train=r["train"], oos=r["oos"], kept=0)
        _emit(progress, f"完成：{res.n_eval} 次求值，用时 {time.time() - t0:.0f}s", 100,
              run_id=run_id, best_formula=kept_rows[0]["formula"] if kept_rows else "")
        return {"run_id": run_id, "meta": meta, "top_formulas": kept_rows, "combos": combos,
                "best_history": [round(float(x), 4) for x in res.history]}
    except Exception as e:
        S.finish_run(run_id, "error", error=str(e)[:400])
        _emit(progress, f"失败：{e}", 100)
        raise


def walk_forward(params: Optional[Dict] = None, progress: Optional[Callable] = None) -> Dict:
    """滚动窗口验证（训练窗口独立搜索 → 紧接的测试窗口评估）。"""
    from .walk_forward import build_folds

    p = dict(DEFAULTS)
    p.update({"train_months": 24, "test_months": 6, "folds": 5, "combo": 5})
    p.update(params or {})
    t0 = time.time()
    run_id = S.create_run("walkforward", p)
    try:
        _emit(progress, "加载面板 …", 5)
        codes, dates, _f, target, masks, bench = _load(p)
        feats = P.build_features(_f)
        folds = build_folds(dates, int(p["train_months"]), int(p["test_months"]), int(p["folds"]))
        _emit(progress, f"面板 {len(codes)} × {len(dates)} 日；折数 {len(folds)}", 12, folds=len(folds))
        rows = []
        for fi, (lo, hi, te) in enumerate(folds, 1):
            _emit(progress, f"折 {fi}/{len(folds)}：训练 {dates[lo]}~{dates[hi - 1]}，"
                            f"测试 {dates[hi]}~{dates[te - 1]}", 12 + int(75 * (fi - 1) / max(1, len(folds))))
            bench_tr = np.concatenate([np.zeros(lo, dtype=np.float32), bench[lo:]])
            bench_oo = np.concatenate([np.zeros(hi, dtype=np.float32), bench[hi:]])
            cache_tr: Dict = {}
            cache_oo: Dict = {}
            tr_fn = _eval_factory(feats, target, masks, slice(lo, hi), int(p["topk"]),
                                  int(p["hold"]), bench_tr, cache_tr)
            oo_fn = _eval_factory(feats, target, masks, slice(hi, te), int(p["topk"]),
                                  int(p["hold"]), bench_oo, cache_oo)
            ga = GASearch(features=tuple(P.FEATURE_NAMES), evaluate_fn=tr_fn,
                          population=int(p["pop"]), generations=int(p["gens"]),
                          max_nodes=int(p["max_nodes"]), verbose=False)
            res = ga.run()
            cands = [c for c in res.best[: max(40, int(p["combo"]) * 8)] if c.score > -9]

            def sig_of(tokens, _feats=feats, _t=target):
                s = interpret(tokens, _feats)
                return s if s is not None else np.zeros_like(_t)

            kept = dedupe(cands, lambda a, b: abs(R.signal_correlation(sig_of(a), sig_of(b))),
                          top=int(p["combo"]), max_corr=0.85)
            row = {"fold": fi, "train": f"{dates[lo]}~{dates[hi - 1]}", "test": f"{dates[hi]}~{dates[te - 1]}",
                   "kept": [decode(c.tokens) for c in kept]}
            if cands:
                bm = tr_fn(cands[0].tokens)[1]
                bo = oo_fn(cands[0].tokens)[1]
                row["best_formula"] = decode(cands[0].tokens)
                row["best_train"] = {k: round(float(v), 4) for k, v in bm.items() if isinstance(v, (int, float))}
                row["best_oos"] = {k: round(float(v), 4) for k, v in bo.items() if isinstance(v, (int, float))}
            if kept:
                combo = R.combine_signals([sig_of(c.tokens) for c in kept])
                ct = R.evaluate(combo, target, masks, slice(lo, hi), top_k=int(p["topk"]),
                                bench_daily=bench_tr, hold=int(p["hold"]))
                co = R.evaluate(combo, target, masks, slice(hi, te), top_k=int(p["topk"]),
                                bench_daily=bench_oo, hold=int(p["hold"]))
                row["combo_train"] = {k: round(float(v), 4) for k, v in ct.items() if isinstance(v, (int, float))}
                row["combo_oos"] = {k: round(float(v), 4) for k, v in co.items() if isinstance(v, (int, float))}
                S.add_formula(run_id, fold=fi, rank=1, tokens=kept[0].tokens, formula=decode(kept[0].tokens),
                              train=row.get("combo_train", {}), oos=row.get("combo_oos", {}), kept=1)
            rows.append(row)
            _emit(progress, f"折 {fi} 完成：样本外超额 {row.get('combo_oos', {}).get('ex_ann', 0) * 100:+.1f}%"
                            f"（单公式 {row.get('best_oos', {}).get('ex_ann', 0) * 100:+.1f}%）",
                  12 + int(75 * fi / max(1, len(folds))))

        bs = [r["best_oos"]["ex_ann"] for r in rows if "best_oos" in r]
        cs = [r["combo_oos"]["ex_ann"] for r in rows if "combo_oos" in r]
        cso = [r["combo_oos"]["ex_sortino"] for r in rows if "combo_oos" in r]
        cic = [r["combo_oos"]["ic"] for r in rows if "combo_oos" in r]
        summary = {"n_folds": len(rows),
                   "best_mean_ex_ann": float(np.mean(bs)) if bs else None,
                   "best_median_ex_ann": float(np.median(bs)) if bs else None,
                   "best_positive_folds": int(sum(1 for x in bs if x > 0)),
                   "combo_mean_ex_ann": float(np.mean(cs)) if cs else None,
                   "combo_median_ex_ann": float(np.median(cs)) if cs else None,
                   "combo_positive_folds": int(sum(1 for x in cs if x > 0)),
                   "combo_mean_ex_sortino": float(np.mean(cso)) if cso else None,
                   "combo_mean_ic": float(np.mean(cic)) if cic else None}
        meta = {"codes": len(codes), "days": len(dates), "start": dates[0], "end": dates[-1],
                "train_months": int(p["train_months"]), "test_months": int(p["test_months"]),
                "folds": len(rows), "hold": int(p["hold"]), "top_k": int(p["topk"]),
                "population": int(p["pop"]), "generations": int(p["gens"]),
                "combo_top": int(p["combo"]), "elapsed_sec": round(time.time() - t0, 1),
                "search": "GA(numpy)"}
        S.finish_run(run_id, "done", meta=meta, summary=summary, history=[])
        _emit(progress, "滚动验证完成", 100, run_id=run_id)
        return {"run_id": run_id, "meta": meta, "summary": summary, "folds": rows}
    except Exception as e:
        S.finish_run(run_id, "error", error=str(e)[:400])
        _emit(progress, f"失败：{e}", 100)
        raise
