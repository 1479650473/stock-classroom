# -*- coding: utf-8 -*-
"""价值因子跨周期稳健性(含真熊市 2018/2022) — 2023→now 之外, 补抓 2018-2021 后解锁。

前提: 依赖 `prefetch_kline_history.py` 已补抓 2018-2021 全市场历史 K 线(新浪全历史)。
子区间: 2018(熊, 贸易战/去杠杆) / 2019-2021(修复/结构) / 2022(熊, 加息/疫情) / 2023-2026。
记忆安全: 用 **有 2018 K线的活跃股**(∩ 有基本面) 做池, 默认≤BEAR_UNIVERSE_MAX(默认 2500) 只,
   limit=2400(回溯到 ~2016 供前向 warmup)。
验证: 价值 IC 是否在**真熊市(2018/2022)**一致为正? 选股组合(前20%低PB)在熊市 vs 等权买持?
运行: C:/Python314/python.exe backend/strategy/verify_value_cycle_2018.py  (timeout 600)
环境: BEAR_UNIVERSE_MAX=<N>（默认2500; 小=更快/更省内存）
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

PERIODS = [
    ("2018", "2018-01-01", "2018-12-31", "2018(熊市: 贸易战/去杠杆)"),
    ("2019-2021", "2019-01-01", "2021-12-31", "2019-21(修复/结构)"),
    ("2022", "2022-01-01", "2022-12-31", "2022(熊市: 加息/疫情)"),
    ("2023-2026", "2023-01-01", None, "2023-26(反弹/成长 risk-on)"),
]
LIMIT = int(os.environ.get("VALUE_CYCLE_LIMIT", "2400"))
MAX_U = int(os.environ.get("BEAR_UNIVERSE_MAX", "2500"))


def _pool_with_2018() -> list:
    """活跃股中『有 2018 K线』且『有基本面』的代码(∩) → 熊市跨周期池, 限 MAX_U。"""
    con = sqlite3.connect(get_kline_db_path(), timeout=30)
    try:
        rows = con.execute(
            "SELECT DISTINCT code FROM kline_daily WHERE date<'20180101' AND code IN "
            "(SELECT code FROM kline_daily WHERE date<'20190101' AND date>='20180101') "
            "AND code IN (SELECT code FROM stock_list WHERE status='active')"
            " ORDER BY code").fetchall()
    finally:
        con.close()
    codes = [r[0] for r in rows if has_vals(r[0])]
    return codes[:MAX_U]


def _slice_frames(frames: dict, s: str, e: str) -> dict:
    lo = pd.Timestamp(s) if s else None
    hi = pd.Timestamp(e) if e else None
    out = {}
    for code, df in frames.items():
        sub = df
        if lo is not None:
            sub = sub.loc[sub.index >= lo]
        if hi is not None:
            sub = sub.loc[sub.index <= hi]
        if len(sub) >= 60:
            out[code] = sub
    return out


def _sel_net(res: dict) -> tuple:
    gs = res.get("groupCurves", [])
    if not gs:
        return 1.0, 0.0
    gid = max(c["group"] for c in gs)
    cv = next((c for c in gs if c["group"] == gid), None)
    if not cv or not cv["points"]:
        return 1.0, 0.0
    nav = float(cv["points"][-1]["net"])
    return nav, nav - 1.0


def _bench(subframes: dict) -> tuple:
    rets = []
    for code, df in subframes.items():
        if len(df) < 2:
            continue
        fo, lo = float(df.iloc[0]["open"]), float(df.iloc[-1]["open"])
        if fo > 0 and lo > 0:
            rets.append(lo / fo - 1.0)
    return (sum(rets) / len(rets), len(rets)) if rets else (None, 0)


def main() -> int:
    pool = _pool_with_2018()
    print("=== 价值因子跨周期稳健性(含真熊市 2018/2022) ===", flush=True)
    print(f"池: {len(pool)} 只(2018有K线∩有基本面, 上限{MAX_U}) | LIMIT={LIMIT} | 走 2018→now", flush=True)
    if not pool:
        print("  ⚠ 池为空 —— 请先跑 prefetch_kline_history.py 补抓 2018-2021 K线", flush=True)
        return 1
    frames = load_universe_frames(pool, start="2017-06-01", end=datetime.now().strftime("%Y%m%d"),
                                  with_fundamentals=True, fetch_missing=False, limit=LIMIT)
    print(f"  frames: {len(frames)} 只", flush=True)
    engine = FactorResearchEngine()

    print("\n── 各时期(BP@月度20) IC/ICIR/多空 + 选股组合(前20%) vs 等权买持 ──", flush=True)
    print(f"  {'时期':<12}{'IC':>8}{'ICIR':>7}{'覆盖':>6}{'多空':>9}{'选股组合':>11}{'买持基准':>10}", flush=True)
    rows = []
    for label, s, e, note in PERIODS:
        end = e if e else datetime.now().strftime("%Y%m%d")
        sub = _slice_frames(frames, s, end)
        if not sub:
            print(f"  {label:<12} 无数据", flush=True)
            continue
        try:
            r = engine.run(frames=sub, factor_id="BP", start_date=s, end_date=end,
                           groups=5, holding_period=20, compute_correlation=False)
        except Exception as ex:
            print(f"  {label:<12} 失败 {type(ex).__name__}: {str(ex)[:40]}", flush=True)
            continue
        ic = float(r.get("rankIc", 0.0) or 0.0); icir = float(r.get("icir", 0.0) or 0.0)
        cov = float(r.get("coverage", 0.0) or 0.0); ls = float(r.get("netLongShortReturn", 0.0) or 0.0)
        _, sel = _sel_net(r); bench, bn = _bench(sub)
        rows.append({"label": label, "ic": ic, "icir": icir, "cov": cov, "ls": ls, "sel": sel,
                     "bench": bench, "bn": bn, "note": note})
        print(f"  {label:<12}{ic:>+8.3f}{icir:>7.2f}{cov:>6.0%}{ls:>+9.2%}{sel:>+11.2%}"
              f"{'%+.2f' % bench if bench is not None else 'N/A':>10}", flush=True)

    if rows:
        pos_ic = sum(1 for r in rows if r["ic"] > 0)
        sel_beat = sum(1 for r in rows if r["bench"] is not None and r["sel"] > r["bench"])
        print("\n── 一致性(跨时期含熊市) ──", flush=True)
        print(f"  IC 为正: {pos_ic}/{len(rows)} 期 | 选股组合>买持: {sel_beat}/{len(rows)} 期", flush=True)
        for r in rows:
            b = r["bench"]
            verdict = ("跑赢" if b is not None and r["sel"] > b else
                       ("跑输" if b is not None and r["sel"] < b else "持平/无基准"))
            bench_s = (f"{b:+.2%}" if b is not None else "N/A")
            print(f"    {r['label']}: IC={r['ic']:+.3f} ICIR={r['icir']:+.2f} | 组合 {r['sel']:+.2%} vs 买持 "
                  f"{bench_s} → {verdict} | {r['note']}", flush=True)

    print("\n诚实结论: 价值 IC 在真熊市(2018/2022)是否一致为正? 选股组合在熊市是否跑赢买持? 见上。", flush=True)
    print("局限: 幸存者偏差(活跃∩2018有K线池); 单因子; 池规模上限(内存); 基准等权(小盘倾斜)。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
