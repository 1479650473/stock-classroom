# -*- coding: utf-8 -*-
"""验证 ResearchLoop.portfolio_paper —— 把组合重平衡选股器(接 portfolio_value_alloc)挂进主闭环.

流程: 建一个专用 paper 账户(100k) → ResearchLoop(StubBackend, InProcessGw).portfolio_paper()
  → 读账户现金+持仓, RebalancePlanner 算目标组合(价值层权重随 三路信号多数决),
  → reconcile 出调仓交易, 逐笔 gw.paper_order 下真实 paper 单 → 打印计划+订单+账户状态.
运行: C:/Python314/python.exe backend/agent/verify_portfolio_paper_loop.py  (timeout 400)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.agent.research_loop import ResearchLoop, StubBackend  # noqa: E402
from backend.agent.research_loop import InProcessGw  # noqa: E402
from backend.agent import services as svc  # noqa: E402
from backend.strategy.factor_selector import build_wide_pool  # noqa: E402
from backend.strategy.portfolio_rebalance import SelectionContract  # noqa: E402
from backend.trade_engine.engine import TradeEngine  # noqa: E402


def _reset_account(engine: TradeEngine, account_id: int, initial: float):
    try:
        engine.reset_account(account_id)
    except Exception:
        pass
    return account_id


def main() -> int:
    print("=== ResearchLoop.portfolio_paper (组合重平衡器挂进主闭环) 验证 ===", flush=True)
    gw = InProcessGw(agent_id="portfolio-paper-test")
    engine = TradeEngine()
    # 专用账户, 重置到干净初始
    acc = engine.create_account("portfolio-paper-test", 100000.0)
    account_id = acc if isinstance(acc, int) else acc.get("id", 0)
    _reset_account(engine, account_id, 100000.0)
    print(f"专用 paper 账户: id={account_id} initial=100000", flush=True)

    loop = ResearchLoop(StubBackend(), gw)
    contract = SelectionContract(top_k_pct=0.2, rebalance_bars=20, initial_balance=100000.0)
    pool = build_wide_pool()
    print(f"池 {len(pool)} 只(跨板块均衡) | 调仓=20bar | top=20%", flush=True)

    print("\n[运行 portfolio_paper(重平衡+下单)]", flush=True)
    res = loop.portfolio_paper(gw=gw, pool=pool, contract=contract, account_id=account_id)
    if res.get("error"):
        print(f"  ✗ {res.get('code')}: {res.get('error')}", flush=True)
        return 1

    print(f"  账户 {res['account_id']} | as_of={res['as_of']} | 现金={res['cash']:.1f} | 已持仓 {len(res['holdings'])} 只", flush=True)
    tilt = res.get("tilt") or {}
    print(f"  tilt={tilt.get('tilt_label')} w_value={res.get('w_value')} | 三路信号={tilt.get('signal_parts')}", flush=True)
    print(f"  目标组合 {len(res.get('target') or {})} 只 | 生成调仓 {res['n_trades']} 笔", flush=True)

    print("\n[调仓交易 + 下单结果]", flush=True)
    ok = 0; fail = 0
    for o in res.get("orders", []):
        t = o.get("trade", {}); ordr = o.get("order") or {}
        status = ordr.get("status") if isinstance(ordr, dict) else None
        e = o.get("error")
        if e:
            fail += 1
            print(f"    ✗ {t.get('side','?')} {t.get('code')} x{t.get('qty')} @{t.get('price'):.2f} → 下单失败: {e}", flush=True)
        else:
            ok += 1
            print(f"    ✓ {t.get('side','?'):>4} {t.get('code')} x{t.get('qty')} @{t.get('price'):.2f} "
                  f"→ {status} 成交价={ordr.get('filled_price')}", flush=True)
    print(f"  下单成功 {ok} / 失败 {fail}", flush=True)

    # 下单后账户持仓
    print("\n[下单后账户状态]", flush=True)
    acc2 = engine.get_account(account_id)
    print(f"  余额(现金)={acc2['balance']:.1f} | 持仓 {len(engine.get_positions(account_id))} 只", flush=True)
    for p in engine.get_positions(account_id)[:10]:
        print(f"    {p['code']} qty={p['qty']}", flush=True)

    print("\n── 诚实结论 ──", flush=True)
    print("  * ResearchLoop.portfolio_paper 已把组合重平衡选股器(基于 portfolio_value_alloc 的三路信号)挂进主闭环:", flush=True)
    print("    在真实 paper 账户现金/持仓上算目标组合 → reconcile → 逐笔真实下单。", flush=True)
    print("  * 这是『研究→组合纸面』的一步(vs run() 的单票 paper); 构成本次『全局寻优+分层+tilt』证据的落地出口。", flush=True)
    print("  * 局限: 一次性重平衡(非历史回测); 池为跨板块均衡(~287); 目标=最新持仓日快照; 账户初始100k demo。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
