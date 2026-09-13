# -*- coding: utf-8 -*-
"""固定配置测试 —— 微盘组合 + 债券 ETF（对应"用债券半仓把回撤压下来"的思路）。

数据
    · 微盘腿：`data/smb_result.json`（alpha.smb 产出的月度收益）
    · 债券腿：kline.db `etf_daily`（默认 511010 国债ETF，2013 年起；可换 511260/159972）

方法
    两腿都在**月末**取值、每月再平衡回目标权重（w 微盘 / 1−w 债券）。
    给出各权重的年化/波动/夏普/最大回撤/月胜率、两腿相关系数、
    以及两种"自动配比"：HRP（风险平价，按波动倒数分配）与最大夏普网格搜索。

用法
    python -m backend.alpha.allocation --bond 511010
    python -m backend.alpha.allocation --strategy data/smb_result.json --bond 511260
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.api.paths import DATA_DIR, KLINE_DB  # noqa: E402

TRADING_DAYS = 244


def bond_monthly(code: str) -> Dict[str, float]:
    """债券 ETF 的月末收盘价 → 月度收益。"""
    con = sqlite3.connect(KLINE_DB)
    try:
        rows = con.execute("SELECT date, close FROM etf_daily WHERE code=? ORDER BY date", (code,)).fetchall()
    finally:
        con.close()
    if not rows:
        raise SystemExit(f"etf_daily 里没有 {code}（可先跑 scripts/rebuild_etf.py 或手动补）")
    month_last: Dict[str, float] = {}
    for d, c in rows:
        if c and float(c) > 0:
            month_last[str(d)[:6]] = float(c)
    months = sorted(month_last)
    out = {}
    for a, b in zip(months, months[1:]):
        out[a] = month_last[b] / month_last[a] - 1.0
    return out


def strategy_monthly(path: str) -> Tuple[Dict[str, float], Dict]:
    d = json.load(open(path, encoding="utf-8"))
    st = d.get("strategy") or {}
    picks = st.get("picks") or []
    rets = st.get("monthly") or []
    out = {p["month"]: float(r) for p, r in zip(picks, rets)}
    return out, d


def stats(rets: List[float]) -> Dict[str, float]:
    a = np.array(rets, dtype=float)
    if a.size < 6:
        return {}
    eq = np.cumprod(1 + a)
    ann = float(eq[-1] ** (12 / a.size) - 1)
    vol = float(a.std(ddof=1) * np.sqrt(12)) if a.size > 1 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max(1 - eq / (peak + 1e-12)))
    return {"months": int(a.size), "ann": ann, "vol": vol,
            "sharpe": (ann / vol) if vol > 0 else 0.0,
            "maxdd": mdd, "month_win": float((a > 0).mean()),
            "total": float(eq[-1] - 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default=os.path.join(str(DATA_DIR), "smb_result.json"))
    ap.add_argument("--bond", default="511010", help="债券 ETF 代码（511010 国债 / 511260 十年国债 / 159972 地方债）")
    ap.add_argument("--weights", default="1.0,0.7,0.5,0.3,0.0", help="微盘权重列表，1.0=纯微盘，0.0=纯债券")
    args = ap.parse_args()

    eq_m, meta = strategy_monthly(args.strategy)
    bd_m = bond_monthly(args.bond)
    months = sorted(set(eq_m) & set(bd_m))
    if len(months) < 12:
        raise SystemExit(f"重合月份只有 {len(months)} 个，无法比较")
    eq = [eq_m[m] for m in months]
    bd = [bd_m[m] for m in months]
    print(f"微盘腿 {meta.get('meta', {}).get('start')}~{meta.get('meta', {}).get('end')}"
          f"（成本单边 {meta.get('meta', {}).get('cost_one_way')}）｜债券腿 {args.bond}"
          f"｜重合 {len(months)} 个月（{months[0]}~{months[-1]}）")
    c = float(np.corrcoef(eq, bd)[0, 1])
    s_eq, s_bd = stats(eq), stats(bd)
    print(f"\n单腿：微盘 年化 {s_eq['ann'] * 100:+.1f}% 波动 {s_eq['vol'] * 100:.1f}% "
          f"夏普 {s_eq['sharpe']:.2f} 回撤 {s_eq['maxdd'] * 100:.1f}%")
    print(f"      债券 年化 {s_bd['ann'] * 100:+.1f}% 波动 {s_bd['vol'] * 100:.1f}% "
          f"夏普 {s_bd['sharpe']:.2f} 回撤 {s_bd['maxdd'] * 100:.1f}%")
    print(f"      相关性 {c:+.2f}")

    print("\n固定配置（每月再平衡）：")
    print(f"  {'微盘权重':>8}{'年化':>10}{'波动':>9}{'夏普':>8}{'最大回撤':>10}{'月胜率':>9}{'累计':>12}")
    best = None
    for w in [float(x) for x in args.weights.split(",") if x.strip()]:
        r = [w * a + (1 - w) * b for a, b in zip(eq, bd)]
        s = stats(r)
        flag = ""
        if best is None or s["sharpe"] > best[1]:
            best = (w, s["sharpe"])
        print(f"  {w:>8.2f}{s['ann'] * 100:>9.1f}%{s['vol'] * 100:>8.1f}%{s['sharpe']:>8.2f}"
              f"{s['maxdd'] * 100:>9.1f}%{s['month_win'] * 100:>8.1f}%{s['total'] * 100:>11.0f}%{flag}")

    # HRP / 风险平价（按波动倒数分配）
    inv = 1.0 / max(1e-9, s_eq["vol"]) + 1.0 / max(1e-9, s_bd["vol"])
    w_hrp = (1.0 / max(1e-9, s_eq["vol"])) / inv
    r_hrp = [w_hrp * a + (1 - w_hrp) * b for a, b in zip(eq, bd)]
    s_hrp = stats(r_hrp)
    print(f"\n风险平价（按波动倒数，微盘 {w_hrp * 100:.0f}% / 债券 {(1 - w_hrp) * 100:.0f}%）："
          f"年化 {s_hrp['ann'] * 100:+.1f}% 波动 {s_hrp['vol'] * 100:.1f}% 夏普 {s_hrp['sharpe']:.2f} "
          f"回撤 {s_hrp['maxdd'] * 100:.1f}%")

    # 最大夏普网格
    grid = []
    for w in np.arange(0, 1.0001, 0.02):
        r = list(w * np.array(eq) + (1 - w) * np.array(bd))
        s = stats(r)
        grid.append((float(w), s))
    best_w, best_s = max(grid, key=lambda kv: kv[1]["sharpe"])
    print(f"最大夏普权重（网格 2% 步长）：微盘 {best_w * 100:.0f}% / 债券 {(1 - best_w) * 100:.0f}% → "
          f"年化 {best_s['ann'] * 100:+.1f}% 夏普 {best_s['sharpe']:.2f} 回撤 {best_s['maxdd'] * 100:.1f}%")
    if best is not None:
        print(f"（固定档位里夏普最高的是 微盘 {best[0] * 100:.0f}%，夏普 {best[1]:.2f}）")


if __name__ == "__main__":
    main()
