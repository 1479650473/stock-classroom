# -*- coding: utf-8 -*-
"""单因子分析（Alphalens 风格）—— 分层回测 / 多空净值 / IC 衰减 / 成本敏感性。

对任意因子（面板特征名，可选反向）给出：
  1) **分位数组合**：按因子值分 10 组，各组等权日收益（可含成本）→ 年化/夏普/回撤；
  2) **多空价差**：Q10 − Q1 的净值与统计；
  3) **单调性**：各组年化收益与组序的秩相关（越接近 ±1 越单调）；
  4) **IC 衰减**：因子对未来 1/2/3/5/10/20 日收益的 Rank IC；
  5) **成本敏感性**：不同持有期（1/5/10/20 天重叠建仓）下的净收益与换手。

用法：
  python -m backend.alpha.factor_analysis --factor RET20 --sign -1
  python -m backend.alpha.factor_analysis --factor LOG_AMT20 --sign -1 --quantiles 10
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..api.paths import DATA_DIR
from . import panel as P
from . import reward as R

HORIZONS = (1, 2, 3, 5, 10, 20)


def _fwd_returns(open_: np.ndarray, h: int) -> np.ndarray:
    out = np.zeros_like(open_)
    if open_.shape[1] > h + 1:
        o1, o2 = open_[:, 1:-h], open_[:, h + 1:]
        ok = (o1 > 0) & (o2 > 0)
        tmp = np.zeros_like(o1)
        tmp[ok] = o2[ok] / o1[ok] - 1.0
        out[:, :-h - 1] = tmp
    return out


def quantile_returns(sig: np.ndarray, target: np.ndarray, mask: np.ndarray,
                     q: int = 10, cost_one_way: float = 5e-4,
                     hold: int = 1) -> Dict[str, List[float]]:
    """分层组合：返回每组（含多空）的净值曲线（成本按持仓变动计）。"""
    N, T = sig.shape
    daily = np.zeros((q + 1, T), dtype=np.float64)      # 末行=多空
    prev = np.zeros((q + 1, N), dtype=np.float32)       # 每组的持仓权重（hold>1 时用滚动平均）
    tg = np.nan_to_num(target)
    for t in range(T):
        m = mask[:, t]
        if m.sum() < max(30, q * 5):
            continue
        idx = np.where(m)[0]
        v = sig[idx, t]
        order = np.argsort(-v)
        groups = np.array_split(order, q)
        for gi, g in enumerate(groups):
            sel = idx[g]
            w = np.zeros(N, dtype=np.float32)
            w[sel] = 1.0 / max(1, len(sel))
            prev[gi] = w if prev[gi].sum() == 0 else (prev[gi] * (hold - 1) + w) / hold
            turn = float(np.abs(prev[gi] - w).sum()) if t else 1.0
            daily[gi, t] = float((prev[gi] * tg[:, t]).sum()) - cost_one_way * turn
        # 多空 = Q1（因子值最高）− Qq
        daily[q, t] = daily[0, t] - daily[q - 1, t]
    return {"daily": daily}


def _stats(daily: np.ndarray) -> Dict[str, float]:
    d = daily[daily != 0]
    if d.size < 30:
        return {"ann": 0.0, "sharpe": 0.0, "maxdd": 0.0, "win": 0.0}
    eq = np.cumprod(1 + daily)
    ann = float(eq[-1] ** (R.TRADING_DAYS / max(1, daily.size)) - 1)
    sr = float(d.mean() / (d.std() + 1e-12) * np.sqrt(R.TRADING_DAYS))
    peak = np.maximum.accumulate(eq)
    dd = float(np.max(1 - eq / (peak + 1e-12)))
    return {"ann": ann, "sharpe": sr, "maxdd": dd, "win": float((d > 0).mean())}


def analyze(factor: str, sign: float = 1.0, codes: int = 300, start: str = "2016-01-01",
            end: str = "2025-12-31", quantiles: int = 10) -> Dict:
    t0 = time.time()
    uni = P.pick_universe(limit=codes, as_of=start)
    pan = P.load_panel(uni, start, end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats = P.build_features(fields)
    base = feats.get(factor)
    if base is None:
        return {"error": f"未知因子：{factor}", "factors": list(P.FEATURE_NAMES)}
    sig = (base * float(sign)).astype(np.float32)
    target = P.build_target(fields)
    masks = P.trade_masks(fields)
    mask = (feats["_TRADABLE"] > 0.5) & (masks["can_buy"] > 0)

    # ① 分层 + ② 多空
    qr = quantile_returns(sig, target, mask, q=quantiles)
    daily = qr["daily"]
    groups = [{"group": i + 1, **_stats(daily[i])} for i in range(quantiles)]
    ls = _stats(daily[quantiles])
    anns = np.array([g["ann"] for g in groups])
    from scipy.stats import spearmanr
    mono = float(spearmanr(np.arange(1, quantiles + 1), anns).statistic)

    # ③ IC 衰减
    ic_decay = {}
    for h in HORIZONS:
        tgt = _fwd_returns(fields["open"], h)
        ics = R._rank_ic(sig, tgt, mask)
        ic_decay[str(h)] = {"ic": float(np.mean(ics)),
                            "ic_ir": float(np.mean(ics) / (np.std(ics) + 1e-9))}

    # ④ 成本/持有期敏感性（Top-K 组合）
    cost_curve = []
    for h in (1, 5, 10, 20):
        bench = R.bench_series(target, masks)
        m = R.evaluate(sig, target, masks, slice(0, len(dates)), top_k=20,
                       bench_daily=bench, hold=h)
        cost_curve.append({"hold": h, "ann": float(m["ann"]), "ex_ann": float(m["ex_ann"]),
                           "turnover": float(m["turnover"]), "maxdd": float(m["maxdd"])})

    return {"factor": factor, "sign": float(sign), "quantiles": quantiles,
            "meta": {"codes": len(uni), "days": len(dates), "start": dates[0], "end": dates[-1],
                     "elapsed_sec": round(time.time() - t0, 1)},
            "groups": groups, "long_short": ls, "monotonicity": mono,
            "ic_decay": ic_decay, "cost_curve": cost_curve,
            "equity": {"long_short": [round(float(x), 4) for x in np.cumprod(1 + daily[quantiles])[::5]],
                       "dates": dates[::5]}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", default="RET20")
    ap.add_argument("--sign", type=float, default=1.0, help="1 或 -1（反向）")
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--quantiles", type=int, default=10)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    res = analyze(args.factor, args.sign, args.codes, args.start, args.end, args.quantiles)
    if res.get("error"):
        print(res["error"])
        return
    print(f"因子 {res['sign']:+g}{res['factor']}｜{res['meta']['codes']} 只 × {res['meta']['days']} 日")
    print("\n分位组合（Q1=因子值最高）：")
    for g in res["groups"]:
        print(f"  Q{g['group']:>2}  年化 {g['ann'] * 100:+7.1f}%  夏普 {g['sharpe']:+5.2f}  "
              f"回撤 {g['maxdd'] * 100:5.1f}%  日胜率 {g['win'] * 100:4.1f}%")
    ls = res["long_short"]
    print(f"  多空(Q1-Q{res['quantiles']}) 年化 {ls['ann'] * 100:+.1f}%  夏普 {ls['sharpe']:+.2f}  "
          f"回撤 {ls['maxdd'] * 100:.1f}%｜单调性 {res['monotonicity']:+.2f}")
    print("\nIC 衰减：", " ".join(f"{h}日 {v['ic']:+.4f}" for h, v in res["ic_decay"].items()))
    print("成本/持有期：", " ".join(
        f"hold{c['hold']} 净{c['ann'] * 100:+.1f}%/换手{c['turnover']:.2f}" for c in res["cost_curve"]))
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"报告：{args.out}（{res['meta']['elapsed_sec']}s）")


if __name__ == "__main__":
    main()
