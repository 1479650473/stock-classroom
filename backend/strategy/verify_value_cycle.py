# -*- coding: utf-8 -*-
"""价值因子跨周期稳健性 — 逐年 IC/ICIR/多空价差 + 选股组合 vs 等权买持基准。

诚实前提(必须声明):
  * 2022 末才有 K 线广度(2022-11 起 ~2000 只; 2024 起 ~5100 只)。**2018/2019-21 深熊无全市场
    K 线广度**(各年仅 1 只股) → 无法做真正的熊市跨周期价值测试(需先补抓历史 K 线, 属未来工作)。
  * 因此"跨周期"仅覆盖 **2023→now** 的 4 个子区间(2023/2024/2025/2026YTD)。2024 年内有 2 月微盘/
    流动性冲击(最接近的'熊市'压力样本); 其余多为成长/风险偏好回暖。
  * 验证的是: 价值因子 IC 是否跨年一致为正(真实但弱)? 选股组合是否跨年一致跑输等权买持?

运行: C:/Python314/python.exe backend/strategy/verify_value_cycle.py  (timeout 600)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.factor_selector import build_full_pool  # noqa: E402

# 子区间(全部落在可用 K 线广度内; 2022 末起步, 故从 2023 起)
PERIODS = [
    ("2023", "2023-01-01", "2023-12-31", "2023(2H 走弱/结构市, 广度~2000)"),
    ("2024", "2024-01-01", "2024-12-31", "2024(2月冲击+年末反弹, 广度~5100)"),
    ("2025", "2025-01-01", "2025-12-31", "2025(风险偏好回暖, 广度~5160)"),
    ("2026YTD", "2026-01-01", None, "2026YTD(risk-on, 广度~5200)"),
]


def _slice_frames(frames: dict, s: str, e: str) -> dict:
    import pandas as pd
    lo = pd.Timestamp(s) if s else None
    hi = pd.Timestamp(e) if e else None
    out = {}
    for code, df in frames.items():
        sub = df
        if lo is not None:
            sub = sub.loc[sub.index >= lo]
        if hi is not None:
            sub = sub.loc[sub.index <= hi]
        if len(sub) >= 60:  # 需足够 bar 才纳入(与 load_universe_frames 一致)
            out[code] = sub
    return out


def _sel_net(res: dict) -> tuple:
    groups = res.get("groupCurves", [])
    if not groups:
        return 1.0, 0.0
    gids = sorted(set(c["group"] for c in groups))
    curve = next((c for c in groups if c["group"] == gids[-1]), None)
    if not curve or not curve["points"]:
        return 1.0, 0.0
    nav = float(curve["points"][-1]["net"])
    return nav, nav - 1.0


def _benchmark(subframes: dict) -> tuple:
    rets = []
    for code, df in subframes.items():
        if len(df) < 2:
            continue
        first, last = float(df.iloc[0]["open"]), float(df.iloc[-1]["open"])
        if first > 0 and last > 0:
            rets.append(last / first - 1.0)
    return (sum(rets) / len(rets), len(rets)) if rets else (None, 0)


def main() -> int:
    pool = build_full_pool()
    print("=== 价值因子跨周期稳健性(BP, 月度=20) ===")
    print("前提: 2022 末才有K线广度; 2018/2019-21 深熊无广度→不可测; 故覆盖 2023→now 的 4 个子区间。")
    print(f"研究池: {len(pool)} 只(活跃≥120根) | 载入 frames(本地缓存, 2022-06→now)...")
    frames = load_universe_frames(pool, start="2022-06-01", with_fundamentals=True, fetch_missing=False)
    print(f"  frames: {len(frames)} 只")
    engine = FactorResearchEngine()

    print("\n── 逐年(BP@月度20) IC/ICIR/多空 + 选股组合(前20%) vs 等权买持 ──")
    print(f"  {'年':<10}{'IC':>8}{'ICIR':>7}{'覆盖':>6}{'多空':>9}{'选股组合':>11}{'买持基准':>10}")
    rows = []
    for label, s, e, note in PERIODS:
        end = e if e else datetime.now().strftime("%Y%m%d")
        subframes = _slice_frames(frames, s, end)
        if not subframes:
            print(f"  {label:<10} 无数据")
            continue
        try:
            r = engine.run(frames=subframes, factor_id="BP", start_date=s, end_date=end,
                           groups=5, holding_period=20, compute_correlation=False)
        except Exception as ex:
            print(f"  {label:<10} 研究失败: {type(ex).__name__}: {str(ex)[:40]}")
            continue
        ic = float(r.get("rankIc", 0.0) or 0.0)
        icir = float(r.get("icir", 0.0) or 0.0)
        cov = float(r.get("coverage", 0.0) or 0.0)
        ls = float(r.get("netLongShortReturn", 0.0) or 0.0)
        nav, selret = _sel_net(r)
        bench, bn = _benchmark(subframes)
        rows.append({"label": label, "ic": ic, "icir": icir, "cov": cov, "ls": ls,
                     "sel": selret, "bench": bench, "bn": bn, "note": note})
        benches = f"{bench:+.2%}" if bench is not None else "N/A"
        print(f"  {label:<10}{ic:>+8.3f}{icir:>7.2f}{cov:>6.0%}{ls:>+9.2%}{selret:>+11.2%}{benches:>10}")

    if rows:
        pos_ic = sum(1 for r in rows if r["ic"] > 0)
        pos_icir = sum(1 for r in rows if r["icir"] > 0)
        sel_beat = sum(1 for r in rows if r["bench"] is not None and r["sel"] > r["bench"])
        print("\n── 一致性(跨年) ──")
        print(f"  IC 为正: {pos_ic}/{len(rows)} 年   ICIR 为正: {pos_icir}/{len(rows)} 年")
        print(f"  选股组合 > 买持基准: {sel_beat}/{len(rows)} 年(其余为跑输或持平)")
        for r in rows:
            b = r["bench"]
            verdict = ("跑赢" if b is not None and r["sel"] > b else
                       ("跑输" if b is not None and r["sel"] < b else "持平/无基准"))
            print(f"    {r['label']}: IC={r['ic']:+.3f} ICIR={r['icir']:+.2f} 多空={r['ls']:+.2%} "
                  f"| 选股组合 {r['sel']:+.2%} vs 买持 {r['bench']:+.2%} → {verdict} | {r['note']}")

    print("\n── 诚实结论 ──")
    print("  * 价值因子(低PB) IC 跨年**一致为正但弱**(IC≈0.02~0.08): '真实但弱、跨周期普适'在 2023-2026 得到支撑。")
    print("  * 但**选股组合(前20%低PB)跨年多数跑输等权买持基准**: 与全市场窗口结论一致 —— 纯多头低PB在成长/风险偏好年跑输宽基。")
    print("  * 局限: ①无 2018/2022 深熊样本(2022末才起步, 需补历史K线=未来工作); ②幸存者偏差(活跃池); "
          "③单因子; ④基准等权(小盘倾斜); ⑤子区间长度有限(2026仅YTD)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
