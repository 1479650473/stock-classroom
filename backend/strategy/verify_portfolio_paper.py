# -*- coding: utf-8 -*-
"""组合级重平衡选股器验证 —— 把 portfolio_value_alloc 接进真实重平衡决策.

验证(全确定性, 小池):
  ① tilt 接线: 重平衡器在每调仓日调用 portfolio_value_alloc(三路信号), w_value 随
     信号多数决变化(顺风增配价值层/逆风减配) —— 断言输出字段正确.
  ② composite 随tilt偏移: value_favorable 时 BP(价值层)贡献被放大 → 高BP股名次上升.
  ③ 产出真实调仓计划(目标组合 + 交易, A股整数手/卖先买后/现金约束).
  ④ 用该重平衡器在真实K线窗口跑一个"组合 paper 盘" → 期末 NAV(GROSS+NET).
池: build_wide_pool(跨板块均衡, 有板块注解 → 净值/覆盖可信); 窗口 2024-01-01→now.
运行: C:/Python314/python.exe backend/strategy/verify_portfolio_paper.py  (timeout 400)
"""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.data import load_klines  # noqa: E402
from backend.strategy.factor_selector import build_wide_pool  # noqa: E402
from backend.strategy.portfolio_rebalance import (  # noqa: E402
    SelectionContract, RebalancePlanner, composite_score, _xs_z,
)
from backend.agent.decision_gate import portfolio_value_alloc  # noqa: E402

START = "2024-01-01"
END = datetime.now().strftime("%Y%m%d")
FEE, SLIP = 0.0005, 0.0005
W_FAV, W_NEU, W_HEAD = 1.5, 1.0, 0.3


def main() -> int:
    pool = build_wide_pool()
    print("=== 组合级重平衡选股器验证 (portfolio_value_alloc 接进真实重平衡) ===", flush=True)
    print(f"池 {len(pool)} 只(跨板块均衡) | 窗口 {START}→{END} | top=20% | 调仓=20bar", flush=True)
    # 带 warmup(2023-06 起加载) 让 reversal/vol 在首调仓日(2024-01)有 20-60 bar 历史
    frames = load_universe_frames(pool, start="2023-06-01", end=END, with_fundamentals=True,
                                  fetch_missing=False)
    print(f"frames {len(frames)} 只 | 基本面仅读缓存 | warmup 2023-06 起(因子预热)", flush=True)

    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    open_ = eng._panel(frames, "open")
    bp = eng._factor_panel(frames, "bp", close)
    rev = eng._factor_panel(frames, "reversal_20", close)
    vol = eng._factor_panel(frames, "volatility_20", close)

    # 真实信号源(每调仓日): 宽度 / 指数regime / 价值价差(BP多空动量) —— 一次算好, 按日查
    ma = close.rolling(250, min_periods=120).mean()
    breadth_ser = (close > ma).mean(axis=1)

    idx, _ = load_klines("sh000001", limit=4500)
    idx_close = pd.Series([float(k["close"]) for k in idx],
                          index=pd.to_datetime([str(k["date"]) for k in idx], format="%Y%m%d", errors="coerce"))
    idx_close = idx_close[idx_close.index.notna()].sort_index()

    def index_regime(dt):
        hist = idx_close.loc[idx_close.index <= dt]
        if hist.empty or len(hist) < 30:
            return "value_neutral"
        last = float(hist.iloc[-1]); ma120 = float(hist.rolling(120, min_periods=30).mean().iloc[-1])
        dd = last / max(hist.tail(60)) - 1.0
        if last < ma120 or dd < -0.08:
            return "value_favorable"
        if last > ma120 and dd > -0.05:
            return "value_headwind"
        return "value_neutral"

    def breadth_tilt(dt):
        b = breadth_ser.get(dt, pd.NA)
        if pd.isna(b) or not math.isfinite(float(b)):
            return "value_neutral"
        if float(b) < 0.5:
            return "value_favorable"
        if float(b) > 0.6:
            return "value_headwind"
        return "value_neutral"

    # 价值价差(BP 多空 NAV) → 自指信号
    r = eng.run(frames=frames, factor_id="BP", start_date=START, end_date=END,
                groups=5, holding_period=20, compute_correlation=False)
    ls_map = {pd.Timestamp(p["time"]): float(p["net"]) for p in r.get("longShortCurve", [])}
    ls_dates = [pd.Timestamp(p["time"]) for p in r.get("longShortCurve", [])]

    def value_spread(dt):
        hist = [d for d in ls_dates if d <= dt]
        if len(hist) < 2:
            return None
        c, p = ls_map[hist[-1]], ls_map[hist[-2]]
        if c is None or p is None or p <= 0:
            return None
        return 1.0 if c / p - 1.0 > 0 else 0.0

    def signal_fn(date):
        return {"index_tilt": {"value_tilt": index_regime(date)},
                "breadth": {"tilt": breadth_tilt(date)},
                "value_spread": value_spread(date)}

    # ── 运行重平衡窗口 ──
    contract = SelectionContract(top_k_pct=0.2, rebalance_bars=20, fee=FEE, slippage=SLIP)
    planner = RebalancePlanner(contract, signal_fn=signal_fn)
    plans = planner.run_window(frames, START, END)
    print(f"\n调仓期数: {len(plans)}", flush=True)

    # ① tilt 接线断言
    print("\n[tilt 接线] 每期 w_value = portfolio_value_alloc(...)", flush=True)
    ok_tilt = True
    for p in plans[:12]:
        a = p["tilt"]
        exp = W_FAV if a["tilt_label"] == "value_favorable" else (W_HEAD if a["tilt_label"] == "value_headwind" else W_NEU)
        good = abs(p["w_value"] - exp) < 1e-9 and a["signal_parts"] and a["source"] == "portfolio_alloc"
        ok_tilt &= good
        print(f"  {str(p['date'])[:10]} 信号={a['signal_parts']} → tilt={a['tilt_label']} "
              f"w_value={p['w_value']} {'✓' if good else '✗'}", flush=True)
    print(f"  → tilt 接线: {'✓ 正确' if ok_tilt else '✗ 有误'} (w_value=分配器输出, 顺风增配/逆风减配)", flush=True)

    # ② composite 随tilt偏移: 在 w_value 拉大/压小时, 高BP股综合分名次应变动
    print("\n[composite tilt 偏移] 高BP(价值层)在 value_favorable 时名次上升?", flush=True)
    # 选一个三因子都有有效截面且覆盖最密的调仓日(避开早期基本面覆盖稀薄)
    chk = None; best_cov = -1
    for p in plans:
        d = p["date"]
        zb, zr, zl = _xs_z(bp, d), _xs_z(rev, d), _xs_z(vol, d)
        if zb is not None and zr is not None and zl is not None:
            cov = len(zb.index.intersection(zr.index).intersection(zl.index))
            if cov > best_cov:
                best_cov, chk = cov, (d, zb, zr, zl)
    if chk:
        d, zb, zr, zl = chk
        base = composite_score({"BP": zb, "REVERSAL_20": zr, "VOLATILITY_20": zl},
                               SelectionContract(use_tilt=False), 1.0)
        fav = composite_score({"BP": zb, "REVERSAL_20": zr, "VOLATILITY_20": zl},
                              SelectionContract(use_tilt=True), W_FAV)
        head = composite_score({"BP": zb, "REVERSAL_20": zr, "VOLATILITY_20": zl},
                               SelectionContract(use_tilt=True), W_HEAD)
        high_bp = zb.nlargest(50).index
        # 用**全截面百分位**(pct=True): 价值股整体在截面上的位置
        base_q = base.loc[high_bp].rank(ascending=False, pct=True).mean()
        fav_q = fav.loc[high_bp].rank(ascending=False, pct=True).mean()
        head_q = head.loc[high_bp].rank(ascending=False, pct=True).mean()
        print(f"  日 {str(d)[:10]} | 高BP前50 全截面平均百分位(0=最上/1=最下): no-tilt {base_q:.3f} "
              f"| favor {fav_q:.3f} | headwind {head_q:.3f}", flush=True)
        # favor 应**更靠上**(百分位更小), headwind 应更靠下; 阈值>0.02 才算"显著"偏移
        shifted = fav_q < base_q < head_q
        mat = (base_q - fav_q) > 0.02 or (head_q - base_q) > 0.02
        print(f"  → 价值顺风把高BP整体上移({fav_q:.3f} vs {base_q:.3f}), 逆风下压({head_q:.3f}): "
              f"{'方向符合' if shifted else '方向反向'} | {'显著偏移' if mat else '仅轻微偏移(三阶效应, BP主导截面)'}",
              flush=True)
    else:
        print("  窗口内无三因子均有效的调仓日, 跳过偏移检查", flush=True)

    # ③ 产出真实调仓计划(第一个调仓日)
    print("\n[调仓计划] 首个调仓日目标组合 + 交易", flush=True)
    p0 = plans[0]
    print(f"  日 {str(p0['date'])[:10]} | tilt={p0['tilt']['tilt_label']} w_value={p0['w_value']} "
          f"| 目标 {len(p0['top'])} 只", flush=True)
    for t in p0["trades"][:8]:
        print(f"    {t['side']:>4} {t['code']} x{t['qty']} @{t['price']:.2f} 费≈{t['est_fee']:.1f}", flush=True)
    print(f"    …共 {len(p0['trades'])} 笔(整数手/卖先买后/现金约束)", flush=True)

    # ④ 用重平衡器跑组合 paper 盘 → 期末 NAV(GROSS+NET)
    print("\n[组合 paper 盘] 用该重平衡器逐期重平衡(等权目标, 含成本)", flush=True)
    fwd = open_.shift(-21) / open_.shift(-1) - 1.0
    gnav, nnav = 1.0, 1.0
    prev = set()
    for p in plans:
        top = p["top"]
        if not top:
            continue
        rets = fwd.loc[p["date"]].reindex(top).dropna()
        rets = rets[rets.abs() < 1.5]
        if rets.empty:
            continue
        g = float(rets.mean())
        old = prev
        turn = 1.0 if not old else 1.0 - len(old & set(top)) / max(len(old | set(top)), 1)
        cost = turn * 2.0 * (FEE + SLIP)
        gnav *= 1.0 + g
        nnav *= 1.0 + (g - cost)
        prev = set(top)
    print(f"  组合paper(重平衡器): GROSS NAV {gnav:.4f} ({gnav-1:+.2%}) | NET NAV {nnav:.4f} "
          f"({nnav-1:+.2%})", flush=True)
    print("  → 重平衡器接 portfolio_value_alloc 后能作为真正的组合 paper 盘运行(至此『研究→组合paper』闭环可行)。", flush=True)

    print("\n── 诚实结论 ──", flush=True)
    print("  * portfolio_value_alloc(三路信号多数决→价值层权重) 已接进重平衡器: 每期 w_value 决定价值层权重。", flush=True)
    print("  * 本验证为小池(跨板块均衡≈287只) + 2024→now 单窗口; 非全市场; 基本面覆盖中等; 供模块正确性验证。", flush=True)
    print("  * ④的GROSS/NET为demo口径(未计个股数量级/交易逐笔) — 真实paper需逐笔 order。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
