# -*- coding: utf-8 -*-
"""System 1 横截面决策头：**校准后的"跑赢等权池概率"**（Laya 方法论 × 我们的因子面板）。

这就是"交给小模型"的那部分：**有界的横截面判断**——给定一只票的特征，它未来 N 日跑赢
等权池的概率是多少（带校准 + 弃权带）。无界的部分（选股理由、组合构建、应变）留给 LLM。

为什么选这个任务（而不是时序方向预测，见 `sys1.py` 的实验）：
    · 时序方向：小模型样本外命中 34~35% vs 多数类基线 38.9% —— **没有赢面**；
    · 横截面排序：我们已有证据（HGB 多空价差 +32%、9/10 折为正）—— **有赢面**，值得做成工具。

设计（对齐 Laya 的三条做法）：
    1. **三段切分**：训练 ≤2022 / 校准 2023 / 测试 2024+ —— 温度或保序回归只能在留出集上拟合；
    2. **校准**：raw 概率 → 保序回归（isotonic）→ 校准后概率，报 ECE 前后对比；
    3. **弃权带**：校准后概率落在 [0.45, 0.55] 视为"无信号"（noul 精神），
       只在有信号时给 LLM 用，避免拿噪声当依据。
    4. **对照**：同一测试期，小模型 vs 我们的固定因子组合（-RET1/-RET5/-HIGH60_GAP/-LOG_AMT20）
       —— 回答"该把哪一方的意见交给大模型"。

用法：
    python -m backend.trader.sys1_xsec            # 训练+评估+持久化（几分钟）
    python -m backend.trader.sys1_xsec --codes 300 --horizon 5
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

import sys as _sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACK = os.path.join(_ROOT, "backend")
for _p in (_ROOT, _BACK):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from ..api.paths import DATA_DIR                      # noqa: E402
from ..alpha import panel as P                        # noqa: E402

MODEL_PATH = os.path.join(str(DATA_DIR), "sys1_xsec.pkl")
META_PATH = os.path.join(str(DATA_DIR), "sys1_xsec.json")


def _paths(tag: str = "") -> Tuple[str, str]:
    """分域头：tag='' 为默认（流动池），其它 tag 存 `sys1_xsec_<tag>.pkl/json`。

    为什么分域：实测 LLM 操盘手的选票 65% 在流动池参照系之外（偏好中小盘），
    一个池内模型评判不了另一个域的选择 —— 所以按域各训一个头，评测时才对齐。
    """
    t = f"_{tag}" if tag else ""
    return (os.path.join(str(DATA_DIR), f"sys1_xsec{t}.pkl"),
            os.path.join(str(DATA_DIR), f"sys1_xsec{t}.json"))

TRAIN_END = "2022-12-31"
CAL_END = "2023-12-31"
ABSTAIN_LO, ABSTAIN_HI = 0.45, 0.55


# ───────────────────────── 数据 ─────────────────────────

def _dataset(codes: int, start: str, end: str, horizon: int,
             pool_skip: int = 0, include_bj: bool = False) -> Tuple[Dict, List[str], np.ndarray, np.ndarray]:
    """构造 (特征 dict, 日期, 特征名, 面板 fields, 目标 dict)。

    `pool_skip` 跳过流动性最好的 N 只 → 中小盘域；`include_bj` 纳入北交所。
    """
    uni = P.pick_universe(limit=int(codes), as_of=start, skip=int(pool_skip),
                          include_bj=bool(include_bj))
    pan = P.load_panel(uni, start, end)
    fields = pan["fields"]                      # type: ignore[assignment]
    dates: List[str] = pan["dates"]             # type: ignore[assignment]
    feats = P.build_features(fields)
    masks = P.trade_masks(fields)
    masks["_tradable"] = feats["_TRADABLE"]
    names = [n for n in P.FEATURE_NAMES if feats.get(n) is not None]
    # 目标：未来 horizon 日 open-to-open，相对等权池的超额
    open_ = fields["open"]
    h = int(horizon)
    ret = np.zeros_like(open_)
    if open_.shape[1] > h + 1:
        o1, o2 = open_[:, 1:-h], open_[:, h + 1:]
        ok = (o1 > 0) & (o2 > 0)
        tmp = np.zeros_like(o1)
        tmp[ok] = o2[ok] / o1[ok] - 1.0
        ret[:, :-h - 1] = tmp
    tradable = masks["_tradable"] > 0.5
    pool = np.where(tradable, ret, np.nan)
    pool_mean = np.nanmean(pool, axis=0, keepdims=True)
    excess = ret - np.nan_to_num(pool_mean, nan=0.0)
    mask = tradable & (masks["can_buy"] > 0) & (ret != 0)
    return {"feats": feats, "names": names, "excess": excess, "ret": ret,
            "mask": mask, "fields": fields,
            "codes": list(pan["codes"]), "stock_names": pan.get("names") or {}},         dates, names, excess, mask


def _design(feats: Dict[str, np.ndarray], names: List[str], target: np.ndarray,
            mask: np.ndarray, lo: int, hi: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    cols = []
    for n in names:
        arr = feats.get(n)
        if arr is None:
            continue
        cols.append(arr[:, lo:hi])
    if not cols:
        return np.zeros((0, 0)), np.zeros(0), np.zeros((0, 0), dtype=bool)
    X = np.stack(cols, axis=-1)                  # [N, T, F]
    y = target[:, lo:hi]
    m = mask[:, lo:hi]
    Xf = X.reshape(-1, X.shape[-1])
    yf = y.reshape(-1)
    mf = m.reshape(-1)
    keep = mf & np.isfinite(yf) & np.isfinite(Xf).all(axis=1)
    return Xf[keep], yf[keep], np.zeros((0, 0))


def _split_idx(dates: List[str], train_end: str, cal_end: str) -> Tuple[int, int]:
    def last_le(d: str) -> int:
        idx = [i for i, x in enumerate(dates) if x <= d.replace("-", "")]
        return (idx[-1] + 1) if idx else 0
    return last_le(train_end), last_le(cal_end)


# ───────────────────────── 指标 ─────────────────────────

def _auc(y: np.ndarray, s: np.ndarray) -> float:
    """AUC（不依赖 sklearn 的实现，便于离线复算）。"""
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y > 0
    n1, n0 = int(pos.sum()), int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _ece(p: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    tot = len(y)
    if tot == 0:
        return float("nan")
    err = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        m = (p >= lo) & (p < hi if b < bins - 1 else p <= hi)
        if m.sum() == 0:
            continue
        err += abs(p[m].mean() - (y[m] > 0).mean()) * m.sum() / tot
    return float(err)


# ───────────────────────── 训练 ─────────────────────────

def train(codes: int = 300, start: str = "2016-01-01", end: str = "2026-09-30",
          horizon: int = 5, save: bool = True, pool_skip: int = 0,
          include_bj: bool = False, tag: str = "") -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression

    t0 = time.time()
    ds, dates, names, excess, mask = _dataset(codes, start, end, horizon,
                                              pool_skip=pool_skip, include_bj=include_bj)
    lo_tr, lo_cal = _split_idx(dates, TRAIN_END, CAL_END)
    print(f"面板 {codes} 只 × {len(dates)} 日 | 特征 {len(names)} | horizon {horizon} 日 | "
          f"训练 ≤{TRAIN_END}（{lo_tr} 天）/ 校准 ≤{CAL_END} / 测试其后", flush=True)

    def design(lo, hi):
        return _design(ds["feats"], names, ds["excess"], ds["mask"], lo, hi)

    Xtr, ytr, _ = design(0, lo_tr)
    Xcal, ycal, _ = design(lo_tr, lo_cal)
    Xte, yte, Xte3 = design(lo_cal, len(dates))
    if len(Xtr) < 5000 or len(Xcal) < 500 or len(Xte) < 500:
        return {"error": f"样本不足 train={len(Xtr)} cal={len(Xcal)} test={len(Xte)}"}
    ytr_b = (ytr > 0).astype(int)
    ycal_b = (ycal > 0).astype(int)
    yte_b = (yte > 0).astype(int)

    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, random_state=7,
                                         early_stopping=True, validation_fraction=0.15)
    clf.fit(Xtr, ytr_b)
    p_cal_raw = clf.predict_proba(Xcal)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(p_cal_raw, ycal_b)
    p_te_raw = clf.predict_proba(Xte)[:, 1]
    p_te = iso.predict(p_te_raw)

    base_rate = float(yte_b.mean())
    res: Dict[str, object] = {
        "meta": {"codes": codes, "pool_skip": int(pool_skip), "include_bj": bool(include_bj),
                 "tag": tag, "days": len(dates), "features": len(names),
                 "train_end": TRAIN_END, "cal_end": CAL_END,
                 "test_from": dates[lo_cal], "test_to": dates[-1],
                 "horizon": horizon, "train_n": int(len(Xtr)), "cal_n": int(len(Xcal)),
                 "test_n": int(len(Xte)), "elapsed_sec": round(time.time() - t0, 1)},
        "test": {
            "base_rate": round(base_rate * 100, 2),
            "auc_raw": round(_auc(yte_b, p_te_raw), 4),
            "auc_calibrated": round(_auc(yte_b, p_te), 4),
            "ece_raw": round(_ece(p_te_raw, yte), 4),
            "ece_calibrated": round(_ece(p_te, yte), 4),
            "brier_raw": round(float(np.mean((p_te_raw - yte_b) ** 2)), 4),
            "brier_calibrated": round(float(np.mean((p_te - yte_b) ** 2)), 4),
        },
        "note": ("横截面任务：预测未来 %d 日相对等权池的超额 > 0。"
                 "三段切分（训练≤%s / 校准≤%s / 测试其后），校准只在留出集拟合。"
                 "**排序用 raw 概率、分位做信号**（实测：① 保序回归是阶梯函数，用校准值排序会并列退化；"
                 "② 绝对概率带 [0.45,0.55] 是错的用法——实测'有信号'组超额反而更低，"
                 "因为横截面模型只对排序负责，不对绝对水平负责）。" %
                 (horizon, TRAIN_END, CAL_END)),
    }

    # 弃权带 + 分位超额（用测试期逐日截面）
    n_codes = None
    try:
        n_codes = Xte3.shape[0]
        # 按日分组：Xte3 是 [样本数, F]（keep 后），无法直接还原逐日截面 →
        # 用带掩码的完整面板重新算逐日分位（更省事也更准）
        p_all = np.full_like(ds["excess"], np.nan, dtype=float)   # 校准后（报"概率水平"用）
        raw_all = np.full_like(ds["excess"], np.nan, dtype=float)  # raw（截面对比排序用）
        Xf_all = []
        cols = [ds["feats"][n][:, lo_cal:len(dates)] for n in names if ds["feats"].get(n) is not None]
        Xa = np.stack(cols, axis=-1)
        shape = Xa.shape
        flat = Xa.reshape(-1, shape[-1])
        ok = np.isfinite(flat).all(axis=1)
        pred = np.full(flat.shape[0], np.nan)
        raw = np.full(flat.shape[0], np.nan)
        pr = clf.predict_proba(flat[ok])[:, 1]
        raw[ok] = pr
        pred[ok] = iso.predict(pr)
        p_all = pred.reshape(shape[0], shape[1])
        raw_all = raw.reshape(shape[0], shape[1])
        ex = ds["excess"][:, lo_cal:len(dates)]
        mk = ds["mask"][:, lo_cal:len(dates)]
        for q, label in ((0.9, "top10%"), (0.8, "top20%")):
            vals = []
            for j in range(raw_all.shape[1]):
                col, m = raw_all[:, j], mk[:, j]
                good = np.isfinite(col) & m
                if good.sum() < 30:
                    continue
                thr = np.nanquantile(col[good], q)
                sel = good & (col >= thr)
                if sel.sum():
                    vals.append(float(np.nanmean(ex[sel, j])))
            res.setdefault("deciles", {})[label] = {
                "n_days": len(vals),
                "mean_excess_pct": round(float(np.mean(vals)) * 100, 3) if vals else None,
                "positive_days_pct": round(float(np.mean([v > 0 for v in vals])) * 100, 1) if vals else None,
            }
        # 信号口径：**截面分位**（横截面模型的排序能力才是有意义的，
        # 绝对概率带是错的用法 —— 实测绝对带 [0.45,0.55] 的有信号组超额 -0.095%、
        # 无信号组反而 +0.152%，因为它把"中部"当成了没信息，实际那才是最好的区）
        bands = [("p>=90%", 0.9, 1.0), ("70~90%", 0.7, 0.9), ("30~70%", 0.3, 0.7),
                 ("10~30%", 0.1, 0.3), ("p<=10%", 0.0, 0.1)]
        band_stat = {}
        for label, ql, qh in bands:
            vals = []
            for j in range(raw_all.shape[1]):
                col, m = raw_all[:, j], mk[:, j]
                good = np.isfinite(col) & m
                if good.sum() < 30:
                    continue
                lo_q = np.nanquantile(col[good], ql)
                hi_q = np.nanquantile(col[good], qh)
                sel = good & (col >= lo_q) & (col <= hi_q if qh >= 1 else col < hi_q)
                if sel.sum():
                    vals.append(float(np.nanmean(ex[sel, j])))
            band_stat[label] = {"mean_excess_pct": round(float(np.mean(vals)) * 100, 3) if vals else None,
                                "positive_days_pct": round(float(np.mean([v > 0 for v in vals])) * 100, 1) if vals else None,
                                "n_days": len(vals)}
        top = band_stat.get("p>=90%") or {}
        bot = band_stat.get("p<=10%") or {}
        res["signal_rule"] = {
            "type": "cross_section_quantile",
            "ranking_on": "raw",
            "long_q": 0.9, "short_q": 0.1,
            "note": "横截面模型只对'排序'负责：看多 = 当日预测概率前 10%，看空 = 后 10%，"
                    "中间 80% 一律视为无信号（不要用绝对概率带）",
            "bands": band_stat,
            "top_minus_bottom_pct": (round((top.get("mean_excess_pct") or 0) - (bot.get("mean_excess_pct") or 0), 3)
                                     if top and bot else None),
        }
    except Exception as e:
        res["deciles_error"] = str(e)[:150]

    # 对照：固定因子组合（-RET1/-RET5/-HIGH60_GAP/-LOG_AMT20 等权 rank）—— 直接用面板特征算，
    # 口径与 `alpha/composite.py` 一致，但不必逐日重读数据库（654 天 × snapshot 太慢）
    try:
        f = ds["feats"]
        comp_cols = []
        for nm, sign in (("RET1", -1.0), ("RET5", -1.0), ("HIGH60_GAP", -1.0), ("LOG_AMT20", -1.0)):
            arr = f.get(nm)
            if arr is None:
                continue
            comp_cols.append(sign * np.asarray(arr, dtype=float))
        comp_vals = []
        if comp_cols:
            stack = np.stack(comp_cols, axis=-1)              # [N, T, K]
            for j in range(lo_cal, len(dates)):
                col = stack[:, j, :]
                m = ds["mask"][:, j] & np.isfinite(col).all(axis=1)
                if m.sum() < 30:
                    continue
                # 每个因子先做截面 rank（0~1），再等权平均 → 组合得分
                ranks = []
                for k in range(col.shape[1]):
                    v = col[m, k]
                    r = np.argsort(np.argsort(v)) / max(1, len(v) - 1)
                    ranks.append(r)
                score = np.mean(ranks, axis=0)
                order = np.argsort(-score)[:10]                # Top10（与 composite 的 top_n 一致）
                idx = np.where(m)[0][order]
                comp_vals.append(float(np.nanmean(ds["excess"][idx, j])))
        res["baseline_composite"] = {
            "n_days": len(comp_vals),
            "mean_excess_pct": round(float(np.mean(comp_vals)) * 100, 3) if comp_vals else None,
            "positive_days_pct": round(float(np.mean([v > 0 for v in comp_vals])) * 100, 1) if comp_vals else None,
            "note": "同期的固定因子组合 Top10 平均超额（同一池、同一 horizon，面板内直算）—— 对照用",
        }
    except Exception as e:
        res["baseline_error"] = str(e)[:150]

    if save:
        mp, xp = _paths(tag)
        with open(mp, "wb") as f:
            pickle.dump({"model": clf, "iso": iso, "names": names, "meta": res["meta"]}, f)
        with open(xp, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        res["saved"] = {"model": mp, "meta": xp}
        print("已保存:", mp, "与", xp, flush=True)
    return res


def _fmt(d: str) -> str:
    d = str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


# ───────────────────────── 推理（给工具用） ─────────────────────────

_CACHE: Dict[str, object] = {}


def _load(tag: str = ""):
    key = f"m:{tag}"
    if key not in _CACHE:
        mp, _ = _paths(tag)
        if not os.path.exists(mp):
            return None
        with open(mp, "rb") as f:
            _CACHE[key] = pickle.load(f)
    return _CACHE[key]


def predict(codes: List[str], as_of: Optional[str] = None, lookback_days: int = 400,
            universe_ref: bool = True, tag: str = "") -> dict:
    """对给定代码出「未来 N 日跑赢等权池」的**校准概率** + 截面分位信号。

    两个实现细节（都是实测踩出来的）：
      · **排序用 raw 概率**：保序回归是阶梯函数，顶部会大量并列成同一个值（全是 0.5），
        直接用校准值排序会退化成随机序；
      · **代码数 <20 时用全场（流动性前 400）当参照系**：只给 3 只票时在 3 个值里取分位没有意义。
    """
    m = _load(tag)
    if not m:
        return {"error": f"尚未训练（tag={tag or '默认'}）：先跑 python -m backend.trader.sys1_xsec"}
    as_of = (as_of or "").replace("-", "")[:8]
    if not as_of:
        import datetime as _dt
        as_of = _dt.date.today().strftime("%Y%m%d")
    start = _shift(as_of, lookback_days)
    codes = [str(c) for c in codes][:400]
    ref_codes: List[str] = []
    _meta = (m.get("meta") or {})
    if universe_ref and len(codes) < 20:
        try:
            _lim = int(_meta.get("codes") or 400)
            _skip = int(_meta.get("pool_skip") or 0)
            ref_codes = [c for c in P.pick_universe(limit=_lim, skip=_skip, as_of=as_of) if c not in codes]
        except Exception:
            ref_codes = []
    all_codes = list(dict.fromkeys(codes + ref_codes))
    pan = P.load_panel(all_codes, _fmt(start), _fmt(as_of))
    if not pan.get("dates"):
        return {"error": f"{as_of} 之前无数据"}
    feats = P.build_features(pan["fields"])      # type: ignore[arg-type]
    names = m["names"]
    last = len(pan["dates"]) - 1                 # type: ignore[arg-type]
    rows_all = []
    for i, c in enumerate(pan["codes"]):         # type: ignore[attr-defined]
        try:
            x = np.array([feats[n][i, last] if feats.get(n) is not None else np.nan for n in names],
                         dtype=float).reshape(1, -1)
            if not np.isfinite(x).all():
                rows_all.append({"code": c, "raw": None, "p_beat_pool": None,
                                 "name": (pan.get("names") or {}).get(c, "")})  # type: ignore[union-attr]
                continue
            raw = float(m["model"].predict_proba(x)[0, 1])
            p = float(m["iso"].predict([raw])[0])
            rows_all.append({"code": c, "name": (pan.get("names") or {}).get(c, ""),  # type: ignore[union-attr]
                             "p_beat_pool": round(p, 4), "raw": round(raw, 4)})
        except Exception:
            rows_all.append({"code": c, "raw": None, "p_beat_pool": None, "name": ""})
    # 分位参照系：全场（或单次给的一大批）
    ref = [r["raw"] for r in rows_all if r.get("raw") is not None]
    q90 = float(np.quantile(ref, 0.9)) if len(ref) >= 20 else None
    q10 = float(np.quantile(ref, 0.1)) if len(ref) >= 20 else None
    for r in rows_all:
        if r.get("raw") is None:
            r["signal"] = "数据不足"; continue
        if q90 is None:
            r["signal"] = "无信号"
        else:
            r["signal"] = "看多" if r["raw"] >= q90 else ("看空" if r["raw"] <= q10 else "无信号")
            r["pct_in_universe"] = round(float(np.mean(np.asarray(ref) <= r["raw"])) * 100, 1)
        r["p_beat_pool"] = r["p_beat_pool"] if r["p_beat_pool"] is not None else None
    want = set(codes)
    out = sorted([r for r in rows_all if r["code"] in want],
                 key=lambda r: -(r.get("raw") if r.get("raw") is not None else -1))
    out = [r for r in out if r.get("raw") is not None] or out
    meta = m.get("meta") or {}
    return {"as_of": pan["dates"][-1], "horizon": meta.get("horizon"),
            "rows": out, "features": len(names),
            "reference": f"流动性前 {len(ref)} 只" if ref_codes else "本次给的一批",
            "note": (f"概率=未来 {meta.get('horizon')} 日跑赢等权池的校准估计；"
                     "信号按**截面分位**（看多=参照系前 10%、看空=后 10%、中间无信号），"
                     "排序依据 raw（校准是阶梯函数会并列）。它是统计参考不是指令。")}


def _shift(as_of: str, back_days: int) -> str:
    import datetime as dt
    d = dt.datetime.strptime(as_of, "%Y%m%d") - dt.timedelta(days=int(back_days))
    return d.strftime("%Y%m%d")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=int, default=300)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--pool-skip", type=int, default=0,
                    help="跳过流动性最好的 N 只（分域建模，如 600 = 中小盘域）")
    ap.add_argument("--include-bj", action="store_true", help="池子纳入北交所")
    ap.add_argument("--tag", default="", help="分域头标签（如 mid_small）→ sys1_xsec_<tag>.pkl")
    args = ap.parse_args()
    r = train(args.codes, args.start, args.end, args.horizon, save=not args.no_save,
              pool_skip=args.pool_skip, include_bj=args.include_bj, tag=args.tag)
    if r.get("error"):
        print("失败:", r["error"]); return
    t = r["test"]
    print(f"测试期 {r['meta']['test_from']}~{r['meta']['test_to']}｜样本 {r['meta']['test_n']}")
    print(f"  基准胜率（跑赢池的比例）: {t['base_rate']}%")
    print(f"  AUC: {t['auc_raw']}（校准后 {t['auc_calibrated']}）")
    print(f"  ECE: {t['ece_raw']} → 校准后 {t['ece_calibrated']}")
    print(f"  Brier: {t['brier_raw']} → {t['brier_calibrated']}")
    for k, v in (r.get("deciles") or {}).items():
        print(f"  {k}: 平均超额 {v['mean_excess_pct']}%（{v['positive_days_pct']}% 的日子为正，n={v['n_days']}）")
    if r.get("abstain"):
        a = r["abstain"]
        print(f"  弃权带 {a['band']}: 有信号 {a['coverage_pct']}%｜有信号平均超额 {a['signal_excess_pct']}%"
              f"｜无信号 {a['no_signal_excess_pct']}%")
    if r.get("baseline_composite"):
        b = r["baseline_composite"]
        print(f"  对照·固定因子组合 Top10: 平均超额 {b['mean_excess_pct']}%（{b['positive_days_pct']}% 的日子为正）")
    print("\n" + r["note"])


if __name__ == "__main__":
    main()
