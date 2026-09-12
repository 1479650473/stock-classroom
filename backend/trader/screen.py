# -*- coding: utf-8 -*-
"""自主选股检索引擎 —— 给 AI 操盘手用（不再依赖固定候选池）。

设计动机：候选池由评分卡/因子组合预先算好再交给模型，等于"模型在别人选好的股里挑"；
模型自己要有检索市场的能力，才能形成并检验自己的选股标准。本模块提供：

    screen(as_of, filters, sort_by, ascending, limit)  按条件筛选 + 排序取前 N
    factors_of(code, as_of)                            单只股票的全部可用指标
    DIMENSIONS                                         可用维度与含义（注入提示词，供模型组合条件）

全部 **as-of 安全**：只用 <= as_of（或库内最新）的日线；指标口径与因子库一致
（流通市值 = 成交量 ÷ 换手率 × 收盘价）。
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..api.paths import KLINE_DB

#: 可用筛选/排序维度：名字 → (说明, 单位)
DIMENSIONS: Dict[str, Tuple[str, str]] = {
    "close": ("最新收盘价", "元"),
    "circ_mv": ("流通市值（成交量÷换手率×收盘价）", "亿元"),
    "amount_ma20": ("20 日均成交额", "亿元"),
    "turnover_ma5": ("5 日均换手率", "%"),
    "ret20": ("20 日涨跌幅", "%"),
    "ret60": ("60 日涨跌幅", "%"),
    "ret250": ("250 日涨跌幅", "%"),
    "amp": ("最近 20 日平均振幅", "%"),
    "vol20": ("20 日收益波动率（年化）", "%"),
    "pos60": ("收盘价在 60 日区间的位置", "0~1"),
    "amount_ratio": ("5 日/20 日成交额比", "倍"),
}

#: 过滤条件的简写别名（如 amount_min → amount_ma20）
_ALIAS = {"amount": "amount_ma20", "turnover": "turnover_ma5", "mv": "circ_mv",
          "vol": "vol20", "pos": "pos60", "price": "close"}

_CACHE: Dict[Tuple[str, int], Dict[str, Any]] = {}
_CACHE_MAX = 4


def _load(as_of: Optional[str], window: int = 300) -> Dict[str, Any]:
    """载入全市场近 window 个交易日面板（带简单 LRU 缓存）。"""
    key = (str(as_of or "latest"), window)
    if key in _CACHE:
        return _CACHE[key]
    con = sqlite3.connect(KLINE_DB)
    try:
        if as_of:
            ref = str(as_of).replace("-", "")
        else:
            ref = str(con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0])
        dates = [str(r[0]) for r in con.execute(
            "SELECT DISTINCT date FROM kline_daily WHERE date<=? ORDER BY date DESC LIMIT ?",
            (ref, window))]
        dates.reverse()
        lo = dates[0] if dates else ref
        rows = con.execute(
            "SELECT code,date,open,high,low,close,volume,amount,turnover FROM kline_daily "
            "WHERE date>=? AND date<=?", (lo, ref)).fetchall()
        names = {str(c): str(n or "") for c, n in con.execute("SELECT code,name FROM stock_list")}
        status = {str(c): str(s or "") for c, s in con.execute("SELECT code,status FROM stock_list")}
    finally:
        con.close()
    di = {d: i for i, d in enumerate(dates)}
    data: Dict[str, Dict[str, list]] = {}
    for code, d, o, h, l, c, v, amt, to in rows:
        code = str(code)
        if code[:2] not in ("60", "00", "30", "68"):
            continue
        j = di.get(str(d))
        if j is None:
            continue
        rec = data.setdefault(code, {"close": [0.0] * len(dates), "high": [0.0] * len(dates),
                                     "low": [0.0] * len(dates), "amount": [0.0] * len(dates),
                                     "turnover": [0.0] * len(dates), "volume": [0.0] * len(dates)})
        rec["close"][j] = float(c or 0)
        rec["high"][j] = float(h or 0)
        rec["low"][j] = float(l or 0)
        rec["amount"][j] = float(amt or 0)
        rec["turnover"][j] = float(to or 0)
        rec["volume"][j] = float(v or 0)
    out = {"dates": dates, "data": data, "names": names, "status": status, "as_of": dates[-1] if dates else ref}
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = out
    return out


def _metrics(rec: Dict[str, list], dates: List[str]) -> Dict[str, float]:
    """由单只股票的日线序列算出全部可用维度（最后一个交易日为基准）。"""
    cl = np.array(rec["close"], dtype=float)
    hi = np.array(rec["high"], dtype=float)
    lo = np.array(rec["low"], dtype=float)
    amt = np.array(rec["amount"], dtype=float)
    tur = np.array(rec["turnover"], dtype=float)
    vol = np.array(rec["volume"], dtype=float)
    ok = cl > 0
    if ok.sum() < 10:
        return {}
    i = int(np.where(ok)[0][-1])                     # 最后一个有行情的交易日
    out: Dict[str, float] = {"close": float(cl[i])}
    # 流通市值：成交量 ÷ 换手率 × 收盘价（换手率缺失时用最近有效值）
    t_valid = tur[:i + 1][tur[:i + 1] > 0]
    t_last = float(t_valid[-1]) if t_valid.size else 0.0
    shares = (vol[i] / (t_last / 100.0)) if (t_last > 0 and vol[i] > 0) else 0.0
    out["circ_mv"] = shares * cl[i] / 1e8 if shares else 0.0
    n20 = min(20, i + 1)
    out["amount_ma20"] = float(amt[i - n20 + 1:i + 1].mean()) / 1e8
    a5 = float(amt[i - min(5, i + 1) + 1:i + 1].mean())
    out["amount_ratio"] = (a5 / (out["amount_ma20"] * 1e8)) if out["amount_ma20"] > 0 else 0.0
    n5 = min(5, i + 1)
    out["turnover_ma5"] = float(tur[i - n5 + 1:i + 1][tur[i - n5 + 1:i + 1] > 0].mean() or 0.0) \
        if (tur[i - n5 + 1:i + 1] > 0).any() else 0.0
    for h, key in ((20, "ret20"), (60, "ret60"), (250, "ret250")):
        base = cl[i - h] if i >= h and cl[i - h] > 0 else 0.0
        out[key] = ((cl[i] / base - 1.0) * 100.0) if base else 0.0
    win = slice(max(0, i - 19), i + 1)
    rng = (hi[win] - lo[win]) / np.where(cl[win] > 0, cl[win], np.nan)
    out["amp"] = float(np.nanmean(rng) * 100.0) if np.isfinite(rng).any() else 0.0
    rets = np.diff(cl[win]) / np.where(cl[win][:-1] > 0, cl[win][:-1], np.nan)
    out["vol20"] = float(np.nanstd(rets) * math.sqrt(244) * 100.0) if np.isfinite(rets).any() else 0.0
    lo60 = slice(max(0, i - 59), i + 1)
    h60, l60 = float(np.nanmax(hi[lo60])), float(np.nanmin(lo[lo60]))
    out["pos60"] = (cl[i] - l60) / (h60 - l60) if h60 > l60 else 0.5
    # ST 代理：近 60 个交易日**从未**超过 5.2%，但**至少触碰过一次** 4.5%
    # （ST 的涨跌停是 ±5%，因此"顶到 5% 附近却从不超过"才是 ST 的特征；
    #  只看"从未超过"会把招商银行这类低波动大票误判成 ST —— 实测误判率 15%）
    w60 = slice(max(0, i - 59), i + 1)
    diffs = np.abs(np.diff(cl[w60]) / np.where(cl[w60][:-1] > 0, cl[w60][:-1], np.nan))
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size >= 20:
        out["st_like"] = 1.0 if (diffs.max() <= 0.052 and diffs.max() >= 0.045) else 0.0
    else:
        out["st_like"] = 0.0
    return out


def snapshot(as_of: Optional[str] = None) -> Tuple[Dict[str, Dict[str, float]], str]:
    """全市场指标快照：{code: metrics}（一次性算完，约 1-3 秒，带缓存）。"""
    pan = _load(as_of)
    out: Dict[str, Dict[str, float]] = {}
    for code, rec in pan["data"].items():  # type: ignore[union-attr]
        m = _metrics(rec, pan["dates"])  # type: ignore[arg-type]
        if m and m.get("close", 0) > 0:
            out[code] = m
    return out, str(pan["as_of"])


def screen(as_of: Optional[str] = None, filters: Optional[Dict[str, Any]] = None,
           sort_by: str = "circ_mv", ascending: bool = True, limit: int = 20,
           exclude_st: bool = True) -> Dict[str, Any]:
    """按条件筛选全市场并排序取前 N（as-of 安全）。

    filters 支持的键（全部区间/阈值，可省略）：
        circ_mv_min / circ_mv_max（亿元）、close_min / close_max、
        amount_min（20日均额，亿元）、turnover_min / turnover_max、
        ret20_min / ret20_max、ret60_min / ret60_max、ret250_min / ret250_max、
        amp_max、vol20_max、pos60_min / pos60_max、exclude_st
    """
    snap, ref = snapshot(as_of)
    snap_names = _load(as_of)["names"]  # type: ignore[index]
    # 先剔除指标算不出来的（长期停牌/无换手数据，circ_mv=0）
    snap = {c: m for c, m in snap.items() if m.get("circ_mv", 0) > 0 and m.get("amount_ma20", 0) > 0}
    fl = dict(filters or {})
    if exclude_st:
        fl.setdefault("exclude_st", True)
    # 解析过滤条件：foo_min/foo_max → (指标, 比较)；未知键会被显式返回，避免"静默空结果"
    conds: List[Tuple[str, str, float]] = []
    unknown: List[str] = []
    for k, v in fl.items():
        if k == "exclude_st" or v is None:
            continue
        if not (k.endswith("_min") or k.endswith("_max")):
            unknown.append(k)
            continue
        field = k[:-4]
        op = k[-3:]
        field = _ALIAS.get(field, field)
        if field not in DIMENSIONS:
            unknown.append(k)
            continue
        try:
            conds.append((field, op, float(v)))
        except (TypeError, ValueError):
            unknown.append(k)
    rows: List[Dict[str, Any]] = []
    for code, m in snap.items():
        nm = str(snap_names.get(code, "")).upper()
        is_st_name = ("ST" in nm) or ("退" in nm)
        if fl.get("exclude_st", True) and (m.get("st_like") or is_st_name):
            # 名称含 ST/退 是最可靠的剔除（行为代理会漏掉"ST 但仍有大波动"的票，
            # 实测如 ST龙大 近 60 日最大单日 10.1%）；行为代理则补上"历史 ST"的情况。
            continue
        bad = False
        for field, op, v in conds:
            val = float(m.get(field, 0.0) or 0.0)
            if (op == "min" and val < v) or (op == "max" and val > v):
                bad = True
                break
        if bad:
            continue
        rows.append({"code": code, "name": snap_names.get(code, ""),
                     **{k: round(float(x), 3) if isinstance(x, float) else x
                        for k, x in m.items()}})
    key = sort_by if sort_by in DIMENSIONS else "circ_mv"
    rows.sort(key=lambda r: r.get(key, 0.0), reverse=not ascending)
    top = rows[: max(1, min(int(limit or 20), 100))]
    return {"as_of": ref, "total_matched": len(rows), "sort_by": key,
            "ascending": bool(ascending), "filters": {k: v for k, v in fl.items() if v is not None},
            "unknown_filters": unknown,
            "dimensions": {k: f"{v[0]}（{v[1]}）" for k, v in DIMENSIONS.items()},
            "results": top,
            "note": "流通市值=成交量÷换手率×收盘价；st_like=近60日无±5.5%以上波动（ST代理）"}


def factors_of(code: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """单只股票的可用指标（与 screen 同一口径）。"""
    snap, ref = snapshot(as_of)
    c = str(code)
    m = snap.get(c)
    if not m:
        return {"code": c, "as_of": ref, "error": "没有该股票在此时点的行情（代码错误/停牌/未上市）"}
    return {"code": c, "name": (_load(as_of)["names"] or {}).get(c, ""),  # type: ignore[index]
            "as_of": ref, **{k: round(float(v), 3) for k, v in m.items()},
            "dimension_doc": {k: v[0] for k, v in DIMENSIONS.items()}}
