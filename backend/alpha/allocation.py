# -*- coding: utf-8 -*-
"""通用组合构建器 —— 任意多条"腿"（策略 / ETF）→ 相关性、固定配比、最优配比。

腿（leg）类型：
    smb            微盘策略（data/smb_result.json，最小 5 只等权）
    equal          等权全市场（同上文件里的 benchmark_equal_weight）
    etf:<code>     任一场内 ETF（kline.db etf_daily，如 511010 国债ETF / 511260 十年国债 / 159972 地方债）
    file:<path>    任意 alpha.smb 风格 JSON（含 strategy.picks + strategy.monthly）

输出：
    各腿统计（年化/波动/夏普/回撤/月胜率）、相关矩阵、
    固定配比表（两腿走细网格，多腿给常用预设）、
    自动配比：等权 / 逆波动 / 最小方差 / 最大夏普（含随机搜索兜底），
    以及最优组合的月度净值（供前端画图）。

用法：
    python -m backend.alpha.allocation --legs smb,etf:511010,etf:511260
    python -m backend.alpha.allocation --legs smb,etf:511010 --grid 0.05 --out data/alloc.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.api.paths import DATA_DIR, KLINE_DB  # noqa: E402

SMB_PATH = os.path.join(str(DATA_DIR), "smb_result.json")


# ───────────────────────── 腿的加载 ─────────────────────────

def _etf_monthly(code: str) -> Tuple[Dict[str, float], str]:
    con = sqlite3.connect(KLINE_DB)
    try:
        rows = con.execute("SELECT date, close FROM etf_daily WHERE code=? ORDER BY date", (code,)).fetchall()
        name = con.execute("SELECT name FROM etf_list WHERE code=?", (code,)).fetchone()
    finally:
        con.close()
    if not rows:
        raise SystemExit(f"etf_daily 里没有 {code}（先跑 scripts/rebuild_etf.py 或补数据）")
    last: Dict[str, float] = {}
    for d, c in rows:
        if c and float(c) > 0:
            last[str(d)[:6]] = float(c)
    months = sorted(last)
    rets = {a: last[b] / last[a] - 1.0 for a, b in zip(months, months[1:])}
    return rets, f"{code} {name[0] if name else ''}"


def _smb_like(path: str, which: str = "strategy") -> Tuple[Dict[str, float], str]:
    d = json.load(open(path, encoding="utf-8"))
    if which == "benchmark":
        eq = ((d.get("benchmark_equal_weight") or {}).get("equity") or [])
        if not eq:
            raise SystemExit(f"{path} 里没有 benchmark_equal_weight.equity")
        months, rets = _months_from_equity(eq, (d.get("strategy") or {}).get("picks"))
        return rets, "等权全市场"
    st = d.get("strategy") or {}
    picks, monthly = st.get("picks") or [], st.get("monthly") or []
    if not picks or not monthly:
        raise SystemExit(f"{path} 里没有 strategy.picks/monthly")
    return {p["month"]: float(r) for p, r in zip(picks, monthly)}, "微盘最小5只"


def _months_from_equity(equity: List[float], picks: Optional[List[dict]]) -> Tuple[List[str], Dict[str, float]]:
    """由净值序列反推月度收益（月份标签优先取 picks 的 month）。"""
    months = [p["month"] for p in (picks or [])]
    if len(months) != len(equity):
        months = [f"M{i:04d}" for i in range(len(equity))]
    rets = {}
    prev = 1.0
    for m, v in zip(months, equity):
        rets[m] = float(v) / prev - 1.0 if prev else 0.0
        prev = float(v)
    return months, rets


def load_leg(spec: str) -> Tuple[str, Dict[str, float]]:
    """返回 (标签, 月度收益)。内部两个 helper 返回的是 (收益, 标签)，这里统一交换。"""
    s = (spec or "").strip()
    if s in ("smb", "微盘", ""):
        rets, label = _smb_like(SMB_PATH, "strategy")
    elif s in ("equal", "等权", "market"):
        rets, label = _smb_like(SMB_PATH, "benchmark")
    elif s.startswith("etf:"):
        rets, label = _etf_monthly(s[4:])
    elif s.startswith("file:"):
        rets, label = _smb_like(s[5:], "strategy")
    elif s.isdigit() and len(s) == 6:          # 裸 6 位数字当 ETF
        rets, label = _etf_monthly(s)
    else:
        raise SystemExit(f"无法识别的腿：{spec}（可用 smb / equal / etf:511010 / file:path）")
    return label, rets


# ───────────────────────── 组合统计 ─────────────────────────

def stats(rets) -> Dict[str, float]:
    a = np.asarray(rets, dtype=float)
    if a.size < 6:
        return {"months": int(a.size)}
    eq = np.cumprod(1 + a)
    ann = float(eq[-1] ** (12 / a.size) - 1)
    vol = float(a.std(ddof=1) * np.sqrt(12)) if a.size > 1 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max(1 - eq / (peak + 1e-12)))
    return {"months": int(a.size), "ann": ann, "vol": vol,
            "sharpe": (ann / vol) if vol > 0 else 0.0,
            "maxdd": mdd, "month_win": float((a > 0).mean()),
            "total": float(eq[-1] - 1)}


def _shrink(cov: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    n = cov.shape[0]
    return cov + np.eye(n) * eps * float(np.trace(cov) / max(n, 1) + 1e-12)


def optimize_weights(X: np.ndarray, n_random: int = 4000, seed: int = 7
                     ) -> Dict[str, List[float]]:
    """等权 / 逆波动 / 最小方差 / 最大夏普（含随机搜索兜底与不放开空约束）。"""
    T, n = X.shape
    mu = X.mean(axis=0)
    cov = np.cov(X, rowvar=False) if T > 2 else np.eye(n)
    cov = np.atleast_2d(_shrink(cov))
    out: Dict[str, List[float]] = {"equal": list(np.ones(n) / n)}
    vol = np.sqrt(np.diag(cov))
    out["inv_vol"] = list(vol ** -1 / np.sum(vol ** -1))
    try:
        inv = np.linalg.inv(cov)
        w = inv @ np.ones(n)
        w = np.clip(w, 0, None)
        out["min_var"] = list(w / w.sum() if w.sum() > 0 else np.ones(n) / n)
        wt = inv @ (mu * 12)                       # 年化收益向量
        wt = np.clip(wt, 0, None)
        out["max_sharpe_analytic"] = list(wt / wt.sum() if wt.sum() > 0 else np.ones(n) / n)
    except Exception:
        pass
    # 随机搜索（Dirichlet），对不可解析或含负权重的情形更稳
    rng = np.random.default_rng(seed)
    best = (-9e9, None)
    for _ in range(max(200, int(n_random))):
        w = rng.dirichlet(np.ones(n))
        r = X @ w
        s = stats(r)
        if s.get("sharpe", -9) > best[0]:
            best = (s["sharpe"], w)
    if best[1] is not None:
        out["max_sharpe"] = list(best[1])
    return out


def build(leg_specs: List[str], cost_one_way: float = 0.0, grid: float = 0.05) -> Dict:
    legs: List[Dict] = []
    series: Dict[str, Dict[str, float]] = {}
    for spec in leg_specs:
        label, rets = load_leg(spec)
        legs.append({"spec": spec, "label": label})
        series[spec] = rets
    common = sorted(set.intersection(*[set(s.keys()) for s in series.values()]))
    if len(common) < 12:
        raise SystemExit(f"各腿重合月份只有 {len(common)} 个，无法比较")
    X = np.array([[series[s][m] for s in leg_specs] for m in common], dtype=float)
    leg_stats = [{"spec": spec, "label": legs[i]["label"], **stats(X[:, i])}
                 for i, spec in enumerate(leg_specs)]
    corr = np.corrcoef(X, rowvar=False) if len(leg_specs) > 1 else np.ones((1, 1))
    weights = optimize_weights(X)
    mixes = []
    if len(leg_specs) == 2:
        w = 0.0
        while w <= 1.0001:
            r = X @ np.array([w, 1 - w])
            mixes.append({"weights": [round(w, 3), round(1 - w, 3)], **stats(r)})
            w += grid
    for name, w in weights.items():
        wv = np.array(w, dtype=float)
        mixes.append({"name": name, "weights": [round(float(x), 4) for x in wv],
                      **stats(X @ wv)})
    best = max((m for m in mixes if m.get("sharpe") is not None),
               key=lambda m: m.get("sharpe", -9), default=None)
    best_eq = None
    if best is not None:
        wv = np.array(best["weights"], dtype=float)
        best_eq = list(np.cumprod(1 + X @ wv))
    return {"legs": leg_stats, "months": common, "corr": corr.tolist(),
            "weights": {k: [round(float(x), 4) for x in v] for k, v in weights.items()},
            "mixes": mixes, "best": best,
            "best_equity": [round(float(x), 4) for x in best_eq] if best_eq else [],
            "leg_equity": {s: [round(float(x), 4) for x in np.cumprod(1 + X[:, i])]
                           for i, s in enumerate(leg_specs)},
            "meta": {"start": common[0], "end": common[-1], "n_months": len(common),
                     "cost_one_way": cost_one_way}}


def available_legs() -> List[Dict[str, str]]:
    """可选腿清单：内置策略 + 库里已有的债券类 ETF（供前端下拉）。"""
    out = [{"spec": "smb", "label": "微盘最小5只（月度）"},
           {"spec": "equal", "label": "等权全市场（月度）"}]
    try:
        con = sqlite3.connect(KLINE_DB)
        rows = con.execute(
            "SELECT e.code, e.name, COUNT(d.date) n FROM etf_list e "
            "JOIN etf_daily d ON d.code=e.code "
            "WHERE e.type='bond' OR e.name LIKE '%国债%' OR e.name LIKE '%债%' "
            "GROUP BY e.code HAVING n > 200 ORDER BY n DESC").fetchall()
        for code, name, n in rows:
            out.append({"spec": f"etf:{code}", "label": f"{code} {name}（{n} 天）"})
        rows2 = con.execute(
            "SELECT e.code, e.name, COUNT(d.date) n FROM etf_list e "
            "JOIN etf_daily d ON d.code=e.code WHERE e.code IN ('510300','510500','159915','512100') "
            "GROUP BY e.code ORDER BY n DESC").fetchall()
        for code, name, n in rows2:
            out.append({"spec": f"etf:{code}", "label": f"{code} {name}（{n} 天）"})
        con.close()
    except Exception:
        pass
    return out


# ───────────────────────── CLI ─────────────────────────

def _fmt(s: Dict[str, float]) -> str:
    return (f"年化 {s.get('ann', 0) * 100:+7.1f}% | 波动 {s.get('vol', 0) * 100:5.1f}% | "
            f"夏普 {s.get('sharpe', 0):5.2f} | 回撤 {s.get('maxdd', 0) * 100:5.1f}% | "
            f"月胜率 {s.get('month_win', 0) * 100:4.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", default="smb,etf:511010", help="逗号分隔：smb / equal / etf:511010 / file:path")
    ap.add_argument("--grid", type=float, default=0.05, help="两腿时的权重网格步长")
    ap.add_argument("--out", default="", help="把完整结果写成 JSON（供 API/前端）")
    args = ap.parse_args()
    specs = [s.strip() for s in args.legs.split(",") if s.strip()]
    res = build(specs, grid=args.grid)
    res["available"] = available_legs()
    print(f"组合构建：{len(specs)} 条腿｜重合 {res['meta']['n_months']} 个月"
          f"（{res['meta']['start']}~{res['meta']['end']}）")
    print("\n单腿：")
    for leg in res["legs"]:
        print(f"  [{leg['spec']:<14}] {leg['label'][:16]:<18} {_fmt(leg)}")
    if len(specs) > 1:
        print("\n相关矩阵：")
        hdr = "        " + "".join(f"{s[:10]:>12}" for s in specs)
        print(hdr)
        for i, s in enumerate(specs):
            print(f"  {s[:6]:<6}" + "".join(f"{res['corr'][i][j]:>12.2f}" for j in range(len(specs))))
    print("\n固定/自动配比：")
    for m in res["mixes"]:
        w = m.get("weights") or []
        tag = m.get("name") or "网格"
        print(f"  {tag:<18}" + "/".join(f"{x:.2f}" for x in w) + f"  {_fmt(m)}")
    best = res.get("best")
    if best:
        print(f"\n最优（按夏普）：{'/'.join(f'{x:.2f}' for x in best['weights'])} → {_fmt(best)}")
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        print(f"结果已写入 {args.out}")


if __name__ == "__main__":
    main()
