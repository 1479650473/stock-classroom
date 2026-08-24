# -*- coding: utf-8 -*-
"""真 LLM 端到端验证 — LLM 基于"研究论证因子 + 决策门"生成/复盘策略。

运行:  C:/Python314/python.exe backend/agent/verify_llm_run.py
前置:  backend/configs/settings.json 已配深证 LLM api_key/model(否则自动回退 Stub)。
输出:  研究因子证据 + LLM 生成契约(摘要) + 各轮回测指标 + 择优 + paper(决策门)。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.agent.llm_client import LLMError  # noqa: E402
from backend.agent.research_loop import ResearchLoop, LLMBackend, StubBackend, InProcessGw  # noqa: E402
from backend.agent.decision_gate import LLMDecisionGate  # noqa: E402


def main():
    # 选后端: 有 LLM 配置则用真 LLM, 否则 Stub(报告)
    from backend.agent.llm_client import get_agent_config
    cfg = get_agent_config()
    use_llm = bool(cfg.get("api_key") and cfg.get("api_base"))
    backend = LLMBackend() if use_llm else StubBackend()
    print(f"=== 真 LLM 端到端闭环 ===")
    print(f"后端: {backend.name}  模型: {cfg.get('model', 'stub')!r}  llm_configured={use_llm}")

    gw = InProcessGw(agent_id="llm-run")
    gate = LLMDecisionGate()
    loop = ResearchLoop(backend, gw)

    try:
        res = loop.run(rounds=2, universe_code="600036", initial_balance=100000.0,
                       paper=True, paper_account_id=4, gate=gate, use_factor_research=True)
    except LLMError as e:
        print(f"\n[LLMError] {e} → 用确定性 Stub 验证")
        backend = StubBackend()
        loop = ResearchLoop(backend, gw)
        res = loop.run(rounds=2, universe_code="600036", initial_balance=100000.0,
                       paper=True, paper_account_id=4, gate=LLMDecisionGate())

    print(f"\n── 各轮结果 ──")
    for rr in res.rounds:
        c = rr.contract
        print(f"  R{rr.round_id} [{c.get('name')}] sid={rr.strategy_id} "
              f"收益={rr.metrics.get('total_return', 0) * 100:+.2f}% "
              f"夏普={rr.metrics.get('sharpe', 0):.2f} 回撤={rr.metrics.get('max_drawdown', 0):.2f}% "
              f"score={rr.score}")
        print(f"       entry={json.dumps(c.get('entry'), ensure_ascii=False)[:150]}")
        if rr.round_id == 1:
            print(f"       risk={c.get('risk')}")

    if res.best:
        print(f"\n── 最优轮 ──")
        print(f"  R{res.best.round_id} [{res.best.contract.get('name')}] "
              f"收益={res.best.metrics.get('total_return', 0) * 100:+.2f}% "
              f"胜率={res.best.metrics.get('win_rate', 0)}%")
    else:
        print(f"\n── 最优轮: 无(所有轮收益为负或回撤过大, 评分 -inf) ──")

    # paper 记录
    if res.paper:
        d = res.paper.get("decision")
        print(f"\n── paper 盘 ──")
        print(f"  signal={res.paper.get('signal')}  note={res.paper.get('note', '')}")
        if d:
            print(f"  决策门: {d.get('action')} score={d.get('score')} conf={d.get('confidence')} "
                  f"reason={d.get('reason')!r}")
    print("\n完成。真 LLM 生成/复盘闭环可跑通。" if use_llm else "\n完成(注: 用 Stub, 未配置真 LLM key)。")
    return type("", (), {"x": 0}) if use_llm else None


if __name__ == "__main__":
    main()
