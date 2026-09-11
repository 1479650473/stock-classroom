# -*- coding: utf-8 -*-
"""因子挖掘 CLI —— 遗传搜索 A 股因子公式，样本外检验，出报告。

用法：
    python -m backend.alpha.run_mine --codes 300 --start 2022-01-01 --end 2025-12-31 \
        --pop 150 --gens 25 --topk 20 --hold 5 --out data/alpha_mine_result.json

    滚动窗口验证（判断是否跨期稳定）：
    python -m backend.alpha.walk_forward --codes 300 --hold 5

实现在 pipeline.mine / pipeline.walk_forward（API 与 CLI 共用同一套逻辑），
结果同时写入 data/alpha.db 供前端展示。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from ..api.paths import DATA_DIR
from . import pipeline as PL


def _print_report(rep: dict, hold: int, topk: int) -> None:
    meta = rep.get("meta") or {}

    def line(m: dict) -> str:
        return (f"IC {m.get('ic', 0):+.4f} | IC_IR {m.get('ic_ir', 0):+.3f} | "
                f"年化 {m.get('ann', 0) * 100:+7.1f}% | 超额年化 {m.get('ex_ann', 0) * 100:+7.1f}% | "
                f"夏普 {m.get('sharpe', 0):5.2f} | 超额Sortino {m.get('ex_sortino', 0):5.2f} | "
                f"回撤 {m.get('maxdd', 0) * 100:5.1f}% | 换手 {m.get('turnover', 0):.2f} | "
                f"胜率 {m.get('win_rate', 0) * 100:.1f}%")

    print("\n" + "=" * 100)
    print(f"因子挖掘结果（{meta.get('codes')} 只 × {meta.get('days')} 日，Top{topk} 组合，"
          f"持有 {hold} 天，成本单边 5bp，{meta.get('evaluations')} 次求值）")
    print(f"基准等权池年化：训练 {meta.get('bench_ann_train', 0) * 100:+.1f}% | "
          f"样本外 {meta.get('bench_ann_oos', 0) * 100:+.1f}%")
    print("=" * 100)
    for i, r in enumerate(rep.get("top_formulas") or [], 1):
        print(f"\n#{i}  {r['formula']}")
        print("   训练   " + line(r["train"]))
        print("   样本外 " + line(r["oos"]))
    for c in rep.get("combos") or []:
        print(f"\n多因子合成（Top{c['k']} 等权 rank 合成）")
        print("   训练   " + line(c["train"]))
        print("   样本外 " + line(c["oos"]))
    print(f"\n运行 #{rep.get('run_id')} 已写入 data/alpha.db")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2021-07-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--pop", type=int, default=120)
    ap.add_argument("--gens", type=int, default=18)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--train-ratio", type=float, default=0.8)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    params = {"codes": args.codes, "start": args.start, "end": args.end, "pop": args.pop,
              "gens": args.gens, "max_nodes": args.max_nodes, "topk": args.topk,
              "hold": args.hold, "top": args.top, "train_ratio": args.train_ratio}

    def progress(ev: dict) -> None:
        print("   " + str(ev.get("msg") or ev), flush=True)

    rep = PL.mine(params, progress=progress)
    _print_report(rep, args.hold, args.topk)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        print(f"报告：{args.out}")


if __name__ == "__main__":
    main()
