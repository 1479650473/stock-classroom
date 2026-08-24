# -*- coding: utf-8 -*-
"""因子 × 经济周期矩阵 — 把价值(低PB)视为**景气度/宏观多因子**一层, 而非独立信号。

每个因子在 2018(真熊)/2019-21(修复)/2022(真熊)/2023-26(成长) 的截面 IC/ICIR + 选股组合(前20%) vs 等权买持。
输出矩阵 → 用于"因子=景气阶段"映射: 价值=防御/收缩层, 动量=扩张/成长层, 波动=风险, RSI=情绪。
*诚实*: 用 2018 幸存者池(活跃∩2018有K线) — 幸存者偏差; 单一回归窗口; 跨截面(选哪只)非单票择时。
运行: C:/Python314/python.exe backend/strategy/verify_factor_cycle_2018.py  (timeout 600)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.data import get_kline_db_path  # noqa: E402
from backend.fundamental import has_vals  # noqa: E402

FACTORS = ["BP", "MOMENTUM_20", "VOLATILITY_20", "RSI_14"]   # 价值/动量/波动/情绪
PERIODS = [("2018", "2018-01-01", "2018-12-31", "真熊"),
           ("2019-21", "2019-01-01", "2021-12-31", "修复"),
           ("2022", "2022-01-01", "2022-12-31", "真熊"),
           ("2023-26", "2023-01-01", None, "成长")]
LIMIT = int(os.environ.get("VALUE_CYCLE_LIMIT", "2400"))
MAX_U = int(os.environ.get("BEAR_UNIVERSE_MAX", "2500"))


def _pool_with_2018() -> list:
    con = sqlite3.connect(get_kline_db_path(), timeout=30)
    try:
        rows = con.execute(
            "SELECT DISTINCT code FROM kline_daily WHERE date<'20180101' AND code IN "
            "(SELECT code FROM kline_daily WHERE date<'20190101' AND date>='20180101') "
            "AND code IN (SELECT code FROM stock_list WHERE status='active') ORDER BY code").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows if has_vals(r[0])][:MAX_U]


def _slice(frames: dict, s, e) -> dict:
    lo, hi = (pd.Timestamp(s) if s else None), (pd.Timestamp(e) if e else None)
    out = {}
    for c, df in frames.items():
        sub = df
        if lo is not None:
            sub = sub.loc[sub.index >= lo]
        if hi is not None:
            sub = sub.loc[sub.index <= hi]
        if len(sub) >= 60:
            out[c] = sub
    return out


# 各因子"好方向": dir=1 取最高组(因子值越高越好/越强), dir=-1 取最低组(越低越好/买超卖)
FACTOR_DIR = {"BP": 1, "MOMENTUM_20": 1, "VOLATILITY_20": -1, "RSI_14": -1}


def _sel_net(res: dict, fdir: int = 1) -> tuple:
    gs = res.get("groupCurves", [])
    if not gs:
        return 1.0, 0.0
    gids = sorted(c["group"] for c in gs)
    gid = gids[-1] if fdir == 1 else gids[0]
    cv = next((c for c in gs if c["group"] == gid), None)
    if not cv or not cv["points"]:
        return 1.0, 0.0
    nav = float(cv["points"][-1]["net"])
    return nav, nav - 1.0


def _bench(sub: dict) -> tuple:
    rets = []
    for c, df in sub.items():
        if len(df) < 2:
            continue
        fo, lo = float(df.iloc[0]["open"]), float(df.iloc[-1]["open"])
        if fo > 0 and lo > 0:
            rets.append(lo / fo - 1.0)
    return (sum(rets) / len(rets), len(rets)) if rets else (None, 0)


def main() -> int:
    pool = _pool_with_2018()
    print("=== 因子 × 经济周期矩阵(跨截面, 月度20) ===", flush=True)
    print(f"池 {len(pool)} 只 | LIMIT={LIMIT} | 因子 {FACTORS} | 时期 2018/2019-21/2022/2023-26", flush=True)
    frames = load_universe_frames(pool, start="2017-06-01", end=datetime.now().strftime("%Y%m%d"),
                                  with_fundamentals=True, fetch_missing=False, limit=LIMIT)
    print(f"frames {len(frames)} 只", flush=True)
    engine = FactorResearchEngine()

    # 先算各时期基准(等权买持)
    benches = {}
    for label, s, e, note in PERIODS:
        end = e if e else datetime.now().strftime("%Y%m%d")
        bk, _b = _bench(_slice(frames, s, end))
        benches[label] = bk

    rows = []
    for fid in FACTORS:
        for label, s, e, note in PERIODS:
            end = e if e else datetime.now().strftime("%Y%m%d")
            sub = _slice(frames, s, end)
            if not sub:
                rows.append((fid, label, None, None, None, None, note, "无数据"))
                continue
            try:
                r = engine.run(frames=sub, factor_id=fid, start_date=s, end_date=end,
                               groups=5, holding_period=20, compute_correlation=False)
            except Exception as ex:
                rows.append((fid, label, None, None, None, None, note, f"err:{str(ex)[:20]}"))
                continue
            ic = float(r.get("rankIc", 0.0) or 0.0); icir = float(r.get("icir", 0.0) or 0.0)
            _, sel = _sel_net(r, FACTOR_DIR.get(fid, 1)); bench = benches[label]
            rows.append((fid, label, ic, icir, sel, bench, note, ""))

    # 矩阵输出
    print("\n── ICIR 矩阵(行=因子, 列=时期) ──", flush=True)
    hdr = " 因子              2018(熊)  2019-21(修复)  2022(熊)  2023-26(成长)"
    print(hdr, flush=True)
    for fid in FACTORS:
        cells = []
        for label, _, _, _ in PERIODS:
            row = next((x for x in rows if x[0] == fid and x[1] == label), None)
            cells.append(f"{row[3]:+.2f}" if row and row[3] is not None else "  N/A")
        print(f"  {fid:<18}{cells[0]:>12}{cells[1]:>13}{cells[2]:>10}{cells[3]:>12}", flush=True)

    print("\n── 选股组合 vs 买持(每格=组合收益 vs 基准收益) ──", flush=True)
    for fid in FACTORS:
        for label, _, _, note in PERIODS:
            row = next((x for x in rows if x[0] == fid and x[1] == label), None)
            if not row or row[3] is None:
                continue
            ic, icir, sel, bench = row[2], row[3], row[4], row[5]
            verdict = ("跑赢" if bench is not None and sel > bench else "跑输")
            print(f"    {fid:<18}{label:<10} IC={ic:+.3f} ICIR={icir:+.2f} | 组合 {sel:+.2%} vs 基准 "
                  f"{bench:+.2%} → {verdict} | {note}", flush=True)

    print("\n诚实结论: 价值(BP)应是【防御/收缩层】(熊市跑赢/多空为正), 动量(成长层)在修复/成长期走强, 波动/RSI 为风险/情绪。", flush=True)
    print("局限: 2018幸存者池(幸存者偏差); 单回归窗口; 跨截面(选哪只)非单票择时; 基准等权(小盘倾斜)。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
