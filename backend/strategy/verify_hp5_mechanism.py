# -*- coding: utf-8 -*-
"""HP=5 断点机制研究 —— 确认"短持有(周度重平衡)被击穿"是**纯换手成本**还是**模型本身**。

方法(全部点时间, 无前视, 清理+修"跳过稀疏截面"后的口径, 与 verify_portfolio_optimize 一致):
对 HP∈{5,20} 各跑 分层D / 单因子(价值A、低波动C) 的 GROSS 与 NET, 并给出每期**平均换手率**与**成本拖累**:
  · 若 HP=5 时 D-GROSS 仍 > 最佳单-GROSS(分层模型更优) 但 D-NET < 最佳单-NET → **纯成本击穿**(模型OK, 换手太贵)
  · 若 HP=5 时 D-GROSS 已 < 最佳单-GROSS → **模型本身**(分层逻辑在短持有下就不占优)
额外: 换手率/成本拖累(总成本/总收益) 量化"HP=5 为何贵"。
运行: C:/Python314/python.exe backend/strategy/verify_hp5_mechanism.py  (timeout 700)
"""
from __future__ import annotations

import os
import math
import sqlite3
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.data import get_kline_db_path, load_klines  # noqa: E402
from backend.fundamental import has_vals  # noqa: E402

START = "2018-01-01"
TOP_K = 0.2
FEE, SLIP = 0.0005, 0.0005
LIMIT = int(os.environ.get("VALUE_CYCLE_LIMIT", "2400"))
MAX_U = int(os.environ.get("BEAR_UNIVERSE_MAX", "2500"))


def _pool_with_2018() -> list:
    con = sqlite3.connect(get_kline_db_path(), timeout=30)
    rows = con.execute(
        "SELECT DISTINCT code FROM kline_daily WHERE date<'20180101' AND code IN "
        "(SELECT code FROM kline_daily WHERE date<'20190101' AND date>='20180101') "
        "AND code IN (SELECT code FROM stock_list WHERE status='active') ORDER BY code").fetchall()
    con.close()
    return [r[0] for r in rows if has_vals(r[0])][:MAX_U]


def _xs_z(panel, date):
    x = pd.to_numeric(panel.loc[date], errors="coerce")
    x = x.replace([math.inf, -math.inf], pd.NA).dropna()
    if len(x) < 5:
        return None
    sd = float(x.std())
    if not math.isfinite(sd) or sd == 0.0:
        return pd.Series(0.0, index=x.index)
    return (x - x.mean()) / sd


def main() -> int:
    pool = _pool_with_2018()
    print("=== HP=5 断点机制研究: 纯成本 vs 模型本身 ===", flush=True)
    print(f"池 {len(pool)} 只 | top={TOP_K:.0%} | HP∈{{5,20}} | 口径=清理+修稀疏跳过(与 optimize 一致)", flush=True)
    frames = load_universe_frames(pool, start="2017-06-01", end=datetime.now().strftime("%Y%m%d"),
                                  with_fundamentals=True, fetch_missing=False, limit=LIMIT)
    print(f"frames {len(frames)} 只", flush=True)
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    open_ = eng._panel(frames, "open")
    bp = eng._factor_panel(frames, "bp", close)
    rev = eng._factor_panel(frames, "reversal_20", close)
    vol = eng._factor_panel(frames, "volatility_20", close)

    def run(hp, weights):
        """weights=(w_bp,w_rev,w_low); 返回 (GROSS_NAV, NET_NAV, 平均换手, 每期换手列表)."""
        fwd = open_.shift(-(hp + 1)) / open_.shift(-1) - 1.0
        loc = close.loc[close.index >= pd.Timestamp(START)]
        rebal = list(loc.index[::hp])
        gw, nw, turns = 1.0, 1.0, []
        prev = set()
        for dt in rebal:
            zb, zr, zl = _xs_z(bp, dt), _xs_z(rev, dt), _xs_z(vol, dt)
            frow = fwd.loc[dt].replace([math.inf, -math.inf], pd.NA).dropna()
            frow = frow[(frow.abs() < 1.5)]
            if frow.empty or zb is None or zr is None or zl is None:
                continue
            z_low = -zl
            n = max(2, int(len(frow) * TOP_K))
            score = weights[0] * zb + weights[1] * zr + weights[2] * z_low
            score = pd.to_numeric(score, errors="coerce").dropna()
            k = min(n, len(score))
            if k < 2:
                continue
            top = score.nlargest(k).index
            rets = frow.reindex(top).dropna()
            if rets.empty:
                continue
            g = float(rets.mean())
            turn = 1.0 if not prev else 1.0 - len(prev & set(top)) / max(len(prev | set(top)), 1)
            cost = turn * 2.0 * (FEE + SLIP)
            gw *= 1.0 + g
            nw *= 1.0 + (g - cost)
            turns.append(turn)
            prev = set(top)
        return gw, nw, (sum(turns) / len(turns) if turns else 0.0), turns

    def fmt(x): return f"{x:.4f}"

    print("\n── 各 HP 的 GROSS vs NET + 换手/成本拖累 ──", flush=True)
    print("  HP  策略        GROSS   NET    GROSS-NET  平均换手  成本拖累(总成本/总收益)", flush=True)
    for hp in (5, 20):
        d_g, d_n, d_t, _ = run(hp, (1.0, 1.0, 1.0))
        a_g, a_n, a_t, _ = run(hp, (1.0, 0.0, 0.0))
        c_g, c_n, c_t, _ = run(hp, (0.0, 0.0, 1.0))
        best_gross = max(a_g, c_g)
        best_net = max(a_n, c_n)
        drag = ((d_g - 1.0) - (d_n - 1.0)) / (d_g - 1.0) if d_g != 1 else 0.0
        print(f"  {hp:<3} 分层D     {d_g:>8.4f} {d_n:>8.4f}   {d_g-d_n:>8.4f}   {d_t:.3f}   {drag:+.2%}", flush=True)
        print(f"     价值A     {a_g:>8.4f} {a_n:>8.4f}   {a_g-a_n:>8.4f}   {a_t:.3f}", flush=True)
        print(f"     低波动C   {c_g:>8.4f} {c_n:>8.4f}   {c_g-c_n:>8.4f}   {c_t:.3f}", flush=True)
        print(f"     最佳单    {best_gross:>8.4f} {best_net:>8.4f}", flush=True)
        verdict_g = "模型占优(GROSS分层>最佳单)" if d_g >= best_gross else "模型不占优(GROSS分层<最佳单)"
        verdict_n = "成本击穿(净分层<最佳单)" if d_n < best_net else "净分层仍优"
        print(f"     → GROSS: {verdict_g} | NET: {verdict_n}", flush=True)

    print("\n── 诚实判定 ──", flush=True)
    print("  * 关键判据: HP=5 时 GROSS 分层是否仍>最佳单? YES→纯成本(模型OK,换手太贵); NO→模型本身(短持有不占优).", flush=True)
    print("  * 成本拖累 = 总换手成本/(GROSS-1); HP=5 平均换手 vs HP=20 平均换手 定『贵多少』。", flush=True)
    print("  * 局限: 2018幸存池(幸存者偏差); 单窗口; 换手为相邻调仓集合交并≈近似; 单边成本 佣金0.0005+滑点0.0005。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
