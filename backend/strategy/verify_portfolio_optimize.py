# -*- coding: utf-8 -*-
"""组合级价值tilt —— NET(计成本) + 全局寻优权重 + 多窗口稳健性。

延续 verify_portfolio_framework: 价值升级为组合层(权重tilt)。本脚本回答三个问题:
  ① 分层/tilt 优势在**计重平衡成本(NET)**后是否保留? (原框架只报 GROSS)
  ② **全局寻优权重**(而非手工 1.5/1.0/0.3), 并做**训练/验证分离**防过拟合(诚实):
     在训练窗(2018-2022)选最优权重 → 在验证窗(2023-now)评估, 与"直接在验证窗寻优"的上界对比。
  ③ **多窗口稳健性**(holding=5/20/40/60): 分层(z(BP)+z(REV20)-z(VOL20)) > 最佳单因子 > 买持
     ——结论是否跨持有期稳定?

方法(全部点时间, 无前视): 每重平衡日 t 用≤t 的 close 截面因子值打分(z-score), t+1 open 进,
t+1+HP open 出; NET 含换手成本(turnover*2*(佣金+滑点)). 2018-幸存池(2500只, 幸存者偏差).
优化是基于**单一样本内**的, 用训练/验证分离暴露过拟合(训练最优在验证窗的相对表现).
运行: C:/Python314/python.exe backend/strategy/verify_portfolio_optimize.py  (timeout 700)
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
TRAIN_END = "2022-12-31"
TOP_K = 0.2
FEE = 0.0005
SLIP = 0.0005
LIMIT = int(os.environ.get("VALUE_CYCLE_LIMIT", "2400"))
MAX_U = int(os.environ.get("BEAR_UNIVERSE_MAX", "2500"))
BREADTH_MA = 250
BREADTH_LOW, BREADTH_HIGH = 0.5, 0.6


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


def _xs_z(panel, date):
    x = pd.to_numeric(panel.loc[date], errors="coerce")
    x = x.replace([math.inf, -math.inf], pd.NA).dropna()
    if len(x) < 5:
        return None
    sd = float(x.std())
    if not math.isfinite(sd) or sd == 0.0:
        return pd.Series(0.0, index=x.index)
    return (x - x.mean()) / sd


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    return float((nav / nav.cummax() - 1.0).min())


def _sharpe(nav: pd.Series, hp: int) -> float:
    if len(nav) < 3:
        return 0.0
    rets = nav / nav.shift(1) - 1.0
    rets = rets.dropna()
    sd = float(rets.std())
    if sd == 0.0 or not math.isfinite(sd):
        return 0.0
    return float(rets.mean()) / sd * math.sqrt(252.0 / hp)


def main() -> int:
    pool = _pool_with_2018()
    print("=== 组合级价值tilt: NET + 全局寻优权重 + 多窗口稳健性 ===", flush=True)
    print(f"池 {len(pool)} 只 | LIMIT={LIMIT} | 窗口 {START}→now | top={TOP_K:.0%} | "
          f"TP={TRAIN_END} 训练/ {START} 后 验证", flush=True)
    frames = load_universe_frames(pool, start="2017-06-01", end=datetime.now().strftime("%Y%m%d"),
                                  with_fundamentals=True, fetch_missing=False, limit=LIMIT)
    print(f"frames {len(frames)} 只 | 基本面仅读缓存", flush=True)

    engine = FactorResearchEngine()
    close = engine._panel(frames, "close")
    open_ = engine._panel(frames, "open")
    bp = engine._factor_panel(frames, "bp", close)
    rev = engine._factor_panel(frames, "reversal_20", close)
    vol = engine._factor_panel(frames, "volatility_20", close)

    ma = close.rolling(BREADTH_MA, min_periods=120).mean()
    breadth = (close > ma).mean(axis=1)

    idx, _ = load_klines("sh000001", limit=4500)
    idx_close = pd.Series([float(k["close"]) for k in idx],
                          index=pd.to_datetime([str(k["date"]) for k in idx], format="%Y%m%d", errors="coerce"))
    idx_close = idx_close[idx_close.index.notna()].sort_index()

    def index_regime(dt):
        hist = idx_close.loc[idx_close.index <= dt]
        if hist.empty or len(hist) < 30:
            return 0.5
        last = float(hist.iloc[-1]); ma120 = float(hist.rolling(120, min_periods=30).mean().iloc[-1])
        dd = last / max(hist.tail(60)) - 1.0
        if last < ma120 or dd < -0.08:
            return 1.0
        if last > ma120 and dd > -0.05:
            return 0.0
        return 0.5

    def breadth_sig(dt):
        b = breadth.get(dt, pd.NA)
        if pd.isna(b) or not math.isfinite(float(b)):
            return 0.5
        if float(b) < BREADTH_LOW:
            return 1.0
        if float(b) > BREADTH_HIGH:
            return 0.0
        return 0.5

    def build_episodes(hp, start, end):
        """每重平衡日的截面快照(缓存每期 z / frow / 信号), 供多配置复用."""
        fwd = open_.shift(-(hp + 1)) / open_.shift(-1) - 1.0
        r = engine.run(frames=frames, factor_id="BP", start_date=start, end_date=end,
                       groups=5, holding_period=hp, compute_correlation=False)
        ls_map = {pd.Timestamp(p["time"]): float(p["net"]) for p in r.get("longShortCurve", [])}
        ls_dates = [pd.Timestamp(p["time"]) for p in r.get("longShortCurve", [])]

        def vsp(dt):
            hist = [d for d in ls_dates if d <= dt]
            if len(hist) < 4:
                return 0.5
            c, p = ls_map[hist[-1]], ls_map[hist[-4]]
            if c is None or p is None or p <= 0:
                return 0.5
            return 1.0 if c / p - 1.0 > 0 else 0.0

        loc = close.loc[close.index >= pd.Timestamp(start)]
        rebal = [d for d in loc.index[::hp] if d <= pd.Timestamp(end)]
        eps = []
        for dt in rebal:
            zb, zr, zl = _xs_z(bp, dt), _xs_z(rev, dt), _xs_z(vol, dt)
            frow = fwd.loc[dt].replace([math.inf, -math.inf], pd.NA).dropna()
            frow = frow[frow.abs() < 1.5]
            if frow.empty or zb is None or zr is None or zl is None:
                continue
            z_low = -zl
            eps.append({"dt": dt, "zb": zb, "zr": zr, "z_low": z_low,
                        "frow": frow, "n": max(2, int(len(frow) * TOP_K)),
                        "s_idx": index_regime(dt), "s_vsp": vsp(dt), "s_br": breadth_sig(dt)})
        return eps

    def sim(eps, w_bp=1.0, w_rev=1.0, w_low=1.0, wv_fav=1.5, wv_neu=1.0, wv_head=0.3, use_tilt=False):
        """在每个 ep 上按权重+可选tilt打分选 top-K, 返回 GROSS/NET NAV 序列."""
        states = {"g": [], "n": []}
        prev = set()
        for e in eps:
            base = w_bp * e["zb"] + w_rev * e["zr"] + w_low * e["z_low"]
            if use_tilt:
                s = e["s_vsp"]           # 用价值价差自指作tilt驱动(任务②结论最优)
                wv = wv_fav if s == 1.0 else (wv_head if s == 0.0 else wv_neu)
                base = wv * w_bp * e["zb"] + w_rev * e["zr"] + w_low * e["z_low"]
            score = base
            if score is None or not isinstance(score, pd.Series) or len(score) < 2:
                continue
            score = pd.to_numeric(score, errors="coerce").dropna()
            if len(score) < 2:
                continue
            k = min(e["n"], len(score))     # 不复用了"跳过稀疏截面"——与框架/回测一致(n不足取全部)
            top = score.nlargest(k).index
            rets = e["frow"].reindex(top).dropna()
            if rets.empty:
                continue
            g = float(rets.mean())
            old = prev; turn = 1.0 if not old else 1.0 - len(old & set(top)) / max(len(old | set(top)), 1)
            cost = turn * 2.0 * (FEE + SLIP)
            net = g - cost
            prev = set(top)
            states["g"].append((e["dt"], g)); states["n"].append((e["dt"], net))
        def navof(items):
            nav = 1.0; arr = []
            for dt, r in items:
                nav *= 1.0 + r; arr.append(nav)
            idx = pd.DatetimeIndex([x[0] for x in items])
            return pd.Series(arr, index=idx)
        return {"g": navof(states["g"]), "n": navof(states["n"])}

    def rep(title, nv, hp):
        nn = float(nv["n"].iloc[-1]) if len(nv["n"]) else 1.0
        print(f"  {title:<30} GROSS {float(nv['g'].iloc[-1]):.4f}  NET {nn:.4f} "
              f"NET-cum {nn-1:+.2%}  NET-Sharpe {_sharpe(nv['n'],hp):+.2f}  MaxDD-n {_max_drawdown(nv['n']):+.2%}",
              flush=True)
        return nn

    # ── 任务①a: 标准变体 NET(成本后) ──
    print("\n── 任务①a NET(计换手成本, hp=20) ──", flush=True)
    eps20 = build_episodes(20, START, datetime.now().strftime("%Y%m%d"))
    print(f"  hp=20 rebalance期数: {len(eps20)}", flush=True)
    variants = {"A 纯价值(BP)": (1.0, 0.0, 0.0), "B 纯反转(REV20)": (0.0, 1.0, 0.0),
                "C 纯低波动(-VOL)": (0.0, 0.0, 1.0), "D 多因子等权": (1.0, 1.0, 1.0)}
    net_map = {}
    for k, w in variants.items():
        nv = sim(eps20, *w)
        net_map[k] = rep(k, nv, 20)
    nv_eq = sim(eps20, 1.0, 1.0, 1.0, use_tilt=True)
    net_map["F 多因子+价值价差tilt"] = rep("F 多因子+价值价差tilt(1.5/1.0/0.3)", nv_eq, 20)
    base_single = max(net_map["A 纯价值(BP)"], net_map["B 纯反转(REV20)"], net_map["C 纯低波动(-VOL)"])
    layered_net = net_map["D 多因子等权"]
    print(f"  → NET: 多因子分层 {layered_net:.4f} vs 最佳单因子 {base_single:.4f} → "
          f"{'分层仍优(成本后优势保留)' if layered_net >= base_single else '分层被成本侵蚀(独立更省)'}", flush=True)
    print(f"  → NET: 价值价差tilt {net_map['F 多因子+价值价差tilt']:.4f} vs 无tilt分层 {layered_net:.4f} → "
          f"{'tilt成本后仍增配价值' if net_map['F 多因子+价值价差tilt'] >= layered_net else 'tilt被成本侵蚀'}", flush=True)

    # ── 任务③: 多窗口稳健性(分层 vs 单 vs 买持, 无tilt) ──
    print("\n── 任务③ 多窗口稳健性 holding ∈ {5,20,40,60} (无tilt, NET) ──", flush=True)
    print("  HP    A价值    B反转   C低波动    D分层    最佳单    买持     判定(D>=最佳单)", flush=True)
    for hp in (5, 20, 40, 60):
        eps = build_episodes(hp, START, datetime.now().strftime("%Y%m%d"))
        if not eps:
            continue
        navs = {}
        for k, w in {"A": (1.0, 0.0, 0.0), "B": (0.0, 1.0, 0.0), "C": (0.0, 0.0, 1.0),
                     "D": (1.0, 1.0, 1.0)}.items():
            navs[k] = sim(eps, *w)["n"]
        # 买持(宽基等权每期收益)
        broad_net = 1.0
        for e in eps:
            broad_net *= 1.0 + float(e["frow"].mean())
        a = float(navs["A"].iloc[-1]); b = float(navs["B"].iloc[-1]); c = float(navs["C"].iloc[-1]); d = float(navs["D"].iloc[-1])
        best = max(a, b, c); verdict = "分层优✅" if d >= best else "单因优❌"
        print(f"  {hp:<4} {a:6.3f} {b:8.3f} {c:8.3f} {d:8.3f}   {best:8.3f}  {broad_net:8.3f}   {verdict}", flush=True)

    # ── 任务①b: 全局寻优权重 + 训练/验证分离 ──
    print("\n── 任务①b 全局寻优权重(训练2018-2022 → 验证2023-now) ──", flush=True)
    eps_tr = build_episodes(20, START, TRAIN_END)
    eps_te = build_episodes(20, "2023-01-01", datetime.now().strftime("%Y%m%d"))
    print(f"  训练期数 {len(eps_tr)} | 验证期数 {len(eps_te)}", flush=True)
    # 权重网格(因子mix: bp/rev/low ∈ {0.5,1.0,1.5}; 加 tilt 强度 fav/head ∈ {0.0,0.5,1.5}  neu=1.0)
    grid = []
    for wb in (0.5, 1.0, 1.5):
        for wr in (0.0, 0.5, 1.0):
            for wl in (0.0, 0.5, 1.0):
                for use_tilt in (False, True):
                    grid.append((wb, wr, wl, use_tilt))
    def best_on(eps):
        bcfg, bnav, bsharpe = None, -1e9, -1e9
        for wb, wr, wl, ut in grid:
            nv = sim(eps, wb, wr, wl, use_tilt=ut)
            nn = float(nv["n"].iloc[-1]); sh = _sharpe(nv["n"], 20)
            if nn > bnav:
                bnav, bcfg = nn, (wb, wr, wl, ut)
                bsharpe = sh
        return bcfg, bnav, bsharpe
    tr_cfg, tr_nav, tr_sh = best_on(eps_tr)
    te_cfg, te_nav, te_sh = best_on(eps_te)
    print(f"  训练窗最优: 权重mix(价值/反转/低波动={tr_cfg[0]}/{tr_cfg[1]}/{tr_cfg[2]}) tilt={tr_cfg[3]} "
          f"→ 训练NET {tr_nav:.4f} (Sharpe {tr_sh:+.2f})", flush=True)
    # 用训练最优配置在验证窗评估
    nv_te = sim(eps_te, tr_cfg[0], tr_cfg[1], tr_cfg[2], use_tilt=tr_cfg[3])
    te_net_traincfg = float(nv_te["n"].iloc[-1])
    print(f"  训练最优配置 → 验证窗 NET {te_net_traincfg:.4f} (Sharpe {_sharpe(nv_te['n'],20):+.2f})", flush=True)
    print(f"  验证窗直接寻优(上界/过拟合): NET {te_nav:.4f} (Sharpe {te_sh:+.2f})", flush=True)
    # 等权分层 + 买持 在验证窗
    nv_d = sim(eps_te, 1.0, 1.0, 1.0)["n"]
    nv_ft = sim(eps_te, 1.0, 1.0, 1.0, use_tilt=True)["n"]
    print(f"  验证窗基准: 等权分层 {float(nv_d.iloc[-1]):.4f} | 等权+价值价差tilt {float(nv_ft.iloc[-1]):.4f}", flush=True)
    print("  ── 诚实判定 ──", flush=True)
    print("  * 训练最优配置在验证窗的表现 vs '验证窗直接寻优'(上界): 差距越大→过拟合越重。", flush=True)
    print("  * 若训练最优(验证NET) 仍 > 等于 等权分层/买持 → 权重优化具备一定泛化; 否则权重寻优是样本内拟合。", flush=True)

    print("\n── 诚实结论 ──", flush=True)
    print("  * NET(计成本)后: 分层/tilt 优势是否保留以输出为准; 高换手配置(如纯反转高位轮动)受成本侵蚀最大。", flush=True)
    print("  * 全局寻优是**样本内**的: 用训练/验证分离暴露过拟合; 权重(1.5/1.0/0.3)手工值 vs 网格最优的差距可衡量。", flush=True)
    print("  * 局限: 2018幸存池(幸存者偏差); 单窗口; 权重网格粒度有限; 成本模型(turnover*2*(佣金+滑点))为近似。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
