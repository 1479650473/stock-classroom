# -*- coding: utf-8 -*-
"""M0 垂直切片验证 — 一条策略跑通 生成→回测→指标，并自检引擎可信度。

直接从 data/kline.db 读真实 K 线(不依赖 akshare/网络)。运行:
    cd <项目根> && python backend/strategy/run_vertical_slice.py
"""
import os, sys, sqlite3, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.spec import StrategySpec
from backend.strategy.backtest import run_backtest
from backend.strategy.metrics import _max_drawdown, buy_hold_equity
from backend.strategy.data import load_klines, stock_name


# ── 示例策略契约（模拟 LLM 的第一版输出，M1 再由 agent 生成）───────────
SAMPLE_STRATEGY = {
    "name": "均线金叉 + 超卖反弹",
    "description": "MA5上穿MA10 且 收盘>MA20 且 RSI14在40~70 买入；RSI14>75 或 MACD死叉 卖出；止损5%止盈12%",
    "universe": {"code": "600036", "name": "招商银行"},
    "entry": {
        "type": "and",
        "args": [
            {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
            {"type": "gt", "args": ["CLOSE", "MA20"]},
            {"type": "between", "args": ["RSI14", 40, 70]},
        ],
    },
    "exit": {
        "type": "or",
        "args": [
            {"type": "gt", "args": ["RSI14", 75]},
            {"type": "eq", "args": ["MACD_CROSS_DOWN", 1]},
        ],
    },
    "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
    "risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12, "allow_short": False},
    "params": {"initial_balance": 100000.0},
}


def fmt_metrics(m, bh_ret, bh_mdd):
    """metrics 口径为小数(0.05=5%) → 显示 ×100。"""
    lines = []
    lines.append(f"  回测区间   : {m['bars']} 根日K")
    lines.append(f"  初始资金   : ¥{m['initial_balance']:,.0f}  →  期末 ¥{m['final_equity']:,.2f}")
    lines.append(f"  总收益率   : {m['total_return'] * 100:+.2f}%")
    lines.append(f"  年化(CAGR) : {m['cagr'] * 100:+.2f}%")
    lines.append(f"  夏普比率   : {m['sharpe']:.3f}")
    lines.append(f"  最大回撤   : {m['max_drawdown'] * 100:.2f}%")
    lines.append(f"  交易次数   : {m['num_trades']}   胜率 {m['win_rate'] * 100:.2f}%   盈亏比 {m['profit_factor']:.3f}")
    lines.append(f"  基准(买入持有): {m['buy_hold_return'] * 100:+.2f}%  回撤 {m['buy_hold_max_drawdown'] * 100:.2f}%")
    return "\n".join(lines)


def main():
    code = SAMPLE_STRATEGY["universe"]["code"]
    name = stock_name(code)
    SAMPLE_STRATEGY["universe"]["name"] = name
    spec = StrategySpec.from_dict(SAMPLE_STRATEGY)
    spec.validate()

    klines, warns = load_klines(code)
    if not klines:
        print("ERROR: 无K线数据", code)
        return 1

    print("=" * 64)
    print(f"策略: {spec.name}")
    print(f"标的: {code} {name}  |  {klines[0]['date']} ~ {klines[-1]['date']} ({len(klines)}根日K)")
    print("=" * 64)

    if warns:
        print("\n⚠️ 数据质量警告:")
        for w in warns:
            print("  - " + w)

    res = run_backtest(spec, klines)
    m = res.metrics
    print("\n── 回测指标 ──")
    print(fmt_metrics(m, m["buy_hold_return"], m["buy_hold_max_drawdown"]))

    print("\n── 最近 5 笔成交 ──")
    for t in res.trades[-5:]:
        print(f"  {t['entry_date']} 买 {t['qty']}股@{t['entry_price']}  "
              f"→ {t['exit_date']} 卖@{t['exit_price']}  pnl {t['pnl']:+,.2f}")
    if res.errors:
        print("\n── 被拦截事件(诊断, 前5) ──")
        for e in res.errors[:5]:
            print("  " + e)

    # ── 自检：可信度 ──────────────────────────────────────────────
    print("\n── 引擎自检 ──")
    checks = []
    checks.append(("权益曲线非空", len(res.equity_curve) > 0))
    checks.append(("权益曲线条数=bar数", len(res.equity_curve) == len(klines)))
    checks.append(("无 NaN 期末权益", res.final_equity == res.final_equity))

    # 自检1: 无信号无风控策略 → 应零成交、期末=初始
    noop = StrategySpec.from_dict({
        "name": "noop", "universe": {"code": code, "name": name},
        "entry": None, "exit": None,
        "risk": {"stop_loss_pct": None, "take_profit_pct": None},
        "params": {"initial_balance": 100000.0},
    })
    r2 = run_backtest(noop, klines)
    checks.append(("noop零成交", r2.metrics["num_trades"] == 0))
    checks.append(("noop盈亏平衡", abs(r2.final_equity - 100000.0) < 0.01))

    # 自检2: 基准权益重建 = 买入持有
    bh = buy_hold_equity(100000.0, klines)
    checks.append(("基准权益曲线非空", len(bh) > 0))
    checks.append(("基准收益与指标一致",
                   abs((bh[-1][1] / 100000.0 - 1.0) - m["buy_hold_return"]) < 0.02))

    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    all_ok = all(ok for _, ok in checks)
    print("\n" + ("✅ 全部自检通过 → 回测引擎可信" if all_ok else "❌ 存在自检失败"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
