# -*- coding: utf-8 -*-
"""规模因子（SMB，小盘−大盘）+ 月度「最小市值 N 只」策略回测。

数据来源与口径
    - **流通市值**：库里有 `volume`（股）与 `turnover`（换手率%）→
      流通股本 = volume / (turnover/100)，流通市值 = 流通股本 × 收盘价。
      实测（600036）推算 206.3 亿股、流通市值 ~4900 亿，与实际一致且逐日稳定；
      用 60 日**中位数**做流通股本，避免个别日换手异常导致市值跳变。
    - **历史涨跌幅**：20/60/250 日收盘涨跌幅（作为第二个维度）。
    - **剔除规则（全部 as-of，不看未来）**：
      ① ST/退市风险代理：过去 60 个交易日**没有**任何单日 |涨跌幅| ≥ 5.5%
         （A 股 ST 股涨跌幅限制为 ±5%，因此这是很好的"当时是不是 ST"的代理）；
      ② 面值退市风险：收盘价 < 2 元；
      ③ 流动性：20 日均成交额 < 5000 万（僵尸股/停牌边缘）；
      ④ 深度下跌：250 日涨跌幅 < -60%；
      ⑤ 主板/创业/科创以外（北交所）不参与；当月停牌（无月末收盘价）跳过。

策略
    每月最后一个交易日：按流通市值升序（可选叠加历史涨跌幅打分）取最小的 N 只，
    等权买入，持有 1 个月，下月最后一个交易日收盘换仓。

用法
    python -m backend.alpha.smb --start 2016-01-01 --end 2025-12-31 --top 5
    python -m backend.alpha.smb --top 5 --mom-weight -0.3 --out data/smb_result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..api.paths import DATA_DIR, KLINE_DB

BOARDS = ("60", "00", "30", "68")


# ───────────────────────── 数据 ─────────────────────────

def _codes(con: sqlite3.Connection) -> List[str]:
    rows = con.execute("SELECT code, name, status FROM stock_list").fetchall()
    out = []
    for code, name, status in rows:
        c = str(code)
        if c[:2] not in BOARDS:
            continue
        out.append(c)
    return out


def load_monthly(codes: List[str], start: str, end: str) -> Dict[str, object]:
    """构造月度面板：月末（每月最后交易日）的快照 + 次月收益。"""
    con = sqlite3.connect(KLINE_DB)
    try:
        rows = con.execute(
            "SELECT code, date, high, low, close, volume, amount, turnover FROM kline_daily "
            "WHERE date>=? AND date<=? AND code IN (%s) ORDER BY date" %
            ",".join("?" for _ in codes),
            [start.replace("-", ""), end.replace("-", "")] + list(codes)).fetchall()
    finally:
        con.close()
    dates = sorted({str(r[1]) for r in rows})
    di = {d: i for i, d in enumerate(dates)}
    ci = {c: i for i, c in enumerate(codes)}
    N, T = len(codes), len(dates)
    close = np.zeros((N, T), dtype=np.float64)
    high = np.zeros((N, T), dtype=np.float64)
    low = np.zeros((N, T), dtype=np.float64)
    amount = np.zeros((N, T), dtype=np.float64)
    shares = np.zeros((N, T), dtype=np.float64)
    turn = np.zeros((N, T), dtype=np.float64)
    ret = np.zeros((N, T), dtype=np.float64)
    for code, d, h, lo, c, vol, amt, to in rows:
        i, j = ci.get(str(code)), di.get(str(d))
        if i is None or j is None:
            continue
        close[i, j] = float(c or 0)
        high[i, j] = float(h or 0)
        low[i, j] = float(lo or 0)
        amount[i, j] = float(amt or 0)
        turn[i, j] = float(to or 0)
        if to and float(to) > 0 and vol:
            shares[i, j] = float(vol) / (float(to) / 100.0)
    # 日涨跌幅
    prev = np.zeros_like(close)
    prev[:, 1:] = close[:, :-1]
    ok = (prev > 0) & (close > 0)
    ret[ok] = close[ok] / prev[ok] - 1.0
    # 月末索引（每个"年月"的最后一个有数据的交易日）
    month_end: List[int] = []
    for j, d in enumerate(dates):
        if j + 1 == T or dates[j + 1][:6] != d[:6]:
            month_end.append(j)
    return {"codes": codes, "dates": dates, "close": close, "high": high, "low": low,
            "amount": amount, "shares": shares, "turn": turn, "ret": ret, "month_end": month_end}


def monthly_features(pan: Dict[str, object]) -> Dict[str, np.ndarray]:
    """月末快照特征：[N, M]（M=月份数）。"""
    close = pan["close"]  # type: ignore[assignment]
    high = pan["high"]  # type: ignore[assignment]
    low = pan["low"]  # type: ignore[assignment]
    amount = pan["amount"]  # type: ignore[assignment]
    shares = pan["shares"]  # type: ignore[assignment]
    turn = pan["turn"]  # type: ignore[assignment]
    ret = pan["ret"]  # type: ignore[assignment]
    me: List[int] = pan["month_end"]  # type: ignore[assignment]
    N = close.shape[0]
    M = len(me)
    out = {k: np.zeros((N, M), dtype=np.float64) for k in
           ("close", "circ_mv", "amt20", "ret20", "ret60", "ret250", "st_like",
            "next_ret", "delisted_next", "next_ret_d1",
            "to5", "amp20", "vol20", "pos60")}
    for m, j in enumerate(me):
        out["close"][:, m] = close[:, j]
        lo = max(0, j - 59)
        sh = np.median(np.where(shares[:, lo:j + 1] > 0, shares[:, lo:j + 1], np.nan), axis=1)
        out["circ_mv"][:, m] = np.nan_to_num(sh) * close[:, j]
        out["amt20"][:, m] = amount[:, max(0, j - 19):j + 1].mean(axis=1)
        for h, key in ((20, "ret20"), (60, "ret60"), (250, "ret250")):
            lo2 = max(0, j - h)
            base = close[:, lo2]
            out[key][:, m] = np.where((base > 0) & (close[:, j] > 0),
                                      close[:, j] / np.where(base > 0, base, np.nan) - 1.0, 0.0)
        win = ret[:, max(0, j - 59):j + 1]
        out["st_like"][:, m] = (np.abs(win) >= 0.055).sum(axis=1) == 0        # 60 日无 ±5% 以上波动
        # 第三维度候选：5 日换手率、20 日振幅、年化波动、60 日区间位置
        w5 = slice(max(0, j - 4), j + 1)
        to_vals = turn[:, w5]
        out["to5"][:, m] = np.where(to_vals > 0, to_vals, np.nan).mean(axis=1)
        w20 = slice(max(0, j - 19), j + 1)
        rng = (high[:, w20] - low[:, w20]) / np.where(close[:, w20] > 0, close[:, w20], np.nan)
        out["amp20"][:, m] = np.nanmean(rng, axis=1) * 100.0
        rr = ret[:, w20]
        out["vol20"][:, m] = np.nanstd(rr, axis=1) * np.sqrt(244) * 100.0
        hi60 = np.nanmax(high[:, max(0, j - 59):j + 1], axis=1)
        lo60 = np.nanmin(low[:, max(0, j - 59):j + 1], axis=1)
        out["pos60"][:, m] = np.where(hi60 > lo60, (close[:, j] - lo60) / (hi60 - lo60), 0.5)
        if m + 1 < M:
            # 可实现收益：优先用下月最后交易日收盘；若该日停牌/退市，用下月内**最后可得**收盘价；
            # 完全无数据（当月退市）按 -50% 折扣 —— 不能因为"下月没有价格"就把股票剔出候选
            # （那等于用未来信息避开退市股，是回测里最隐蔽的前视之一）。
            lo2, hi2 = me[m] + 1, me[m + 1]
            seg = close[:, lo2:hi2 + 1]
            nxt = np.zeros(N)
            has = np.zeros(N, dtype=bool)
            for k in range(seg.shape[1] - 1, -1, -1):
                col = seg[:, k]
                take = (~has) & (col > 0)
                if take.any():
                    nxt[take] = col[take]
                    has |= take
            base = close[:, j]
            with np.errstate(invalid="ignore", divide="ignore"):
                r = np.where(has & (base > 0), nxt / np.where(base > 0, base, np.nan) - 1.0, -0.5)
            out["next_ret"][:, m] = r
            out["delisted_next"][:, m] = np.where(has, 0.0, 1.0)
            # 延后 1 个交易日成交（买：下月第 1 个交易日；卖：下下月第 1 个交易日）
            Tn = close.shape[1]
            if m + 2 < M and me[m] + 1 < Tn:
                e = me[m] + 1
                x = min(me[m + 1] + 1, Tn - 1)
                e_px, x_px = close[:, e], close[:, x]
                out["next_ret_d1"][:, m] = np.where((e_px > 0) & (x_px > 0),
                                                   x_px / np.where(e_px > 0, e_px, np.nan) - 1.0, np.nan)
    return out


def tradable_mask(f: Dict[str, np.ndarray], min_price: float = 2.0,
                  min_amount: float = 5e7, max_drop250: float = -0.60) -> np.ndarray:
    """as-of 剔除规则（返回 [N, M] 布尔：True = 当月可选）。"""
    ok = (f["close"] > min_price) & (f["circ_mv"] > 0) & (f["amt20"] >= min_amount)
    ok &= ~f["st_like"].astype(bool)
    ok &= f["ret250"] > max_drop250
    return ok


# ───────────────────────── 回测 ─────────────────────────

def _rank01(x: np.ndarray) -> np.ndarray:
    """截面 rank 归一化到 [0,1]（NaN 视为中位）。"""
    v = np.where(np.isfinite(x), x, np.nan)
    if not np.isfinite(v).any():
        return np.zeros_like(x)
    order = np.argsort(np.argsort(np.nan_to_num(v, nan=float(np.nanmedian(v)))))
    return order / max(1, len(v) - 1)


def backtest(f: Dict[str, np.ndarray], mask: np.ndarray, top: int = 5,
             mom_weight: float = 0.0, mom_key: str = "ret60",
             cost_one_way: float = 0.0, ret_key: str = "next_ret",
             tilts: Optional[List[Tuple[str, float]]] = None) -> Dict[str, object]:
    """每月选股 → 持有一个月。

    打分 = −rank(流通市值) + Σ w·rank(维度)（rank 归一化到 0~1，便于多维度叠加）。
    tilts 例：[("ret60", 0.3), ("to5", -0.15)]（权重为正 = 偏好该维度值大）。
    mom_weight/mom_key 是 tilts 的简写形式（向后兼容）。
    """
    tilt_list: List[Tuple[str, float]] = list(tilts or [])
    if mom_weight:
        tilt_list.append((mom_key, float(mom_weight)))
    N, M = f["circ_mv"].shape
    size = np.log(np.where(f["circ_mv"] > 0, f["circ_mv"], np.nan))
    picks: List[Dict] = []
    rets: List[float] = []
    for m in range(M - 1):
        m_ok = mask[:, m]
        if m_ok.sum() < max(20, top):
            continue
        score = -1.0 * _rank01(size[:, m])                    # 越小市值 → 分越高
        for field, w in tilt_list:
            arr = f.get(field)
            if arr is None:
                continue
            score = score + float(w) * _rank01(arr[:, m])
        score = np.where(m_ok, score, -np.inf)
        order = np.argsort(-score)[:top]
        r = f[ret_key][order, m]
        r = r[np.isfinite(r)]
        if r.size == 0:
            continue
        gross = float(np.mean(r))
        rets.append(gross - 2.0 * cost_one_way)      # 月度全换仓：双边成本
        picks.append({"month": str(f["month_labels"][m]), "codes": [str(f["codes"][i]) for i in order],
                      "names": [f["names"].get(str(f["codes"][i]), "") for i in order],
                      "mv_yi": [round(float(f["circ_mv"][i, m]) / 1e8, 1) for i in order],
                      "next_ret": round(float(np.mean(r)) - 2.0 * cost_one_way, 4),
                      "avg_mv_yi": round(float(np.mean(f["circ_mv"][order, m])) / 1e8, 1)})
    daily = np.array(rets, dtype=float)
    if daily.size == 0:
        return {"error": "没有可回测的月份"}
    days_per_month = 244 / 12
    eq = np.cumprod(1 + daily)
    ann = float(eq[-1] ** (12 / daily.size) - 1)
    vol = float(daily.std() * np.sqrt(12))
    sharpe = float(daily.mean() / (daily.std() + 1e-12) * np.sqrt(12))
    peak = np.maximum.accumulate(eq)
    maxdd = float(np.max(1 - eq / (peak + 1e-12)))
    t_stat = float(daily.mean() / (daily.std() / np.sqrt(daily.size) + 1e-12))
    return {"months": int(daily.size), "t_stat": t_stat,
            "equity": [round(float(x), 4) for x in eq],
            "monthly": [round(float(x), 4) for x in daily], "total": float(eq[-1] - 1),
            "ann": ann, "vol": vol, "sharpe": sharpe, "maxdd": maxdd,
            "month_win": float((daily > 0).mean()), "picks": picks,
            "years": _year_returns(picks, daily)}


def _year_returns(picks: List[Dict], daily: np.ndarray) -> List[Dict]:
    buckets: Dict[str, List[float]] = {}
    for p, r in zip(picks, daily):
        buckets.setdefault(p["month"][:4], []).append(r)
    out = []
    for y in sorted(buckets):
        xs = np.array(buckets[y])
        out.append({"year": y, "ret": round(float(np.prod(1 + xs) - 1), 4), "months": len(xs)})
    return out


def smb_series(f: Dict[str, np.ndarray], mask: np.ndarray, n_group: int = 100) -> Dict[str, object]:
    """SMB：小盘组 − 大盘组 的月度收益（按市值分组，简单两分法）。"""
    N, M = f["circ_mv"].shape
    ls: List[float] = []
    small: List[float] = []
    big: List[float] = []
    for m in range(M - 1):
        m_ok = mask[:, m] & np.isfinite(f["next_ret"][:, m])
        idx = np.where(m_ok)[0]
        if idx.size < 2 * n_group:
            continue
        order = idx[np.argsort(f["circ_mv"][idx, m])]
        s, b = order[:n_group], order[-n_group:]
        rs = float(np.mean(f["next_ret"][s, m]))
        rb = float(np.mean(f["next_ret"][b, m]))
        small.append(rs)
        big.append(rb)
        ls.append(rs - rb)
    arr = np.array(ls)
    return {"months": int(arr.size), "mean_month": float(arr.mean()) if arr.size else 0.0,
            "ann": float(arr.mean() * 12) if arr.size else 0.0,
            "t_stat": float(arr.mean() / (arr.std() / np.sqrt(arr.size) + 1e-12)) if arr.size else 0.0,
            "win": float((arr > 0).mean()) if arr.size else 0.0,
            "equity": [round(float(x), 4) for x in np.cumprod(1 + arr)]}


# ───────────────────────── 主流程 ─────────────────────────

def run(start: str = "2016-01-01", end: str = "2025-12-31", top: int = 5,
        mom_weight: float = 0.0, mom_key: str = "ret60", smb_group: int = 100,
        min_amount: float = 5e7, min_price: float = 2.0,
        cost_one_way: float = 0.0,
        tilts: Optional[List[Tuple[str, float]]] = None,
        save: Optional[str] = None) -> Dict[str, object]:
    t0 = time.time()
    con = sqlite3.connect(KLINE_DB)
    codes = _codes(con)
    names = {str(c): str(n or "") for c, n in con.execute("SELECT code, name FROM stock_list")}
    con.close()
    pan = load_monthly(codes, start, end)
    f = monthly_features(pan)
    me: List[int] = pan["month_end"]  # type: ignore[assignment]
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    f["codes"] = pan["codes"]  # type: ignore[assignment]
    f["names"] = names  # type: ignore[assignment]
    f["month_labels"] = [dates[j][:6] for j in me]
    mask = tradable_mask(f, min_price=min_price, min_amount=min_amount)
    res = backtest(f, mask, top=top, mom_weight=mom_weight, mom_key=mom_key,
                   cost_one_way=cost_one_way, tilts=tilts)
    # 宽度对照 + 成本敏感性（把"最小 5 只"的效应宽度与成本承受力一并给出）
    variants = []
    for n in (5, 10, 20, 50):
        v = backtest(f, mask, top=n, mom_weight=mom_weight, mom_key=mom_key,
                     cost_one_way=cost_one_way, tilts=tilts)
        variants.append({"top": n, "ann": v.get("ann"), "sharpe": v.get("sharpe"),
                         "maxdd": v.get("maxdd"), "month_win": v.get("month_win")})
    cost_curve = []
    for c in (0.0, 0.001, 0.003, 0.005, 0.01):
        v = backtest(f, mask, top=top, mom_weight=mom_weight, mom_key=mom_key,
                     cost_one_way=c, tilts=tilts)
        cost_curve.append({"cost_one_way": c, "ann": v.get("ann"), "sharpe": v.get("sharpe"),
                           "maxdd": v.get("maxdd")})
    # 延后一天成交（买下月第一个交易日收盘、卖下下月第一个交易日收盘）—— 检验"月末收盘价成交"的假设
    delay = backtest(f, mask, top=top, mom_weight=mom_weight, mom_key=mom_key,
                     cost_one_way=cost_one_way, ret_key="next_ret_d1", tilts=tilts)
    smb = smb_series(f, mask, n_group=smb_group)
    # 对照：可选标的的全市场等权（月末等权持有 1 个月）
    all_rets = []
    for m in range(len(me) - 1):
        m_ok = mask[:, m] & np.isfinite(f["next_ret"][:, m])
        if m_ok.sum() >= 20:
            all_rets.append(float(np.mean(f["next_ret"][m_ok, m])))
    bench = np.array(all_rets)
    bench_ann = float(np.prod(1 + bench) ** (12 / bench.size) - 1) if bench.size else 0.0
    out = {"meta": {"start": dates[0], "end": dates[-1], "months": len(me) - 1,
                    "universe_codes": len(codes), "top": top, "mom_weight": mom_weight,
                    "mom_key": mom_key, "min_amount": min_amount, "min_price": min_price,
                    "tilts": [f"{k}:{v}" for k, v in (tilts or [])],
                    "smb_group": smb_group, "elapsed_sec": round(time.time() - t0, 1),
                    "rule": "流通市值=volume/(turnover/100)×close；剔除 ST代理(60日无±5.5%波动)/"
                            "价格<2元/20日均额<5千万/250日跌幅<-60%/当月停牌"},
           "strategy": res, "smb": smb,
           "benchmark_equal_weight": {"ann": bench_ann,
                                      "months": int(bench.size),
                                      "equity": [round(float(x), 4) for x in np.cumprod(1 + bench)]},
           "variants": variants, "cost_curve": cost_curve,
           "delay_one_day": {"ann": delay.get("ann"), "sharpe": delay.get("sharpe"),
                             "maxdd": delay.get("maxdd"), "month_win": delay.get("month_win"),
                             "total": delay.get("total"), "months": delay.get("months")},
           "delisting_events": int(float(np.nansum(f["delisted_next"] * mask))),
           "mask_stats": {"avg_selectable": float(mask.mean()), "months": int(mask.shape[1])}}
    if save:
        os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
        with open(save, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--mom-weight", type=float, default=0.0,
                    help="叠加历史涨跌幅权重（<0 偏好跌得多=反转，>0 偏好涨得多=动量）")
    ap.add_argument("--mom-key", default="ret60", choices=["ret20", "ret60", "ret250"])
    ap.add_argument("--smb-group", type=int, default=100, help="SMB 分组每组只数")
    ap.add_argument("--min-amount", type=float, default=5e7)
    ap.add_argument("--min-price", type=float, default=2.0)
    ap.add_argument("--cost", type=float, default=0.0, help="单边成本（如 0.003 = 千三），月度换仓按双边计")
    ap.add_argument("--compare-tilts", action="store_true",
                    help="额外对比若干多维度组合（动量/换手/波动/位置），结果存进报告")
    ap.add_argument("--tilt", action="append", default=[],
                    help='多维度打分，可重复：--tilt "ret60:0.3" --tilt "to5:-0.15"（正=偏好该维度值大）')
    ap.add_argument("--out", default=os.path.join(str(DATA_DIR), "smb_result.json"))
    args = ap.parse_args()
    tilts = []
    for t in (args.tilt or []):
        if ":" in t:
            k, _, v = t.partition(":")
            try:
                tilts.append((k.strip(), float(v)))
            except ValueError:
                pass
    res = run(args.start, args.end, args.top, args.mom_weight, args.mom_key,
              args.smb_group, args.min_amount, args.min_price, cost_one_way=args.cost,
              tilts=tilts, save=args.out)
    if args.compare_tilts:
        # 多维度组合对比（同一份数据、同一成本口径）：回答"再加维度能不能提升"
        con = sqlite3.connect(KLINE_DB)
        codes2 = _codes(con)
        names2 = {str(c): str(n or "") for c, n in con.execute("SELECT code, name FROM stock_list")}
        con.close()
        pan2 = load_monthly(codes2, args.start, args.end)
        f2 = monthly_features(pan2)
        me2: List[int] = pan2["month_end"]  # type: ignore[assignment]
        dt2: List[str] = pan2["dates"]  # type: ignore[assignment]
        f2["codes"] = pan2["codes"]  # type: ignore[assignment]
        f2["names"] = names2  # type: ignore[assignment]
        f2["month_labels"] = [dt2[j][:6] for j in me2]
        mask2 = tradable_mask(f2, min_price=args.min_price, min_amount=args.min_amount)
        combos = [("纯小市值", []), ("+60日动量0.3", [("ret60", 0.3)]),
                  ("+动量-高换手", [("ret60", 0.3), ("to5", -0.15)]),
                  ("+动量-高波动", [("ret60", 0.3), ("vol20", -0.15)]),
                  ("+动量-高位", [("ret60", 0.3), ("pos60", -0.15)]),
                  ("+动量+低振幅", [("ret60", 0.3), ("amp20", -0.15)])]
        cmp_rows = []
        for nm, tl in combos:
            v = backtest(f2, mask2, top=args.top, cost_one_way=args.cost, tilts=tl)
            cmp_rows.append({"name": nm, "ann": v.get("ann"), "sharpe": v.get("sharpe"),
                             "maxdd": v.get("maxdd"), "month_win": v.get("month_win"),
                             "t_stat": v.get("t_stat")})
            print(f"  {nm:<14} 年化 {(v.get('ann') or 0) * 100:+7.1f}% | 夏普 {v.get('sharpe') or 0:5.2f} | "
                  f"回撤 {(v.get('maxdd') or 0) * 100:5.1f}% | 月均 t={v.get('t_stat') or 0:+.2f}")
        res["tilt_compare"] = cmp_rows
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=1)
    s = res["strategy"]  # type: ignore[index]
    m = res["meta"]  # type: ignore[index]
    print(f"规模因子回测：{m['start']}~{m['end']}（{m['months']} 个月，"
          f"股票池 {m['universe_codes']} 只，可选中位数 {res['mask_stats']['avg_selectable'] * 100:.0f}%）")
    print(f"\n策略：每月选流通市值最小的 {args.top} 只等权持有一个月"
          f"{'，叠加 ' + args.mom_key + f' 权重 {args.mom_weight}' if args.mom_weight else ''}")
    print(f"  累计 {s['total'] * 100:+.1f}% | 年化 {s['ann'] * 100:+.1f}% | 波动 {s['vol'] * 100:.1f}% | "
          f"夏普 {s['sharpe']:.2f} | 最大回撤 {s['maxdd'] * 100:.1f}% | 月胜率 {s['month_win'] * 100:.1f}%")
    print(f"  对照：等权全市场 年化 {res['benchmark_equal_weight']['ann'] * 100:+.1f}%")  # type: ignore[index]
    print(f"  平均持仓流通市值 {np.mean([p['avg_mv_yi'] for p in s['picks']]):.1f} 亿元"
          f"｜当月无价格（退市/停牌）事件 {res['delisting_events']} 次（已按 -50% 保守计）")
    print("\n宽度对照（每月选最小的 N 只）：")
    for v in res["variants"]:  # type: ignore[index]
        print(f"  Top{v['top']:<3} 年化 {(v['ann'] or 0) * 100:+7.1f}% | 夏普 {v['sharpe']:5.2f} | "
              f"回撤 {(v['maxdd'] or 0) * 100:5.1f}% | 月胜率 {(v['month_win'] or 0) * 100:4.1f}%")
    print("\n成本敏感性（单边成本 → 年化）：")
    print("  " + " | ".join(f"{c['cost_one_way'] * 100:.1f}%: {(c['ann'] or 0) * 100:+.1f}%"
                            for c in res["cost_curve"]))  # type: ignore[index]
    smb = res["smb"]  # type: ignore[index]
    print(f"\nSMB（小盘组{args.smb_group}只 − 大盘组{args.smb_group}只）：月均 {smb['mean_month'] * 100:+.2f}%"
          f"（年化 {smb['ann'] * 100:+.1f}%，t={smb['t_stat']:+.2f}，胜率 {smb['win'] * 100:.0f}%，{smb['months']} 个月）")
    print("\n分年收益：")
    for y in s["years"]:
        print(f"  {y['year']}  {y['ret'] * 100:+7.1f}%（{y['months']} 个月）")
    print("\n最近 6 个月持仓：")
    for p in s["picks"][-6:]:
        print(f"  {p['month']} 月收益 {p['next_ret'] * 100:+6.1f}% | " +
              "、".join(f"{n}({c},{mv}亿)" for c, n, mv in zip(p["codes"], p["names"], p["mv_yi"])))
    print(f"\n报告：{args.out}（{m['elapsed_sec']}s）")


if __name__ == "__main__":
    main()
