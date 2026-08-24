# -*- coding: utf-8 -*-
"""M2 验证：宏观条件化选板块 + 因子研究(IC/ICIR) + AI 决策门。

运行:  C:/Python314/python.exe backend/agent/verify_m2.py
无 LLM key，用 StubGate/确定性启发式；因子研究用真实 kline.db 银行股池。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.agent.macro_sector import pick_sector, pick_universe  # noqa: E402
from backend.agent.decision_gate import StubDecisionGate, LLMDecisionGate, _sanitize  # noqa: E402
from backend.strategy import catalog as catalog_mod  # noqa: E402
from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.agent import services as svc  # noqa: E402


def main():
    results = []
    def chk(label, cond, extra=""):
        results.append((label, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    known = catalog_mod.sectors()

    # ── 1) 宏观条件化选板块 ───────────────────────────────────────────
    print("── M2a 宏观条件化选板块 ──")
    real = svc.macro_regime()
    sec, reason = pick_sector(real)
    chk("真实宏观→板块在白名单", sec in known, f"{sec} ({reason})")
    univ = pick_universe(real)
    chk("真实宏观→代表股", bool(univ.get("code")), f"{univ.get('code')} {univ.get('name')}")

    def mk(cat):
        return {"overall": "", "categories": {
            "equity": {}, "fx": {}, "rate": cat.get("rate", {}),
            "commodity": cat.get("commodity", {}), "vol": cat.get("vol", {})}}

    cases = [
        ("risk-off/高波动", mk({"vol": {"label": "波动率情绪 高波动(risk-off) 30%"}}),
         {"银行", "医药/医疗"}),
        ("通胀+利率上行", mk({"rate": {"label": "利率流动性 美债利率上行"},
                          "commodity": {"label": "商品通胀 金+10% 油+5% 铜+3%"}}),
         {"黄金/有色", "稀有金属/稀土", "电力/能源", "化工/材料"}),
        ("利率下行", mk({"rate": {"label": "利率流动性 美债利率下行"}}),
         {"半导体/芯片", "AI/人工智能", "互联网/软件"}),
    ]
    for name, macro, allowed in cases:
        s, r = pick_sector(macro)
        chk(f"微观态[{name}]→板块", s in allowed, s)

    # ── 2) 因子研究(IC/ICIR) ─────────────────────────────────────────
    print("\n── M2b 因子研究(真实银行股池) ──")
    bank_codes = [i["code"] for i in catalog_mod.select(sector="银行", status="active")][:22]
    frames = load_universe_frames(bank_codes, start="2024-01-01", limit=600)
    chk("加载银行股池 frames", len(frames) >= 8, f"{len(frames)} 只")
    engine = FactorResearchEngine()
    for fid in ("momentum_20", "volatility_20", "reversal_5"):
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date="2024-01-01",
                           end_date="2026-06-01", groups=5, holding_period=5)
            ok = (isinstance(r.get("rankIc"), float) and len(r.get("groupCurves", [])) == 5
                  and len(r.get("icSeries", [])) > 0)
            extra = (f"IC={r.get('rankIc'):.3f} ICIR={r.get('icir'):.2f} "
                     f"覆盖={r.get('coverage'):.0%} 多空净={r.get('netLongShortReturn', 0):+.2%}") if ok else ""
            chk(f"因子[{fid}] IC/ICIR/分组", ok, extra)
        except Exception as e:
            chk(f"因子[{fid}] IC/ICIR/分组", False, str(e)[:50])

    # ── 3) AI 决策门 ─────────────────────────────────────────────────
    print("\n── AI 决策门(Stub/清洗) ──")
    gate = StubDecisionGate()
    d1 = gate.decide({"signal": True})
    chk("Stub 信号真→enter", d1.action == "enter", d1.to_dict().__str__()[:60])
    d2 = gate.decide({"signal": False})
    chk("Stub 信号假→hold", d2.action == "hold")
    # _sanitize: 非法 action → hold(保守)
    sanitized = _sanitize({"action": "scan", "score": "high", "confidence": 1.5})
    chk("清洗: 非法action→hold", sanitized.action == "hold")
    chk("清洗: confidence 截断到1", sanitized.confidence <= 1.0)
    # LLM gate 无 key → fallback
    from backend.agent.llm_client import LLMError
    lgate = LLMDecisionGate()
    try:
        d3 = LLMDecisionGate().decide({"signal": False})
        chk("LLM gate 无key→fallback hold", d3.action == "hold")
    except LLMError:
        chk("LLM gate 无key→fallback hold", False, "抛错")

    ok = all(x[1] for x in results)
    print(f"\nM2 验证: {sum(1 for x in results if x[1])}/{len(results)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
