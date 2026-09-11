# -*- coding: utf-8 -*-
"""截面机器学习选股（借鉴 Qbot 的策略池：LightGBM/机器学习选股 + Monte-Carlo 检验）。

两个后端：
  - `hgb`  ：sklearn HistGradientBoostingRegressor（本机已装 sklearn，无需 lightgbm）
  - `ridge`：numpy 岭回归（零依赖兜底）

口径与因子体检台一致，便于横向比较：
  - 特征 = 因子动物园的 39 个因子（截面标准化后的面板）
  - 标签 = 未来 1 日 open-to-open 收益（可切 --horizon 5/20）
  - 逐折滚动：训练窗口拟合 → 测试窗口只做预测（严格样本外）
  - 指标：截面 IC、Top-K 组合超额（含成本、持有 hold 天）、多空分位价差、Monte-Carlo 置信区间

用法：
  python -m backend.alpha.ml_rank --model hgb --folds 10 --horizon 1
  python -m backend.alpha.ml_rank --model ridge --mc 500
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


def _design(feats: Dict[str, np.ndarray], names: List[str], target: np.ndarray,
            mask: np.ndarray, lo: int, hi: int) -> Tuple[np.ndarray, np.ndarray]:
    """把 [N,F,T] 面板摊平成 (行=股票×日) 的设计矩阵。"""
    Xs = [feats[n][:, lo:hi] for n in names if feats.get(n) is not None]
    X = np.stack(Xs, axis=2)                     # [N, T, F]
    y = target[:, lo:hi]
    m = mask[:, lo:hi]
    Xf = X[m]                                    # [rows, F]
    yf = y[m]
    ok = np.isfinite(yf)
    return Xf[ok].astype(np.float32), yf[ok].astype(np.float32)


def _fit_predict(kind: str, Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> np.ndarray:
    if kind == "hgb":
        from sklearn.ensemble import HistGradientBoostingRegressor
        model = HistGradientBoostingRegressor(max_depth=4, max_iter=250, learning_rate=0.06,
                                              l2_regularization=0.5, random_state=7)
        model.fit(Xtr, ytr)
        return model.predict(Xte).astype(np.float32)
    # ridge（岭回归，闭式解）
    Xtr1 = np.hstack([Xtr, np.ones((Xtr.shape[0], 1), dtype=np.float32)])
    Xte1 = np.hstack([Xte, np.ones((Xte.shape[0], 1), dtype=np.float32)])
    F = Xtr1.shape[1]
    A = Xtr1.T @ Xtr1 + 1e-2 * np.eye(F, dtype=np.float32)
    b = Xtr1.T @ ytr
    w = np.linalg.solve(A, b)
    return (Xte1 @ w).astype(np.float32)


def _spread(sig: np.ndarray, target: np.ndarray, mask: np.ndarray, lo: int, hi: int,
            q: float = 0.2) -> Tuple[float, float]:
    """多空分位价差（前 q − 后 q，市场中性），返回 (年化, 夏普)。"""
    daily = []
    for t in range(lo, hi):
        m = mask[:, t]
        if m.sum() < 50:
            continue
        idx = np.where(m)[0]
        v, y = sig[idx, t], target[idx, t]
        k = max(5, int(len(idx) * q))
        o = np.argsort(-v)
        daily.append(float(y[o[:k]].mean() - y[o[-k:]].mean()))
    arr = np.array(daily)
    if arr.size < 30:
        return 0.0, 0.0
    ann = arr.mean() * R.TRADING_DAYS
    sr = arr.mean() / (arr.std() + 1e-12) * np.sqrt(R.TRADING_DAYS)
    return float(ann), float(sr)


def monte_carlo(daily: np.ndarray, n: int = 500, block: int = 20, seed: int = 7
                ) -> Dict[str, float]:
    """块自助（block bootstrap）估计收益/夏普/回撤的分布（Qbot 的 monte_carlo 思路）。"""
    rng = np.random.default_rng(seed)
    d = np.asarray(daily, dtype=float)
    T = d.size
    if T < 60:
        return {}
    anns, srs, dds = [], [], []
    nblk = max(1, T // block)
    for _ in range(int(n)):
        starts = rng.integers(0, max(1, T - block), size=nblk)
        path = np.concatenate([d[s:s + block] for s in starts])
        eq = np.cumprod(1 + path)
        anns.append(eq[-1] ** (R.TRADING_DAYS / max(1, path.size)) - 1)
        srs.append(path.mean() / (path.std() + 1e-12) * np.sqrt(R.TRADING_DAYS))
        peak = np.maximum.accumulate(eq)
        dds.append(float(np.max(1 - eq / (peak + 1e-12))))
    f = lambda xs, p: float(np.percentile(xs, p))
    return {"ann_p05": f(anns, 5), "ann_p50": f(anns, 50), "ann_p95": f(anns, 95),
            "sharpe_p05": f(srs, 5), "sharpe_p50": f(srs, 50), "sharpe_p95": f(srs, 95),
            "maxdd_p50": f(dds, 50), "maxdd_p95": f(dds, 95),
            "prob_positive": float(np.mean([x > 0 for x in anns]))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="hgb", choices=["hgb", "ridge"])
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--train-months", type=int, default=24)
    ap.add_argument("--test-months", type=int, default=6)
    ap.add_argument("--folds", type=int, default=10)
    ap.add_argument("--horizon", type=int, default=1, help="预测目标的天数（open-to-open）")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--mc", type=int, default=300, help="Monte-Carlo 次数")
    ap.add_argument("--null-control", action="store_true",
                    help="同时跑随机预测对照（验证多空价差口径，随机应为 0 附近）")
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "alpha_ml.json"))
    args = ap.parse_args()

    t0 = time.time()
    codes = P.pick_universe(limit=args.codes, as_of=args.start)
    pan = P.load_panel(codes, args.start, args.end)
    fields = pan["fields"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats = P.build_features(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats["_TRADABLE"]
    bench = R.bench_series(P.build_target(fields), masks)
    names = [n for n in P.FEATURE_NAMES if feats.get(n) is not None]
    if args.horizon <= 1:
        target = P.build_target(fields)
    else:                                        # 未来 horizon 日 open-to-open
        open_ = fields["open"]
        target = np.zeros_like(open_)
        h = int(args.horizon)
        if open_.shape[1] > h + 1:
            o1, o2 = open_[:, 1:-h], open_[:, h + 1:]
            ok = (o1 > 0) & (o2 > 0)
            tmp = np.zeros_like(o1)
            tmp[ok] = o2[ok] / o1[ok] - 1.0
            target[:, :-h - 1] = tmp
    mask = (masks["_tradable"] > 0.5) & (masks["can_buy"] > 0)
    print(f"面板 {len(codes)} 只 × {len(dates)} 日 | 特征 {len(names)} 个 | "
          f"模型 {args.model} | 预测 {args.horizon} 日收益（{time.time() - t0:.0f}s）", flush=True)

    folds = build_folds(dates, args.train_months, args.test_months, args.folds)
    rows: List[Dict] = []
    rows_null: List[Dict] = []
    for fi, (lo, hi, te) in enumerate(folds, 1):
        Xtr, ytr = _design(feats, names, target, mask, lo, hi)
        Xte, yte = _design(feats, names, target, mask, hi, te)
        pred = _fit_predict(args.model, Xtr, ytr, Xte)
        # 把预测填回面板：**未预测到的位置必须显式屏蔽**，否则占位值(0)会混进排序，
        # 让"选股/多空价差"变成噪声（这一步很容易出隐蔽的前视/伪信号）。
        sig = np.zeros_like(target)
        rows_sel = np.where(mask[:, hi:te])
        sig[rows_sel[0], hi + rows_sel[1]] = pred
        pred_ok = np.zeros_like(target, dtype=bool)
        pred_ok[rows_sel[0], hi + rows_sel[1]] = True
        masks_eval = {"can_buy": (masks["can_buy"] > 0) & pred_ok,
                      "_tradable": pred_ok.astype(np.float32),
                      "can_sell": masks["can_sell"]}
        bench_oo = np.concatenate([np.zeros(hi, dtype=np.float32), bench[hi:]])
        m = R.evaluate(sig, target, masks_eval, slice(hi, te), top_k=args.topk,
                       bench_daily=bench_oo, hold=args.hold)
        spread_ann, spread_sr = _spread(sig, target, mask & pred_ok, hi, te)
        if args.null_control:
            noise = np.random.default_rng(1000 + fi).standard_normal(target.shape).astype(np.float32)
            n_ann, n_sr = _spread(noise, target, mask & pred_ok, hi, te)
            rows_null.append({"fold": fi, "spread_ann": round(n_ann, 4), "spread_sharpe": round(n_sr, 3)})
        rows.append({"fold": fi, "test": f"{dates[hi]}~{dates[te - 1]}",
                     "ic": round(float(m["ic"]), 5), "ex_ann": round(float(m["ex_ann"]), 4),
                     "sortino": round(float(m["ex_sortino"]), 3),
                     "spread_ann": round(spread_ann, 4), "spread_sharpe": round(spread_sr, 3),
                     "maxdd": round(float(m["maxdd"]), 4), "turnover": round(float(m["turnover"]), 3)})
        print(f"  折{fi:>2} {rows[-1]['test']} | IC {m['ic']:+.4f} | 超额 {m['ex_ann'] * 100:+6.1f}% | "
              f"多空 {spread_ann * 100:+6.1f}%（夏普 {spread_sr:+.2f}） | 回撤 {m['maxdd'] * 100:5.1f}%",
              flush=True)

    ic = [r["ic"] for r in rows]
    ex = [r["ex_ann"] for r in rows]
    sp = [r["spread_ann"] for r in rows]
    print(f"\n汇总：IC 均值 {np.mean(ic):+.4f} | 超额均值 {np.mean(ex) * 100:+.1f}%（为正 "
          f"{sum(1 for x in ex if x > 0)}/{len(ex)} 折）| 多空均值 {np.mean(sp) * 100:+.1f}%"
          f"（为正 {sum(1 for x in sp if x > 0)}/{len(sp)} 折）")
    if rows_null:
        na = [r["spread_ann"] for r in rows_null]
        print(f"随机预测对照：多空均值 {np.mean(na) * 100:+.1f}%（应≈0；用于确认多空口径没坏）")
    mc = monte_carlo(np.array([r["ex_ann"] for r in rows]), n=args.mc) if args.mc else {}
    if mc:
        print(f"Monte-Carlo（对每折超额做块自助，{args.mc} 次）：年化 P5/P50/P95 "
              f"{mc['ann_p05'] * 100:+.1f}% / {mc['ann_p50'] * 100:+.1f}% / {mc['ann_p95'] * 100:+.1f}%"
              f" | 夏普 P50 {mc['sharpe_p50']:+.2f} | 正收益概率 {mc['prob_positive'] * 100:.0f}%")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"meta": {"model": args.model, "codes": len(codes), "days": len(dates),
                            "features": len(names), "horizon": args.horizon, "top_k": args.topk,
                            "hold": args.hold, "folds": len(rows),
                            "elapsed_sec": round(time.time() - t0, 1)},
                   "summary": {"ic_mean": float(np.mean(ic)), "ex_mean": float(np.mean(ex)),
                               "ex_positive": int(sum(1 for x in ex if x > 0)),
                               "spread_mean": float(np.mean(sp)),
                               "spread_positive": int(sum(1 for x in sp if x > 0)), **mc},
                   "null_control": rows_null, "folds": rows}, f, ensure_ascii=False, indent=1)
    print(f"报告：{args.out}（用时 {time.time() - t0:.0f}s）")


if __name__ == "__main__":
    main()
