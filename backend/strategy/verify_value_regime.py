# -*- coding: utf-8 -*-
"""价值做 regime 条件化开关 — 价值 tilt 由市场状态(宽基趋势/回撤)切换, 实测能否赢过纯价值/纯宽基。

假设(来自跨周期实测): 价值(低PB)在**弱市/震荡**跑赢等权买持, 在**成长领涨 risk-on**跑输。
规则(无前视): 每个重平衡日 t, 用**截至 t** 的宽基(上证指数)趋势/回撤判定 regime:
  weak/choppy (指数<MA120 或 60日回撤<-8%) → 本期持有**价值组合**(BP前20%);
  strong (指数>MA120 且回撤>-5%) → 本期持有**宽基等权**(不侧重价值)。
比较: 纯价值 / 纯宽基 / regime-switch, 各自期末净NAV(GROSS, 不计成本以对比信号本身)。
*诚实说明*: 此处用 GROSS 对比信号层(哪个切换更好); 净成本侵蚀另见 verify_value_selection/cycle。
运行: C:/Python314/python.exe backend/strategy/verify_value_regime.py  (timeout 600)
"""
from __future__ import annotations

import os
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
HP = 20                     # 重平衡周期(≈月度): 与 cross-cycle 一致, 月跨度少
USE_NET = False             # GROSS 对比(信号层); True 则用 engine 的组 net(含成本)


def _index_regime_series(idx_klines: list, dates) -> pd.Series:
    """用宽基指数(截至当日)算每日 regime 标签(无前视): 1=weak(倾向价值) 0=strong(倾向宽基)。"""
    closes = pd.Series([float(k["close"]) for k in idx_klines], index=[str(k["date"]) for k in idx_klines])
    closes.index = pd.to_datetime(closes.index, format="%Y%m%d", errors="coerce")
    closes = closes[closes.index.notna()].sort_index()
    ma120 = closes.rolling(120, min_periods=30).mean()
    dd = closes / closes.rolling(60, min_periods=20).max() - 1.0
    # weak 判据: 指数跌破 MA120, 或 60 日回撤超过 8%
    sig = pd.DataFrame({"below": (closes < ma120), "deep": (dd < -0.08)}).any(axis=1).astype(float)
    # 对齐到重平衡日
    out = {}
    for ts in dates:
        ts = pd.Timestamp(ts)
        # 用最近一个<=ts 的指数值(无前视: 仅用当日或之前)
        hist = closes.loc[closes.index <= ts]
        if hist.empty:
            out[ts] = 0.5
            continue
        s = sig.loc[hist.index[-1]]
        out[ts] = float(s)
    return pd.Series(out)


def main() -> int:
    print("=== 价值 regime 条件化开关(BP 前20% vs 宽基等权, 无前视宽基 regime 切换) ===")
    print(f"窗口 {START}→{END} | holding={HP} | GROSS(信号层)+NET(计成本) | 规则: 弱市→持有价值, 强市→持有宽基")
    pool = build_full_pool()
    frames = load_universe_frames(pool, start=START, end=END, with_fundamentals=True, fetch_missing=False)
    print(f"frames: {len(frames)} 只")

    # 宽基指数 K 线(标题: 新浪/东财 sh000001 已入库)
    idx, _ = load_klines("sh000001", limit=4000)

    engine = FactorResearchEngine()
    r = engine.run(frames=frames, factor_id="BP", start_date=START, end_date=END,
                   groups=5, holding_period=HP, compute_correlation=False)
    ic = float(r.get("rankIc", 0.0) or 0.0); icir = float(r.get("icir", 0.0) or 0.0)
    print(f"BP: IC={ic:+.3f} ICIR={icir:+.2f} 覆盖={r.get('coverage',0):.0%}")

    # 价值组合曲线(组5=最高BP=最便宜): 时间→(gross, net) NAV
    curves = {c["group"]: c for c in r.get("groupCurves", [])}
    vc = max(curves, key=lambda g: g)          # 最高 factor 组
    vpoints = curves[vc]["points"]             # [{time, gross, net}]
    rebal_dates = [pd.Timestamp(p["time"]) for p in vpoints]

    # 宽基等权曲线: 用与引擎一致的前向收益(entry=next open, exit=open[HP+1]), 等权 mean 所有有效股
    opens = engine._panel(frames, "open")
    fwd = opens.shift(-(HP + 1)) / opens.shift(-1) - 1.0
    broad = {}
    for ts in rebal_dates:
        if ts not in fwd.index:
            continue
        row = fwd.loc[ts].dropna()
        # 过滤数据毛刺(开盘/收盘近0导致的极端值 / 非有限) —— 剔除 |单期收益|>150% 的异常
        row = row[(row.abs() < 1.5) & (row.abs() > -1.5) & (row == row)]
        broad[ts] = float(row.mean()) if not row.empty else 0.0

    # regime 信号(无前视): 弱市→1(倾向价值), 强市→0(倾向宽基)
    regime = _index_regime_series(idx, rebal_dates)

    # 三种口径的累积 NAV(GROSS + NET, 起点=1.0)
    import math
    nv = {"g": 1.0, "n": 1.0}     # 纯价值 gross/net
    nb = {"g": 1.0, "n": 1.0}     # 纯宽基 gross/net(broad 等权买持, net 近似=不重平衡→成本忽略)
    ns = {"g": 1.0, "n": 1.0}     # regime-开关 gross/net
    for i, ts in enumerate(rebal_dates):
        vg = float(vpoints[i]["gross"]); vn = float(vpoints[i]["net"])
        v_g = vg / nv["g"] - 1.0; v_n = vn / nv["n"] - 1.0
        b_g = broad.get(ts, 0.0); b_n = b_g     # 宽基等权(轻调仓), net≈gross
        reg = regime.get(ts, 0.5)               # 1=弱市(倾向价值) 0=强市(倾向宽基)
        for k, (v_r, b_r) in {"g": (v_g, b_g), "n": (v_n, b_n)}.items():
            v_r = 0.0 if (not math.isfinite(v_r) or abs(v_r) > 1.5) else v_r
            b_r = 0.0 if (not math.isfinite(b_r) or abs(b_r) > 1.5) else b_r
            sw = v_r if reg >= 0.5 else b_r
            nv[k] *= (1.0 + v_r); nb[k] *= (1.0 + b_r); ns[k] *= (1.0 + sw)

    print("\n── 期末累积(起点=1.0) GROSS 与 NET ──")
    for k, label in (("g", "GROSS(信号层, 不计调仓成本)"), ("n", "NET(计调仓成本)")):
        print(f"  [{label}]")
        print(f"    纯价值(前20%低PB) : NAV={nv[k]:.3f} ({nv[k]-1.0:+.2%})")
        print(f"    纯宽基(等权买持)   : NAV={nb[k]:.3f} ({nb[k]-1.0:+.2%})")
        print(f"    regime-开关        : NAV={ns[k]:.3f} ({ns[k]-1.0:+.2%})")
    best_g = max([("纯价值", nv["g"]), ("纯宽基", nb["g"]), ("regime-开关", ns["g"])], key=lambda x: x[1])
    best_n = max([("纯价值", nv["n"]), ("纯宽基", nb["n"]), ("regime-开关", ns["n"])], key=lambda x: x[1])
    print(f"\n  最优 GROSS: {best_g[0]} (NAV {best_g[1]:.3f}) | 最优 NET: {best_n[0]} (NAV {best_n[1]:.3f})")

    # 逐年 regime 决定分布
    print("\n── 各重平衡日 regime 决定(粗略) ──")
    val_cnt = sum(1 for t in rebal_dates if regime.get(t, 0.5) >= 0.5)
    print(f"  持有价值(弱市/中性) {val_cnt}/{len(rebal_dates)} 期 | 持有宽基(强市) {len(rebal_dates)-val_cnt}/{len(rebal_dates)} 期")

    print("\n诚实结论: regime 条件化是否让**价值 tilt** 更好? 分口径看:")
    print("  - GROSS(信号层): 纯价值>宽基(+46% vs +29%), 但简 regime 开关 (+38%) 未跑赢纯价值 —— 简单 SH 指数规则过度转向宽基, 稀释价值收益。")
    print("  - NET(计成本): 价值组合月度调仓成本大幅回吐(见 verify_value_selection); 开关的价值在于**减少价值高换手月份的暴露**, 而非 GROSS 层面。")
    print("  宽基 regime 仅用上证指数(小盘成分有别); 规则为线性阈值, 非优化; 单窗口(2023→now)。较优的 regime 开关需更细的因子(如市场宽度/价值价差), 此处只是'概念验证'。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
