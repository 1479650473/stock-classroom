# -*- coding: utf-8 -*-
"""把 CLI 产出的 JSON 报告导入 alpha.db（便于前端直接看历史结果）。

用法：
    python -m backend.alpha.import_reports            # 导入 data/ 下的默认报告
说明：导入的记录会在 meta 里标记 imported_from / imported_at，与 API 跑出来的记录区分开。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

from ..api.paths import DATA_DIR
from . import store as S

FILES = [
    ("mine", "alpha_mine_result.json"),
    ("mine", "alpha_mine_hold5.json"),
    ("walkforward", "alpha_walkforward.json"),
]


def _mean(xs):
    return float(sum(xs) / len(xs)) if xs else None


def _median(xs):
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    return float(ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2)


def _num_map(d) -> Dict:
    if not isinstance(d, dict):
        return {}
    return {k: float(v) for k, v in d.items() if isinstance(v, (int, float))}


def import_mine(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    meta = dict(d.get("meta") or {})
    meta.update({"imported_from": os.path.basename(path), "search": meta.get("search", "GA(numpy)")})
    run_id = S.create_run("mine", {k: meta.get(k) for k in
                                   ("codes", "start", "end", "pop", "gens", "topk", "hold") if k in meta})
    rows: List[Dict] = d.get("top_formulas") or []
    for i, r in enumerate(rows, 1):
        S.add_formula(run_id, rank=i, tokens=r.get("tokens") or [], formula=r.get("formula") or "",
                      train=_num_map(r.get("train")), oos=_num_map(r.get("oos")), kept=1)
    S.finish_run(run_id, "done", meta=meta, summary={"combos": d.get("combos") or []},
                 history=d.get("best_history") or [])
    return run_id


def import_walkforward(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    meta = dict(d.get("meta") or {})
    meta.update({"imported_from": os.path.basename(path)})
    run_id = S.create_run("walkforward", {k: meta.get(k) for k in
                                          ("codes", "start", "end", "pop", "gens", "topk", "hold", "folds") if k in meta})
    folds = d.get("folds") or []
    for f in folds:
        S.add_formula(run_id, fold=int(f.get("fold") or 0), rank=1,
                      tokens=f.get("best_tokens") or [], formula=f.get("best_formula") or "",
                      train=_num_map(f.get("combo_train")), oos=_num_map(f.get("combo_oos")), kept=1)
    # 汇总自己算，统一用“分数”口径（0.09 = +9%）
    bs = [_num_map(f.get("best_oos")).get("ex_ann") for f in folds if f.get("best_oos")]
    cs = [_num_map(f.get("combo_oos")).get("ex_ann") for f in folds if f.get("combo_oos")]
    cso = [_num_map(f.get("combo_oos")).get("ex_sortino") for f in folds if f.get("combo_oos")]
    cic = [_num_map(f.get("combo_oos")).get("ic") for f in folds if f.get("combo_oos")]
    bs = [x for x in bs if x is not None]
    cs = [x for x in cs if x is not None]
    summary = {
        "n_folds": len(folds),
        "best_mean_ex_ann": _mean(bs), "best_median_ex_ann": _median(bs),
        "best_positive_folds": sum(1 for x in bs if x > 0),
        "combo_mean_ex_ann": _mean(cs), "combo_median_ex_ann": _median(cs),
        "combo_positive_folds": sum(1 for x in cs if x > 0),
        "combo_mean_ex_sortino": _mean([x for x in cso if x is not None]),
        "combo_mean_ic": _mean([x for x in cic if x is not None]),
        "folds": [{"fold": f.get("fold"), "train": f.get("train"), "test": f.get("test"),
                   "kept": f.get("kept")} for f in folds],
    }
    S.finish_run(run_id, "done", meta=meta, summary=summary, history=[])
    return run_id


def main() -> None:
    S.ensure_schema()
    for kind, name in FILES:
        path = os.path.join(str(DATA_DIR), name)
        if not os.path.exists(path):
            print(f"跳过（不存在）：{name}")
            continue
        rid = import_mine(path) if kind == "mine" else import_walkforward(path)
        print(f"已导入 {name} → alpha_run #{rid}（{kind}）")


if __name__ == "__main__":
    sys.exit(main())
