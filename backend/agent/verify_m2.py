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

import pandas as pd  # noqa: E402


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

    # ── 2b) 因子库扩充 + ICIR 自动选参 ──────────────────────────────
    print("\n── M2b2 因子库扩充 + ICIR 自动选参 ──")
    from backend.strategy.factor_selector import recommend, _band, DEFAULT_BANDS, CANDIDATES  # noqa: E402
    new_fids = ("momentum_40", "reversal_10", "volatility_60", "skew_20", "rsi_14")
    for fid in new_fids:
        try:
            r = engine.run(frames=frames, factor_id=fid, start_date="2024-01-01",
                           end_date="2026-06-01", groups=5, holding_period=5,
                           compute_correlation=False)
            ok = (isinstance(r.get("rankIc"), float) and len(r.get("groupCurves", [])) == 5
                  and len(r.get("icSeries", [])) > 0)
            extra = (f"IC={r.get('rankIc'):.3f} ICIR={r.get('icir'):.2f} "
                     f"覆盖={r.get('coverage'):.0%}") if ok else ""
            chk(f"新增因子[{fid}] IC/ICIR/分组", ok, extra)
        except Exception as e:
            chk(f"新增因子[{fid}] IC/ICIR/分组", False, str(e)[:50])
    # RSI_14 值域 [0,100]
    close_panel = pd.DataFrame({s: frames[s]["close"] for s in frames})
    rsi = FactorResearchEngine._rsi(close_panel, 14)
    chk("RSI_14 值域在[0,100]",
        float(rsi.min().min()) >= 0 and float(rsi.max().max()) <= 100,
        f"min={rsi.min().min():.1f} max={rsi.max().max():.1f}")
    # ICIR 分档
    chk("ICIR分档 high", _band(2.0, DEFAULT_BANDS) == ("high", 1.0), str(_band(2.0, DEFAULT_BANDS)))
    chk("ICIR分档 medium", _band(0.7, DEFAULT_BANDS)[0] == "medium")
    chk("ICIR分档 weak", _band(0.4, DEFAULT_BANDS)[0] == "weak")
    chk("ICIR分档 reject", _band(0.1, DEFAULT_BANDS)[0] == "reject")
    # 自动选参: 严格门槛 → 全被拒(None 或全 high); 宽松门槛 → 选出带参数的因子
    strict = recommend(bank_codes, "2024-01-01", "2026-06-01",
                       min_icir=2.0, min_ic=0.005, min_coverage=0.5)
    chk("严格ICIR(2.0)→无因子或全high",
        strict is None or strict.get("confidence") == "high" or strict.get("abs_icir", 0) >= 2.0,
        f"{strict.get('dsl_key') if strict else 'None'} |ICIR|={strict.get('abs_icir', 0):.2f}" if strict else "None")
    loose = recommend(bank_codes, "2024-01-01", "2026-06-01",
                      min_icir=0.3, min_ic=0.005, min_coverage=0.5)
    chk("宽松ICIR(0.3)→选出因子", loose is not None and loose.get("dsl_key") in CANDIDATES,
        f"{loose.get('dsl_key')} IC={loose.get('ic', 0):.3f} ICIR={loose.get('icir', 0):.2f} "
        f"conf={loose.get('confidence')}" if loose else "None")
    chk("推荐含置信度/阈值/参数",
        loose is not None and all(k in loose for k in ("confidence", "threshold", "bands",
                                                       "icir_threshold", "direction")))
    # 方向感知 entry: 由 direction 决定 op
    from backend.strategy.factor_selector import entry_for_factor  # noqa: E402
    e1 = entry_for_factor({"dsl_key": "MOMENTUM_20", "direction": 1, "threshold": 0.0})
    e2 = entry_for_factor({"dsl_key": "REVERSAL_5", "direction": -1, "threshold": 0.0})
    chk("方向感知 entry(高→gt)", e1 == {"type": "gt", "args": ["MOMENTUM_20", 0.0]}, str(e1))
    chk("方向感知 entry(低→lt)", e2 == {"type": "lt", "args": ["REVERSAL_5", 0.0]}, str(e2))

    # ── 2c) 价值/质量因子(基本面, 东财每日估值 EP/BP/ROE) ────────────────
    print("\n── M2b3 价值/质量因子(EP/BP/ROE, 东财每日估值) ──")
    from backend.strategy.factor_selector import study_value_factors, VALUE_CANDIDATES  # noqa: E402
    from backend.fundamental import load_vals  # noqa: E402
    value_codes = ["601398", "601288", "601988", "601939", "601328",
                   "601658", "600036", "600000", "600016", "601166"]
    cached = sum(1 for c in value_codes if load_vals(c))
    chk("基本面已缓存(每日估值)", cached >= 5, f"{cached}/{len(value_codes)} 只")
    vres = study_value_factors(value_codes, "2024-01-01", "2026-06-01")
    for v in vres:
        chk(f"价值/质量因子[{v['dsl_key']}] IC/ICIR",
            isinstance(v.get("ic"), float) and len(v.get("research", {}).get("groupCurves", [])) == 5,
            f"IC={v['ic']:.3f} ICIR={v['icir']:.2f} 覆盖={v['coverage']:.0%} 多空净={v['net_long_short']:+.2%}")
    chk("价值因子为研究维度(非策略候选)", VALUE_CANDIDATES == ["EP", "BP", "ROE"]
        and not set(VALUE_CANDIDATES) & set(CANDIDATES))

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
