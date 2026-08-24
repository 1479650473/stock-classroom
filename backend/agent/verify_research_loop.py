# -*- coding: utf-8 -*-
"""M1 研究代理主循环 端到端验证(无 LLM key，用 StubBackend + InProcessGw 自包含)。

运行:  C:/Python314/python.exe backend/agent/verify_research_loop.py
验证闭环: 读宏观 → 选标的 → 生成声明式策略 → 异步回测 → 复盘 → 修订 → 择优 → 上 paper。
同时验证契约安全: 危险/非法契约(allow_short=True/未知因子)会被 StrategySpec 拒绝。
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.agent.research_loop import ResearchLoop, StubBackend, InProcessGw, score  # noqa: E402
from backend.agent.decision_gate import StubDecisionGate  # noqa: E402
from backend.agent import gateway as gw_mod, services as svc, store as store_mod  # noqa: E402
from backend.strategy.spec import StrategySpec  # noqa: E402
from backend.trade_engine.engine import TradeEngine  # noqa: E402


def main():
    store_mod.ensure_schema()
    results = []

    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    # 专用 paper 账户(避免污染真实账户)
    te = TradeEngine()
    test_acct = te.create_account(f"research-loop-paper-{int(time.time())}", 100000.0)
    acct_id = test_acct["id"] if isinstance(test_acct, dict) else test_acct

    gw = InProcessGw(agent_id="research-loop")
    loop = ResearchLoop(backend=StubBackend(), gw=gw)

    print("=" * 64)
    print("M1 研究代理主循环(Stub 后端 + AI 决策门)")
    print("=" * 64)
    res = loop.run(rounds=3, universe_code="600036", initial_balance=100000.0,
                   paper=True, paper_account_id=acct_id, gate=StubDecisionGate())

    chk("读取宏观 regime(整体标签)", bool(res.macro.get("overall")), res.macro.get("overall", "")[:40])
    chk("选定标的域", res.universe.get("code") == "600036", res.universe.get("code"))
    chk("至少一轮有指标", len(res.rounds) >= 1, f"{len(res.rounds)} 轮")

    best = res.best
    if best is not None:
        chk("择优选出(有正收益最优轮)", True, f"best=round{best.round_id} score={best.score}")
        chk("最优轮指标完整(总收益/夏普)", "total_return" in best.metrics and "sharpe" in best.metrics)
    else:
        chk("择优选出(有正收益最优轮)", False, "无正收益轮")

    chk("上 paper 盘(部署或下单)", res.paper is not None,
        res.paper.get("signal") if isinstance(res.paper, dict) else str(res.paper))
    dec = res.paper.get("decision") if isinstance(res.paper, dict) else None
    chk("决策门产出了结构化决策(action/score/confidence)",
        bool(dec and dec.get("action") in ("enter", "hold", "exit")
             and "score" in dec and "confidence" in dec), str(dec)[:70])

    print("\n── 各轮结果 ──")
    for r in res.rounds:
        m = r.metrics
        print(f"  R{r.round_id} 策略[{r.contract.get('name')}] sid={r.strategy_id} "
              f"收益 {m.get('total_return', 0) * 100:+.2f}% 夏普 {m.get('sharpe','')} 回撤 {m.get('max_drawdown', 0) * 100:.2f}% "
              f"笔数 {m.get('num_trades','')}  score={r.score}")
    print(f"── 最优: {('round%d %s score=%s' % (best.round_id, best.contract.get('name'), best.score)) if best else '无正收益轮'}  paper={res.paper}")

    # ── 契约安全红线 ──────────────────────────────────────────────
    print("\n── 契约安全验证(非法契约必须被拒) ──")
    # allow_short=True → 拒绝(A股 T+1 禁做空)
    bad_short = {"name": "bad", "universe": {"code": "600036"},
                 "entry": {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
                 "risk": {"allow_short": True}}
    try:
        StrategySpec.from_dict(bad_short).validate()
        chk("契约拒绝 allow_short=True", False, "未拒绝(致命)")
    except ValueError as e:
        chk("契约拒绝 allow_short=True", True, str(e)[:40])

    # 未知因子 → 无法合法生成(DSL 词表约束) → 建策略会被 reject
    bad_factor = {"name": "bad-factor", "universe": {"code": "600036"},
                  "entry": {"type": "gt", "args": ["NOT_A_FACTOR", 1]}, "risk": {}}
    try:
        s = svc.create_strategy(gw.token_id, gw.agent_id, bad_factor)
        chk("契约拒绝未知因子", False, f"未拒绝({s})")
    except Exception as e:
        chk("契约拒绝未知因子", True, str(e)[:40])

    # 未知 DSL 操作符 → 拒绝(与未知因子同为"静默死策略"缺口)
    bad_op = {"name": "bad-op", "universe": {"code": "600036"},
              "entry": {"type": "foobar", "args": ["CLOSE", 1]}, "risk": {}}
    try:
        s = svc.create_strategy(gw.token_id, gw.agent_id, bad_op)
        chk("契约拒绝未知DSL操作符", False, f"未拒绝({s})")
    except Exception as e:
        chk("契约拒绝未知DSL操作符", True, str(e)[:40])

    # 非 JSON / 代码注入 → LLMBackend 的 extract_json 必须抛错(不会把任意代码当成策略)
    from backend.agent.llm_client import extract_json, LLMError
    try:
        extract_json("```python\nos.system('rm')\n```")
        chk("拒绝代码注入(非JSON)", False, "未拒绝")
    except LLMError:
        chk("拒绝代码注入(非JSON)", True)

    # ── 清理 ──────────────────────────────────────────────────────
    gw_mod.revoke_token_record(gw.token_id)
    for r in res.rounds:
        try:
            svc.delete_strategy(gw.agent_id, r.strategy_id)
        except Exception:
            pass
    try:
        te.delete_account(acct_id)
    except Exception:
        pass

    ok = all(x[1] for x in results)
    print(f"\nM1 研究代理主循环验证: {sum(1 for x in results if x[1])}/{len(results)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
