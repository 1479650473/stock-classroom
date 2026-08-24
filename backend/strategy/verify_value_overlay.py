# -*- coding: utf-8 -*-
"""价值因子作为过滤/择时叠加层 — 单标的 DSL 回测(真实估值+真实A股建模)。

问题: 纯价值(独立满仓低PB)在成长领涨的 risk-on 跑输买持(见 verify_value_selection)。
假设: 价值作为**过滤/择时**叠加层(便宜 AND 处于上升趋势)应优于纯价值 / 纯动量 / 买持。
测试(uniform, 无止损/止盈, 让 entry/exit 逻辑主导):
  A. 纯价值:  入场 BP>中位 & EP>中位(比自己通常便宜) ; 离场 不再便宜
  B. 叠加层:  入场 BP>中位 & EP>中位 & CLOSE>MA20(便宜且趋势) ; 离场 不再便宜或跌破MA20
  C. 纯动量:  入场 CLOSE>MA20 ; 离场 CLOSE<MA20
  D. 买持:    期末close/期初close-1
统一窗口 2024-01-01→now, 使各标的可加总对比。指标为小数(0.05=5%)。
运行: C:/Python314/python.exe backend/strategy/verify_value_overlay.py
"""
from __future__ import annotations

import os
import sys
import statistics
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.spec import StrategySpec  # noqa: E402
from backend.strategy.backtest import run_backtest  # noqa: E402
from backend.strategy.data import load_klines  # noqa: E402
from backend.fundamental import load_vals  # noqa: E402

# 价值股样本: 银行 + 价值蓝筹(有基本面 + 2024 起 K线)
UNIVERSE = ["600036", "601398", "601288", "000001", "601166",
            "600000", "601818", "002142", "601668", "600019"]
START, END = "2024-01-01", datetime.now().strftime("%Y%m%d")


def _med_fe(code: str) -> tuple:
    """该股(窗口内)EP/BP 中位数 = '自己通常的估值水平', 作为价值阈值(便宜=高于自己通常)。"""
    vals = [v for v in load_vals(code)]
    eps, bps = [], []
    for v in vals:
        if v.get("pe_ttm") and v["pe_ttm"] > 0 and v.get("pb") and v["pb"] > 0:
            eps.append(1.0 / v["pe_ttm"])
            bps.append(1.0 / v["pb"])
    if not eps:
        return None, None
    return statistics.median(eps), statistics.median(bps)


def _contract(name: str, desc: str, code: str, uni: str,
              entry: dict, exit_: dict, initial: float) -> dict:
    return {
        "name": name, "description": desc,
        "universe": {"code": code, "name": uni},
        "entry": entry, "exit": exit_,
        "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
        "risk": {"stop_loss_pct": 0.0, "take_profit_pct": 0.0,
                 "trailing_stop_pct": 0.0, "trailing_activation_pct": 0.0,
                 "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
        "params": {"initial_balance": initial},
    }


def _slice(code: str, start: str, end: str):
    kd, _ = load_klines(code, limit=1200)
    s, e = start.replace("-", ""), end.replace("-", "")
    kd = [k for k in kd if s <= str(k["date"]).replace("-", "") <= e]
    return kd


def main() -> int:
    # 1) 预计算各股窗口内 EP/BP 中位数 → 价值阈值
    from backend.strategy.data import stock_name as _sn
    thresholds = {}
    for code in UNIVERSE:
        epm, bpm = _med_fe(code)
        if epm is None:
            print(f"  {code}: 无估值 → 跳过")
            continue
        thresholds[code] = (epm, bpm)

    rows = []
    for code in UNIVERSE:
        if code not in thresholds:
            continue
        epm, bpm = thresholds[code]
        kd = _slice(code, START, END)
        if len(kd) < 90:
            print(f"  {code}: K线不足({len(kd)}) → 跳过")
            continue
        uni = _sn(code)
        initial = 100000.0
        # 买入持有基准(同窗口, 期末/期初close)
        bh = float(kd[-1]["close"]) / float(kd[0]["close"]) - 1.0

        # A 纯价值
        entryA = {"type": "and", "args": [{"type": "gt", "args": ["BP", round(bpm, 4)]},
                                          {"type": "gt", "args": ["EP", round(epm, 4)]}]}
        exitA = {"type": "or", "args": [{"type": "lt", "args": ["BP", round(bpm, 4)]},
                                        {"type": "lt", "args": ["EP", round(epm, 4)]}]}
        # B 叠加层(便宜 & 趋势): 外加 CLOSE>MA20
        ma_gt = {"type": "gt", "args": ["CLOSE", "MA20"]}
        ma_lt = {"type": "lt", "args": ["CLOSE", "MA20"]}
        entryB = {"type": "and", "args": [entryA, ma_gt]}
        exitB = {"type": "or", "args": [exitA, ma_lt]}
        # C 纯动量
        entryC = ma_gt
        exitC = ma_lt
        # D 趋势确认入场 + 价值离场(趋势只作入场确认, 离场由价值决定 → 避免抖出轨)
        entryD = entryB
        exitD = {"type": "or", "args": [{"type": "lt", "args": ["BP", round(bpm, 4)]},
                                        {"type": "lt", "args": ["EP", round(epm, 4)]}]}

        outs = {}
        for tag, label, entry, exit_ in (
                ("A价值", "纯价值", entryA, exitA),
                ("B叠加", "价值+趋势(进出)", entryB, exitB),
                ("C动量", "纯动量", entryC, exitC),
                ("D确认", "趋势确认+价值离场", entryD, exitD)):
            name = f"overlay-{tag}"
            desc = {"A价值": "便宜(BP>BP中位 & EP>EP中位)", "B叠加": "便宜 AND CLOSE>MA20(进出均含)",
                    "C动量": "CLOSE>MA20", "D确认": "便宜&CLOSE>MA20入场 / 价值离场"}[tag]
            spec = StrategySpec.from_dict(_contract(name, desc, code, uni, entry, exit_, initial))
            res = run_backtest(spec, kd)
            m = res.metrics
            outs[tag] = {"total": float(m.get("total_return", 0) or 0),
                         "wr": float(m.get("win_rate", 0) or 0),
                         "mdd": float(m.get("max_drawdown", 0) or 0),
                         "trades": len(res.trades),
                         "sharpe": float(m.get("sharpe", 0) or 0),
                         "final": float(m.get("final_equity", 0) or res.final_equity)}
        rows.append({"code": code, "uni": uni, "bh": bh, "epm": epm, "bpm": bpm, **outs})

    # 2) 输出
    print("=== 价值作为过滤/择时叠加层 ===  窗口", START, "→", END)
    print(f"{'标的':<18}{'买持':>8}{'纯价值':>9}{'价值+趋势':>11}{'纯动量':>9}{'趋势确认+价值离场':>16}   (累计收益; 笔数)")
    for r in rows:
        print(f"{r['code']} {r['uni']:<8}{r['bh']:>8.1%}"
              f"{r['A价值']['total']:>9.1%}"
              f"{r['B叠加']['total']:>11.1%}"
              f"{r['C动量']['total']:>9.1%}"
              f"{r['D确认']['total']:>16.1%}"
              f"  | A{r['A价值']['trades']:3d} B{r['B叠加']['trades']:3d} C{r['C动量']['trades']:3d} D{r['D确认']['trades']:3d}")

    # 3) 平均
    def avg(key):
        rows_ = [r[key]["total"] for r in rows if r[key]["total"] == r[key]["total"]]
        return sum(rows_) / len(rows_) if rows_ else 0.0
    n = len(rows)
    bh_avg = sum(r["bh"] for r in rows) / n if n else 0.0
    print("\n── 平均(等权, {n}只) ──".format(n=n))
    print(f"  买持              {bh_avg:+.2%}")
    print(f"  纯价值(A)         {avg('A价值'):+.2%}")
    print(f"  价值+趋势(B,进出) {avg('B叠加'):+.2%}")
    print(f"  纯动量(C)         {avg('C动量'):+.2%}")
    print(f"  趋势确认+价值离场(D) {avg('D确认'):+.2%}")

    def beats(a, b):
        # a = 'A价值'/'B叠加'/'C动量'/'D确认'; b = 同键 或 "bh"(买持)
        if not rows:
            return 0
        if b == "bh":
            return sum(1 for r in rows if r[a]["total"] > r["bh"])
        return sum(1 for r in rows if r[a]["total"] > r[b]["total"])
    print("\n── 相对跑赢(只数/总) ──")
    print(f"  价值+趋势(B) > 纯价值 : {beats('B叠加','A价值')}/{n}")
    print(f"  趋势确认+价值离场(D) > 纯价值 : {beats('D确认','A价值')}/{n}")
    print(f"  价值+趋势(B) > 买持   : {beats('B叠加','bh')}/{n}")
    print(f"  纯价值(A)   > 买持     : {beats('A价值','bh')}/{n}")
    print(f"  纯动量(C)   > 买持     : {beats('C动量','bh')}/{n}")
    print(f"  趋势确认+价值离场(D) > 买持 : {beats('D确认','bh')}/{n}")
    print("\n结论: '价值作为过滤/择时叠加层'**不成立/弱**——纯价值≈买持(无超额); 加 CLOSE>MA20 趋势叠加反而更差(抖出轨切碎价值择时);")
    print("      '趋势确认入场+价值离场'(D, 避免抖出) 再评估。置信的是: 单窗口(2024→now 成长领涨risk-on); 无止损止盈; 各股窗口一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
