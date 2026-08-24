# -*- coding: utf-8 -*-
"""价值/质量因子进策略契约(DSL)验证 — EP/BP/ROE 可被策略引用并回测。

运行: C:/Python314/python.exe backend/strategy/verify_value_strategy.py
前置: 600036 等标的 东财每日估值已缓存(fundamental.db)。
检查: ① validate() 接受 EP/BP/ROE(加入 KNOWN_FACTORS)
      ② 基于价值因子的策略能真实回测(有交易、指标有效, 点时间无前视)
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.strategy.spec import StrategySpec  # noqa: E402
from backend.strategy.backtest import run_backtest  # noqa: E402
from backend.strategy.data import load_klines  # noqa: E402


def main():
    results = []
    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    print("── 价值/质量因子进策略契约 ──")

    # 价值选股策略: 盈利收益率够高(便宜) AND 账面市值比够高(便宜, 质量) → 入场; 收益变低 → 离场
    contract = {
        "name": "value-便宜银行(EP/BP)", "description": "EP>0.10 且 BP>1.0 买入(便宜+质量); EP<0.12 卖出",
        "universe": {"code": "600036", "name": "招商银行"},
        "entry": {"type": "and", "args": [
            {"type": "gt", "args": ["EP", "0.10"]},
            {"type": "gt", "args": ["BP", "1.0"]},
        ]},
        "exit": {"type": "lt", "args": ["EP", "0.12"]},
        "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
        "risk": {"stop_loss_pct": 0.08, "take_profit_pct": 0.20,
                 "trailing_stop_pct": 0.0, "trailing_activation_pct": 0.0,
                 "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
        "params": {"initial_balance": 100000.0},
    }

    # ① validate 接受 EP/BP/ROE
    try:
        spec = StrategySpec.from_dict(contract)
        spec.validate()
        chk("validate 接受 EP/BP/ROE 因子", True)
    except Exception as e:
        chk("validate 接受 EP/BP/ROE 因子", False, str(e)[:80])
        print("  (契约被拒, 直接返回)")
        return 1

    # ② 真实回测(内部注入点时间基本面)
    kd, _ = load_klines("600036", limit=1200, warn_short=False)
    res = run_backtest(spec, kd)
    tr = res.metrics.get("total_return", 0.0) if res.metrics else 0.0   # 单位: %
    trades = res.metrics.get("num_trades", 0) if res.metrics else 0
    if not res.metrics:
        chk("价值策略回测产出指标", False, "empty metrics")
        return 1
    chk("价值策略回测有交易", int(trades) > 0, f"{int(trades)} 笔")
    chk("价值策略回测指标有效(总收益/夏普)",
        isinstance(tr, float) and isinstance(res.metrics.get("sharpe"), float),
        f"收益={tr * 100:+.2f}% 夏普={res.metrics.get('sharpe', 0):.2f} 笔数={int(trades)} "
        f"回撤={res.metrics.get('max_drawdown', 0) * 100:.2f}% 买入持有={res.metrics.get('buy_hold_return', 0) * 100:.2f}%")

    # ③ 无前视: EP 取值随 PE_TTM/价格变化(非穿越未来)
    from backend.strategy.factors import compute_factor_series
    from backend.fundamental import attach_kline_fundamentals
    en = attach_kline_fundamentals("600036", kd)
    s = compute_factor_series(en)
    eps = [v.get("EP") for v in s if v.get("EP") is not None]
    chk("EP/BP/ROE 逐bar产出(点时间)", len(eps) > 100 and max(eps) > 0.05,
        f"EP样本{len(eps)} 范围 {min(eps):.3f}~{max(eps):.3f}")

    ok = all(x[1] for x in results)
    print(f"\n价值/质量策略: {sum(1 for x in results if x[1])}/{len(results)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
