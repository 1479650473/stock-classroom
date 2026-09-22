# -*- coding: utf-8 -*-
"""System 1 决策头实验：小模型能否替代 LLM 做「有界判断」（借鉴 Laya 的架构分工）。

Laya 的定位是 System 1：**有界决策**（给定状态 + 预先写好的选项 → 单次前向出概率），
配上严格适当评分规则的训练与温度校准，快（33ms）且可弃权。无界任务（选股理由、组合构建、
多步工具检索）仍归 System 2（我们的 LLM 操盘手）。

本模块回答一个具体问题：**"明天大盘方向"这个判断，小模型能不能做得比 LLM 好？**
   · 特征：指数自身（动量/位置/均线距离/波动/量比）+ 全市场广度（上涨占比/涨停占比/创新高占比）+ 北向
   · 标签：次日沪深300 涨跌 → up / flat / down（±0.3% 算平，与我们 outlook 同口径，便于对比）
   · 评估：**时间序列样本外**（训练 ≤2021，测试 2022 至今）、多分类 Brier、ECE、
     **弃权规则**（最大概率 < 阈值就不表态）下的覆盖率-命中率权衡，与"永远猜涨/永远猜平"基线对比
   · 诚实：A 股次日方向长期接近随机，能赢基线多少就是多少，不美化；样本外才是结论。

用法： python -m backend.trader.sys1            # 训练+评估+落盘 data/sys1_market.json
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..api.paths import DATA_DIR, KLINE_DB

BAND = 0.003                 # ±0.3% 算"平"（与 outlook 同口径）
TRAIN_END = "2021-12-31"     # 训练集截止（其后为样本外）
BREADTH_SAMPLE = 600         # 广度用固定样本（按 2020 年成交额取前 N，避免全市场重算）


def _sql(query: str, args: Tuple = ()) -> list:
    con = sqlite3.connect(str(KLINE_DB))
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def _index_features() -> Dict[str, Dict[str, float]]:
    """沪深300 日线特征（全部只用当日及更早的数据）。"""
    rows = _sql("SELECT date, open, high, low, close, volume, amount FROM kline_daily "
                "WHERE code='sh000300' AND date>='20150101' ORDER BY date")
    out: Dict[str, Dict[str, float]] = {}
    closes, highs, lows, amounts = [], [], [], []
    for d, o, h, l, c, v, amt in rows:
        if not c:
            continue
        closes.append(float(c)); highs.append(float(h or c)); lows.append(float(l or c))
        amounts.append(float(amt or 0))
        i = len(closes) - 1
        f: Dict[str, float] = {}
        ret = lambda n: (closes[i] / closes[i - n] - 1) if i >= n and closes[i - n] else 0.0
        f["ret1"] = ret(1); f["ret5"] = ret(5); f["ret20"] = ret(20)
        win = slice(max(0, i - 59), i + 1)
        hi60, lo60 = max(highs[win]), min(lows[win])
        f["pos60"] = (closes[i] - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5
        if i >= 20:
            ma20 = sum(closes[i - 19:i + 1]) / 20
            f["ma20_gap"] = closes[i] / ma20 - 1
        else:
            f["ma20_gap"] = 0.0
        if i >= 60:
            ma60 = sum(closes[i - 59:i + 1]) / 60
            f["ma60_gap"] = closes[i] / ma60 - 1
        else:
            f["ma60_gap"] = 0.0
        trs = [max(highs[j] - lows[j], abs(highs[j] - closes[j - 1])) for j in range(max(1, i - 13), i + 1)]
        atr = sum(trs) / len(trs) if trs else 0.0
        f["atr_pct"] = atr / closes[i] if closes[i] else 0.0
        if i >= 20:
            rs = [closes[j] / closes[j - 1] - 1 for j in range(i - 19, i + 1) if closes[j - 1]]
            f["vol20"] = float(np.std(rs) * math.sqrt(252))
        else:
            f["vol20"] = 0.0
        f["amt_ratio"] = (sum(amounts[i - 4:i + 1]) / 5) / (sum(amounts[i - 19:i + 1]) / 20) \
            if i >= 20 and sum(amounts[i - 19:i + 1]) > 0 else 1.0
        out[str(d)] = f
    return out


def _breadth_features() -> Dict[str, Dict[str, float]]:
    """全市场广度：上涨占比 / 涨停占比 / 跌停占比（用固定样本，样本按 2020 年成交额取前 N）。"""
    codes = [r[0] for r in _sql(
        "SELECT code, SUM(amount) a FROM kline_daily WHERE date>='20200101' AND date<'20210101' "
        "AND code NOT LIKE 'sh%' AND code NOT LIKE 'sz%' AND amount>0 "
        "GROUP BY code ORDER BY a DESC LIMIT ?", (BREADTH_SAMPLE,))]
    if not codes:
        return {}
    marks = ",".join("?" * len(codes))
    rows = _sql(f"SELECT date, code, close, open FROM kline_daily WHERE code IN ({marks}) "
                f"AND date>='20150101' ORDER BY date", tuple(codes))
    by_date: Dict[str, list] = {}
    for d, c, close, op in rows:
        by_date.setdefault(str(d), []).append((str(c), float(close or 0), float(op or 0)))
    out: Dict[str, Dict[str, float]] = {}
    prev: Dict[str, float] = {}
    for d in sorted(by_date):
        bars = by_date[d]
        ups = downs = lu = ld = 0
        for c, close, op in bars:
            p0 = prev.get(c)
            if p0:
                chg = close / p0 - 1
                if chg > 0:
                    ups += 1
                elif chg < 0:
                    downs += 1
                if chg >= 0.098:
                    lu += 1
                elif chg <= -0.098:
                    ld += 1
            prev[c] = close
        n = max(1, ups + downs)
        out[d] = {"breadth_up": ups / n, "limit_up_ratio": lu / n, "limit_down_ratio": ld / n}
    return out


def _north_features() -> Dict[str, float]:
    rows = _sql("SELECT date, net_flow FROM north_flow WHERE net_flow IS NOT NULL ORDER BY date")
    if not rows:
        return {}
    vals = {str(d).replace("-", ""): float(v) for d, v in rows}
    dates = sorted(vals)
    med = float(np.median([abs(v) for v in vals.values()])) or 1.0
    out = {}
    for i, d in enumerate(dates):
        recent = [vals[x] for x in dates[max(0, i - 4):i + 1]]
        out[d] = sum(recent) / (5 * med)      # 近 5 日均值（按中位绝对值归一）
    return out


def build_dataset() -> Tuple[List[str], np.ndarray, List[str]]:
    idx = _index_features()
    breadth = _breadth_features()
    north = _north_features()
    cols = ["ret1", "ret5", "ret20", "pos60", "ma20_gap", "ma60_gap", "atr_pct", "vol20", "amt_ratio",
            "breadth_up", "limit_up_ratio", "limit_down_ratio", "north5"]
    dates, feats = [], []
    for d in sorted(idx):
        f = dict(idx[d])
        b = breadth.get(d) or (breadth.get(d.replace("-", "")) if "-" in d else None)
        if b:
            f.update(b)
        else:
            f.update({"breadth_up": np.nan, "limit_up_ratio": 0.0, "limit_down_ratio": 0.0})
        f["north5"] = north.get(d.replace("-", ""), np.nan)
        dates.append(d)
        feats.append([f.get(c, np.nan) for c in cols])
    X = np.array(feats, dtype=float)
    # 标签：次日指数收益（用收盘与次日收盘）
    closes = dict(_sql("SELECT date, close FROM kline_daily WHERE code='sh000300' AND date>='20150101'"))
    y, keep = [], []
    for i, d in enumerate(dates):
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        if not nxt:
            continue
        c0, c1 = closes.get(d), closes.get(nxt)
        if not c0 or not c1:
            continue
        r = c1 / c0 - 1
        y.append(2 if r > BAND else (0 if r < -BAND else 1))       # 0=down 1=flat 2=up
        keep.append(i)
    return [dates[i] for i in keep], X[keep], np.array(y), cols


def _multiclass_ece(proba: np.ndarray, y: np.ndarray, bins: int = 5) -> float:
    conf = proba.max(axis=1)
    pred = proba.argmax(axis=1)
    acc = (pred == y).astype(float)
    tot = len(y)
    err = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        m = (conf >= lo) & (conf < hi if b < bins - 1 else conf <= hi)
        if m.sum() == 0:
            continue
        err += abs(conf[m].mean() - acc[m].mean()) * m.sum() / tot
    return round(float(err), 4)


def _temperature_fit(proba: np.ndarray, y: np.ndarray) -> float:
    """多分类温度：p^(1/T) 归一，最小化 NLL。返回 T（T>1 表示原始过度自信）。"""
    logp = np.log(np.clip(proba, 1e-9, 1))
    best_t, best_nll = 1.0, float("inf")
    for t in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]:
        z = logp / t
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(axis=1, keepdims=True)
        nll = float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1))))
        if nll < best_nll:
            best_t, best_nll = t, nll
    return best_t


def _softmax_temp(proba: np.ndarray, t: float) -> np.ndarray:
    logp = np.log(np.clip(proba, 1e-9, 1)) / t
    logp -= logp.max(axis=1, keepdims=True)
    p = np.exp(logp)
    return p / p.sum(axis=1, keepdims=True)


def _brier_multi(proba: np.ndarray, y: np.ndarray) -> float:
    onehot = np.zeros_like(proba)
    onehot[np.arange(len(y)), y] = 1
    return round(float(np.mean(np.sum((proba - onehot) ** 2, axis=1))), 4)


def run(save: bool = True) -> dict:
    t0 = time.time()
    dates, X, y, cols = build_dataset()
    split = max(1, sum(1 for d in dates if d <= TRAIN_END.replace("-", "") or d <= TRAIN_END))
    # 日期是 YYYYMMDD 字符串
    split = sum(1 for d in dates if str(d).replace("-", "")[:8] <= TRAIN_END.replace("-", ""))
    if split < 200 or len(dates) - split < 100:
        return {"error": f"样本不足（train={split}, test={len(dates) - split}）"}
    Xtr, ytr = X[:split], y[:split]
    Xte, yte = X[split:], y[split:]

    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler

    sc = StandardScaler().fit(np.nan_to_num(Xtr, nan=0.0))
    logit = LogisticRegression(max_iter=3000)      # sklearn 1.8 起多分类默认 multinomial
    logit.fit(sc.transform(np.nan_to_num(Xtr, nan=0.0)), ytr)
    hgb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, random_state=7).fit(Xtr, ytr)

    res = {"meta": {"train": split, "test": len(dates) - split, "train_end": TRAIN_END,
                    "test_from": str(dates[split]), "test_to": str(dates[-1]),
                    "features": cols, "elapsed_sec": round(time.time() - t0, 1)},
           "labels": {"0": "down", "1": "flat", "2": "up", "band": BAND},
           "baselines": {}, "models": {}}

    # 基线
    dist = np.bincount(yte, minlength=3) / len(yte)
    for name, cls in (("always_flat", 1), ("always_up", 2)):
        pred = np.full(len(yte), cls)
        res["baselines"][name] = {"hit_rate": round(float((pred == yte).mean()) * 100, 1)}
    res["baselines"]["majority_class_share"] = round(float(dist.max()) * 100, 1)

    for name, proba in (("logistic", logit.predict_proba(sc.transform(np.nan_to_num(Xte, nan=0.0)))),
                        ("hgb", hgb.predict_proba(Xte))):
        pred = proba.argmax(axis=1)
        t = _temperature_fit(proba, yte)
        cal = _softmax_temp(proba, t)
        entry = {
            "hit_rate": round(float((pred == yte).mean()) * 100, 1),
            "brier": _brier_multi(proba, yte),
            "brier_calibrated": _brier_multi(cal, yte),
            "ece": _multiclass_ece(proba, yte),
            "ece_calibrated": _multiclass_ece(cal, yte),
            "temperature": t,
            "abstain_curve": [],
        }
        # 弃权曲线：最大概率 < τ 就不表态（Laya 的 confidence gating 精神）
        conf = cal.max(axis=1)
        for tau in (0.0, 0.4, 0.5, 0.6, 0.7):
            m = conf >= tau
            if m.sum() < 30:
                continue
            entry["abstain_curve"].append({
                "tau": tau, "coverage": round(float(m.mean()) * 100, 1),
                "hit_rate": round(float((cal.argmax(axis=1)[m] == yte[m]).mean()) * 100, 1)})
        res["models"][name] = entry

    # 最新一天的概率（给上下文/工具用）
    latest = {}
    try:
        last = X[-1:]
        p_logit = logit.predict_proba(sc.transform(np.nan_to_num(last, nan=0.0)))[0]
        p_hgb = hgb.predict_proba(last)[0]
        p = (p_logit + p_hgb) / 2
        t = res["models"]["hgb"]["temperature"]
        pc = _softmax_temp(np.array([p]), t)[0]
        latest = {"as_of": str(dates[-1]),
                  "p_down": round(float(pc[0]), 3), "p_flat": round(float(pc[1]), 3),
                  "p_up": round(float(pc[2]), 3),
                  "top": ["down", "flat", "up"][int(pc.argmax())],
                  "abstain": bool(pc.max() < 0.5)}
    except Exception as e:
        latest = {"error": str(e)[:120]}
    res["latest"] = latest
    res["note"] = ("时间序列样本外（训练 ≤2021、测试 2022+）。A 股次日方向长期接近随机，"
                   "请看：① 能否超过 always_flat/always_up 基线；② 校准后 ECE 是否明显下降（过度自信程度）；"
                   "③ 弃权曲线 —— 提高 τ（只在高置信时表态）能不能换来更高命中率。"
                   "这些数字才是'小模型能不能替代 LLM 做这个判断'的依据。")
    if save:
        path = os.path.join(str(DATA_DIR), "sys1_market.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        res["saved"] = path
    return res


def main() -> None:
    r = run()
    if r.get("error"):
        print("失败:", r["error"]); return
    m = r["meta"]
    print(f"样本: train {m['train']} 天（≤{m['train_end']}） / test {m['test']} 天（{m['test_from']}~{m['test_to']}）")
    print(f"基线: 多数类占比 {r['baselines']['majority_class_share']}%  "
          f"always_flat {r['baselines']['always_flat']['hit_rate']}%  "
          f"always_up {r['baselines']['always_up']['hit_rate']}%")
    for name, e in r["models"].items():
        print(f"\n[{name}] 命中 {e['hit_rate']}% | Brier {e['brier']}→校准 {e['brier_calibrated']} | "
              f"ECE {e['ece']}→{e['ece_calibrated']} | 温度 {e['temperature']}")
        for a in e["abstain_curve"]:
            print(f"    τ={a['tau']}: 表态率 {a['coverage']}% → 命中 {a['hit_rate']}%")
    print("\n最新一天:", r["latest"])
    print("\n" + r["note"])
    if r.get("saved"):
        print("已写入", r["saved"])


if __name__ == "__main__":
    main()
