# -*- coding: utf-8 -*-
"""价值 regime 开关升级 — 用『价值价差(利好-利空多空)滞后动量』做信号(而非 SH 指数趋势)。

假设: 价值(低PB)在"价值价差转正(便宜正跑赢贵)"时处于防御窗口 → 持有价值组合;
      价值价差转负(成长跑赢) → 退出价值, 持有宽基等权。
这是**自指性** regime 信号(用价值是否在自己工作来开关价值), 无前视(只用滞后多空)。
对比: ①纯价值 ②纯宽基 ③SH指数趋势开关(旧) ④价值价差开关(新)。
运行: C:/Python314/python.exe backend/strategy/verify_value_regime2.py  (timeout 600)
"""
from __future__ import annotations

import os
import math
import sys
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.strategy.factor_selector import build_full_pool  # noqa: E402
from backend.strategy.data import load_klines  # noqa: E402

START = "2023-01-01"
END = datetime.now().strftime("%Y%m%d")
HP = 20
LS_LOOKBACK = 3   # 价值价差滞后窗口(个重平衡期)


def _index_regime(closes: pd.Series, ts) -> float:
    """SH指数趋势开关(旧): 1=弱市(倾向价值) 0=强市(倾向宽基)。"""
    hist = closes.loc[closes.index <= ts]
    if hist.empty:
        return 0.5
    last = float(hist.iloc[-1])
    ma = float(hist.rolling(120, min_periods=30).mean().iloc[-1]) if len(hist) >= 30 else last
    dd = last / max(hist.tail(60)) - 1.0 if len(hist) >= 20 else 0.0
    if last < ma or dd < -0.08:
        return 1.0
    return 0.0


def main() -> int:
    print("=== 价值 regime 开关升级: 价值价差滞后动量(自指) vs SH指数趋势 ===")
    print(f"窗口 {START}→{END} | holding={HP} | GROSS+NET | 规则: 信号=1(价值顺风)→持价值, 0→持宽基")
    pool = build_full_pool()
    frames = load_universe_frames(pool, start=START, end=END, with_fundamentals=True, fetch_missing=False)
    print(f"frames: {len(frames)} 只")
    idx, _ = load_klines("sh000001", limit=4000)
    idx_close = pd.Series([float(k["close"]) for k in idx],
                          index=pd.to_datetime([str(k["date"]) for k in idx], format="%Y%m%d", errors="coerce"))
    idx_close = idx_close[idx_close.index.notna()].sort_index()

    engine = FactorResearchEngine()
    r = engine.run(frames=frames, factor_id="BP", start_date=START, end_date=END,
                   groups=5, holding_period=HP, compute_correlation=False)
    print(f"BP: IC={r.get('rankIc',0):+.3f} ICIR={r.get('icir',0):+.2f} 覆盖={r.get('coverage',0):.0%}")

    curves = {c["group"]: c for c in r.get("groupCurves", [])}
    vc = max(curves, key=lambda g: g)
    vpoints = curves[vc]["points"]
    rebal = [pd.Timestamp(p["time"]) for p in vpoints]
    ls_pts = r.get("longShortCurve", [])          # [{time, gross, net}] 顶-底 多空累计NAV

    # 宽基等权
    opens = engine._panel(frames, "open")
    fwd = opens.shift(-(HP + 1)) / opens.shift(-1) - 1.0
    broad = {}
    for ts in rebal:
        if ts not in fwd.index:
            continue
        row = fwd.loc[ts].dropna()
        row = row[(row.abs() < 1.5) & (row == row)]
        broad[ts] = float(row.mean()) if not row.empty else 0.0

    # 价值价差滞后多空动量(自指信号): 最近 LS_LOOKBACK 个多空净收益的累计
    ls_map = {pd.Timestamp(p["time"]): float(p["net"]) for p in ls_pts}
    def value_spread_sig(i) -> float:
        """i=当前重平衡下标; 返回 1=价值顺风(近3期多空净为正) 0=价值逆风。"""
        if i < LS_LOOKBACK:
            return 1.0
        cur = ls_map.get(rebal[i]); prev = ls_map.get(rebal[i - LS_LOOKBACK])
        if cur is None or prev is None or prev <= 0:
            return 0.5
        ls_ret = cur / prev - 1.0
        return 1.0 if ls_ret > 0 else 0.0

    # 三种开关的累积(GRoss+net)
    def run_switch(sig_fn) -> dict:
        nv = {"g": 1.0, "n": 1.0}
        for i, ts in enumerate(rebal):
            vg = float(vpoints[i]["gross"]); vn = float(vpoints[i]["net"])
            v_g = vg / nv["g"] - 1.0; v_n = vn / nv["n"] - 1.0
            b = broad.get(ts, 0.0)
            sig = sig_fn(i)
            for k, (v_r, b_r) in {"g": (v_g, b), "n": (v_n, b)}.items():
                v_r = 0.0 if (not math.isfinite(v_r) or abs(v_r) > 1.5) else v_r
                b_r = 0.0 if (not math.isfinite(b_r) or abs(b_r) > 1.5) else b_r
                sw = v_r if sig >= 0.5 else b_r
                nv[k] *= (1.0 + sw)
        return nv

    # 直接累计纯价值/纯宽基
    pv = {"g": 1.0, "n": 1.0}; pb = {"g": 1.0, "n": 1.0}
    for i, ts in enumerate(rebal):
        for k in ("g", "n"):
            cur_nav = vpoints[i]["gross"] if k == "g" else vpoints[i]["net"]
            v_r = cur_nav / pv[k] - 1.0; b_r = broad.get(ts, 0.0)
            v_r = 0.0 if (not math.isfinite(v_r) or abs(v_r) > 1.5) else v_r
            b_r = 0.0 if (not math.isfinite(b_r) or abs(b_r) > 1.5) else b_r
            pv[k] *= (1.0 + v_r); pb[k] *= (1.0 + b_r)
    sw_spread = run_switch(value_spread_sig)
    sw_index = run_switch(lambda i: _index_regime(idx_close, rebal[i]) if i < len(rebal) else 0.5)
    val_cnt = sum(1 for i in range(len(rebal)) if value_spread_sig(i) >= 0.5)

    def fmt(x): return f"{x:.3f}({x-1:+.2%})"
    print("\n── 期末累计(起点=1.0) ──")
    for k, label in (("g", "GROSS(信号层)"), ("n", "NET(计成本)")):
        print(f"  [{label}]")
        print(f"    纯价值(前20%低PB)   : {fmt(pv[k])}")
        print(f"    纯宽基(等权买持)     : {fmt(pb[k])}")
        print(f"    SH指数趋势开关(旧)   : {fmt(sw_index[k])}")
        print(f"    价值价差开关(新/自指): {fmt(sw_spread[k])}")
    best = max([("纯价值", pv["g"]), ("纯宽基", pb["g"]), ("SH指数开关", sw_index["g"]), ("价值价差开关", sw_spread["g"])],
               key=lambda x: x[1])
    print(f"\n  GROSS 最优: {best[0]} (NAV {best[1]:.3f}) | 价值价差开关持有价值 {val_cnt}/{len(rebal)} 期")

    print("\n诚实结论: 用『价值价差滞后动量』(自指)做开关, 是否比『SH指数趋势』更能贴中价值的防御窗口?")
    print("  若价值价差开关>纯价值 → 自指开关有效(价值顺风时集中、逆风时退出); 若仍<纯价值 → 价值本身在本窗口(2023-now)持续跑赢, 任何'退出'都会稀释。")
    print("局限: 单窗口(2023→now); GROSS/NET; 自指信号有路径依赖; 用前值开关(无前视), 但多空净含成本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
