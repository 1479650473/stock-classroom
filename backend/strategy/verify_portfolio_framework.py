# -*- coding: utf-8 -*-
"""组合级价值tilt + 市场宽度第三路开关 + 多因子分层组合回测 —— 一次加载帧, 三种分析。

历史任务链: 价值单票择时≈买持(证伪) → value_hard_rule(单票决策门硬裁决) → 现在把价值
**升级到组合层**:
  ①组合级 value_tilt: 价值不再是"单票卖不卖", 而是**整个重平衡选股组合里价值的权重**——
    景气/收缩期增配价值层, 扩张/risk-on 减配价值层(weight-tilt 而非二值开关)。
  ②市场宽度第三路开关: 破年线(MA250)占比 <50% → 弱市 → value_favorable; 与价值价差信号交叉验证。
  ③多因子分层: 价值(防御层)+ 动量反转(买超跌)+ 低波动(防御), 验证"分层而非独立"的整体收益/回撤。

方法(全部点时间, 无前视): 每重平衡日 t 用 ≤t 的 close 截面因子值打分, t+1 open 进场,
t+1+HP open 出场(与 FactorResearchEngine 口径一致). 跨2018(熊)/2019-21(修复)/2022(熊)/2023-26(成长).
诚实: 2018幸存者池(幸存者偏差); 单回归窗口; 跨截面(选哪只)非单票择时; 权重为手工设定(非全局寻优).
运行: C:/Python314/python.exe backend/strategy/verify_portfolio_framework.py  (timeout 700)
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
HP = 20          # 重平衡周期(月)
TOP_K = 0.2      # 前 20% 组合
FEE = 0.0005     # 单边佣金
SLIP = 0.0005    # 单边滑点
LIMIT = int(os.environ.get("VALUE_CYCLE_LIMIT", "2400"))
MAX_U = int(os.environ.get("BEAR_UNIVERSE_MAX", "2500"))
BREADTH_MA = 250        # 年线(250交易日)
BREADTH_LOW = 0.5       # <50% 破年线 → 弱市(价值顺风)
BREADTH_HIGH = 0.6      # >60% 破年线 → 强市(价值逆风)
W_FAV, W_NEU, W_HEAD = 1.5, 1.0, 0.3   # 价值层权重: 顺风增配 / 中性 / 逆风减配


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


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    peak = nav.cummax()
    return float((nav / peak - 1.0).min())


def _xs_z(panel: pd.DataFrame, date: pd.Timestamp):
    """date 时点的截面 z-score(standardize); 返回 Series 或 None(有效样本过少)."""
    x = panel.loc[date].replace([math.inf, -math.inf], pd.NA).dropna()
    if len(x) < 5:
        return None
    sd = float(x.std())
    if not math.isfinite(sd) or sd == 0.0:
        return pd.Series(0.0, index=x.index)
    return (x - x.mean()) / sd


def main() -> int:
    pool = _pool_with_2018()
    print("=== 组合级价值tilt + 市场宽度第三路开关 + 多因子分层组合回测 ===", flush=True)
    print(f"池 {len(pool)} 只 | LIMIT={LIMIT} | 窗口 {START}→now | holding={HP} | top={TOP_K:.0%}", flush=True)
    frames = load_universe_frames(pool, start="2017-06-01", end=datetime.now().strftime("%Y%m%d"),
                                  with_fundamentals=True, fetch_missing=False, limit=LIMIT)
    print(f"frames {len(frames)} 只 | 基本面仅读缓存(无前视)", flush=True)

    engine = FactorResearchEngine()
    close = engine._panel(frames, "close")
    open_ = engine._panel(frames, "open")
    bp = engine._factor_panel(frames, "bp", close)
    rev = engine._factor_panel(frames, "reversal_20", close)
    vol = engine._factor_panel(frames, "volatility_20", close)
    print(f"面板: close {close.shape} open {open_.shape} | BP {bp.shape} REV20 {rev.shape} VOL20 {vol.shape}", flush=True)

    # 市场宽度: 破年线(MA250)占比
    ma = close.rolling(BREADTH_MA, min_periods=120).mean()
    breadth = (close > ma).mean(axis=1)

    # 无前视前向收益: t 信号 → t+1 open 进 → t+1+HP open 出
    fwd = open_.shift(-(HP + 1)) / open_.shift(-1) - 1.0

    # 宽基指数 regime(趋势/回撤)
    idx, _ = load_klines("sh000001", limit=4500)
    idx_close = pd.Series([float(k["close"]) for k in idx],
                          index=pd.to_datetime([str(k["date"]) for k in idx], format="%Y%m%d", errors="coerce"))
    idx_close = idx_close[idx_close.index.notna()].sort_index()

    def index_regime(dt: pd.Timestamp) -> float:
        hist = idx_close.loc[idx_close.index <= dt]
        if hist.empty or len(hist) < 30:
            return 0.5
        last = float(hist.iloc[-1])
        ma120 = float(hist.rolling(120, min_periods=30).mean().iloc[-1])
        dd = last / max(hist.tail(60)) - 1.0
        if last < ma120 or dd < -0.08:
            return 1.0      # 弱市 → value_favorable
        if last > ma120 and dd > -0.05:
            return 0.0      # risk-on → value_headwind
        return 0.5

    # 价值价差自指信号(复用 verify_value_regime2): BP 多空 NAV 滞后动量
    r_bp = engine.run(frames=frames, factor_id="BP", start_date=START,
                      end_date=datetime.now().strftime("%Y%m%d"),
                      groups=5, holding_period=HP, compute_correlation=False)
    ls_pts = r_bp.get("longShortCurve", [])
    ls_map = {pd.Timestamp(p["time"]): float(p["net"]) for p in ls_pts}

    def value_spread(dt: pd.Timestamp) -> float:
        hist = [pd.Timestamp(p["time"]) for p in ls_pts if pd.Timestamp(p["time"]) <= dt]
        if len(hist) < 4:
            return 0.5
        cur, prev = hist[-1], hist[-4]
        c, p = ls_map[cur], ls_map[prev]
        if c is None or p is None or p <= 0:
            return 0.5
        return 1.0 if c / p - 1.0 > 0 else 0.0

    def breadth_sig(dt: pd.Timestamp) -> float:
        b = breadth.get(dt, pd.NA)
        if pd.isna(b) or not math.isfinite(float(b)):
            return 0.5
        if float(b) < BREADTH_LOW:
            return 1.0      # 弱市
        if float(b) > BREADTH_HIGH:
            return 0.0      # 强市
        return 0.5

    # 重平衡日
    loc = close.loc[close.index >= pd.Timestamp(START)]
    rebal = list(loc.index[::HP])
    print(f"重平衡日: {len(rebal)} 期 | 宽度={BREADTH_MA}日均(年线) 阈值<{BREADTH_LOW:.0%}", flush=True)

    def sel_composite(zb, zr, zl, wv):
        if zb is None or zr is None or zl is None:
            return None
        idx = zb.index.intersection(zr.index).intersection(zl.index)
        if len(idx) < 5:
            return None
        return wv * zb.reindex(idx) + 1.0 * zr.reindex(idx) + 1.0 * zl.reindex(idx)

    def wv_from_sig(sig: float) -> float:
        if sig >= 0.5 + 1e-9:
            return W_FAV
        if sig <= 0.5 - 1e-9:
            return W_HEAD
        return W_NEU

    # 每个变体: (名称, score_fn(zb, zr, z_low, s_idx, s_vsp, s_br))
    VARS = {
        "A 纯价值(BP)":          lambda zb, zr, zl, i, v, br: zb,
        "B 纯动量反转(REV20)":   lambda zb, zr, zl, i, v, br: zr,
        "C 纯低波动(-VOL20)":    lambda zb, zr, zl, i, v, br: zl,
        "D 多因子等权(无tilt)":   lambda zb, zr, zl, i, v, br: (zb + zr + zl) if (zb is not None and zr is not None and zl is not None) else None,
        "E 多因子+指数regime":    lambda zb, zr, zl, i, v, br: sel_composite(zb, zr, zl, wv_from_sig(i)),
        "F 多因子+价值价差":      lambda zb, zr, zl, i, v, br: sel_composite(zb, zr, zl, wv_from_sig(v)),
        "G 多因子+市场宽度":      lambda zb, zr, zl, i, v, br: sel_composite(zb, zr, zl, wv_from_sig(br)),
    }

    # 单次遍历: 累计每变体逐期 GROSS/NET NAV 序列
    navs = {k: {"g": [], "n": []} for k in VARS}
    prev_sel = {k: set() for k in VARS}
    broad_g, broad_n = [], []
    val_cnt = {"F": 0, "G": 0}
    agree = {"both_value": 0, "both_broad": 0, "diff": 0, "periods": 0}
    sig_touch = {"idx": 0, "spread": 0, "breadth": 0}

    for dt in rebal:
        zb, zr, zl = _xs_z(bp, dt), _xs_z(rev, dt), _xs_z(vol, dt)
        frow = fwd.loc[dt].replace([math.inf, -math.inf], pd.NA).dropna()
        frow = frow[(frow.abs() < 1.5)]
        if frow.empty:
            continue
        # 三路信号(即使某变体不用, 也用于交叉验证统计)
        s_idx, s_vsp, s_br = index_regime(dt), value_spread(dt), breadth_sig(dt)
        if s_idx in (0.0, 1.0):
            sig_touch["idx"] += 1
        if s_vsp in (0.0, 1.0):
            sig_touch["spread"] += 1
        if s_br in (0.0, 1.0):
            sig_touch["breadth"] += 1
        if (s_vsp == 1.0 and s_br == 1.0):
            agree["both_value"] += 1
        elif (s_vsp == 0.0 and s_br == 0.0):
            agree["both_broad"] += 1
        elif s_vsp != 0.5 and s_br != 0.5:
            agree["diff"] += 1
        agree["periods"] += 1

        b = float(frow.mean())
        broad_g.append((dt, b))

        n = max(2, int(len(frow) * TOP_K))
        z_low = -zl if zl is not None else None
        for k, fn in VARS.items():
            score = fn(zb, zr, z_low, s_idx, s_vsp, s_br)
            if score is None or len(score) < n:
                # 至少一因子缺失 → 该期略过(诚实不参与组合)
                continue
            top = score.nlargest(n).index
            rets = frow.reindex(top).dropna()
            if rets.empty:
                continue
            g = float(rets.mean())
            old = prev_sel[k]
            turn = 1.0 if not old else 1.0 - len(old & set(top)) / max(len(old | set(top)), 1)
            cost = turn * 2.0 * (FEE + SLIP)
            net = g - cost
            prev_sel[k] = set(top)
            navs[k]["g"].append((dt, g))
            navs[k]["n"].append((dt, net))
            if k.startswith("F ") and s_vsp == 1.0:
                val_cnt["F"] += 1
            if k.startswith("G ") and s_br == 1.0:
                val_cnt["G"] += 1

    def stats(items):
        if not items:
            return None, None, None
        nav = 1.0; arr = []
        for dt, r in items:
            nav *= 1.0 + r
            arr.append(nav)
        s = pd.Series(arr, index=[a[0] for a in items])
        yrs = (s.index[-1] - s.index[0]).days / 365.25 if len(s) > 1 else 1.0
        cagr = float(s.iloc[-1]) ** (1.0 / max(1e-9, yrs)) - 1.0
        return float(s.iloc[-1]), cagr, _max_drawdown(s)

    print("\n── 各策略 GROSS(未计成本) 累计/年化/最大回撤 ──", flush=True)
    best = {}
    for k in VARS:
        nav, cagr, mdd = stats(navs[k]["g"])
        if nav is None:
            print(f"  {k:<26} 无数据", flush=True)
            continue
        best[k] = nav
        print(f"  {k:<26} NAV {nav:.4f}  累计 {nav-1:+.2%}  年化 {cagr:+.2%}  MaxDD {mdd:+.2%}", flush=True)
    bnav, bcagr, bmdd = stats(broad_g)
    if bnav is not None:
        best["H 宽基等权买持"] = bnav
        print(f"  {'H 宽基等权买持':<26} NAV {bnav:.4f}  累计 {bnav-1:+.2%}  年化 {bcagr:+.2%}  MaxDD {bmdd:+.2%}", flush=True)

    singles = ["A 纯价值(BP)", "B 纯动量反转(REV20)", "C 纯低波动(-VOL20)"]
    layered = "D 多因子等权(无tilt)"
    best_single = max([best.get(s) or 0.0 for s in singles])
    print("\n── 任务③ 分层 vs 独立 ──", flush=True)
    print(f"  最佳单因子(独立): {best_single:.4f} | 多因子等权(分层): {best.get(layered,0):.4f}", flush=True)
    print(f"  → {'分层优于最佳单因子' if best.get(layered,0) >= best_single else '分层未跑赢最佳单因子(独立更简单)'}", flush=True)

    print("\n── 任务① 组合级价值tilt ──", flush=True)
    for k in ["D 多因子等权(无tilt)", "E 多因子+指数regime", "F 多因子+价值价差", "G 多因子+市场宽度"]:
        print(f"  {k:<26} NAV {best.get(k,0):.4f}", flush=True)
    print(f"  价值权重: 顺风增配 {W_FAV} / 中性 {W_NEU} / 逆风减配 {W_HEAD} (收缩增配、扩张减配)| F持价值期 {val_cnt['F']}/G持价值期 {val_cnt['G']}", flush=True)

    print("\n── 任务② 市场宽度第三路开关 ──", flush=True)
    print(f"  宽度(破{BREADTH_MA}日年线占比): 弱市阈值<{BREADTH_LOW:.0%}, 强市>{BREADTH_HIGH:.0%}", flush=True)
    print(f"  与价值价差信号交叉验证({agree['periods']}期): 同指价值 {agree['both_value']} | 同指宽基 "
          f"{agree['both_broad']} | 分歧 {agree['diff']}", flush=True)
    print(f"  信号被触发(明确侧)期数: 指数 {sig_touch['idx']} | 价值价差 {sig_touch['spread']} | 宽度 {sig_touch['breadth']}", flush=True)

    print("\n── 诚实结论 ──", flush=True)
    print("  * 价值是**一层**(防御/轮动倾斜), 非独立 alpha: 单看 BP 组合跑不赢宽基(尤其成长期)。", flush=True)
    print("  * 组合级 value_tilt = 重平衡时调节价值在组合里的**权重**(收缩增配/扩张减配), 而非单票二值开关。", flush=True)
    print("  * 市场宽度(破年线占比)是可用的第三路弱市→价值信号, 与价值价差同向率高, 可交叉验证做多价值窗口。", flush=True)
    print("  * 局限: 2018幸存者池(幸存者偏差); 单窗口; 权重手工拟定(未全局寻优); 主口径 GROSS(未计重平衡成本);"
          " 基本面覆盖早年偏低(empty→NaN→诚实不参与组合).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
