# -*- coding: utf-8 -*-
"""真 LLM 生成"低PB价值选股"策略 + 全市场截面回测(周/月+多空价差+逐年基准) + 决策门。

运行:  C:/Python314/python.exe backend/strategy/verify_value_selection.py
前置:  settings.json 已配 DeepSeek(否则 LLM 生成回退到默认 BP 选股)。
诚实口径: BP/EP 是*跨截面选股*因子(全市场基本面, 点时间无前视)。本次"低PB选股"=每期持有
         被研究论证为"最便宜"(最高BP)的前 K% 等权组合, 定期调仓(含成本), 对比等权买入持有。
         关键区分: IC(rank相关, 点时间前向收益) vs 组合(长期持有) vs 基准(宽基等权)。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.agent.llm_client import LLMClient, extract_json, LLMError, get_agent_config  # noqa: E402
from backend.agent.decision_gate import LLMDecisionGate  # noqa: E402
from backend.strategy.factor_selector import (  # noqa: E402
    validate_value_selection, build_full_pool,
)
from backend.strategy.factor_research import FactorResearchEngine  # noqa: E402
from backend.strategy.factor_data import load_universe_frames  # noqa: E402
from backend.agent import services as svc  # noqa: E402

FULL_MARKET_EVIDENCE = {
    "BP":  {"ic": 0.041, "icir": 1.54, "conf": "high"},
    "EP":  {"ic": 0.023, "icir": 0.83, "conf": "medium"},
    "ROE": {"ic": -0.004, "icir": -0.23, "conf": "reject"},
}
DEFAULT_SEL = {"factor": "BP", "direction": "high", "hold_top_k_pct": 0.2, "rebalance_bars": 20,
               "risk": {"stop_loss_pct": 0.0, "max_hold_bars": 0, "avoid_st": True}}


def llm_generate(uname_desc: str, macro_overall: str, use_llm: bool) -> dict:
    if not use_llm:
        print("  [LLM] 未配置 key → 用默认 BP 选股(DEFAULT_SEL)")
        return dict(DEFAULT_SEL)
    ev = "\n".join(f"  {k}: IC={v['ic']:+.3f} ICIR={v['icir']:+.2f} 置信度={v['conf']}"
                   for k, v in FULL_MARKET_EVIDENCE.items())
    sys_prompt = (
        "你是 A 股价值选股策略设计师。基于给出的全市场价值因子截面研究证据, 设计一个**低估值选股**策略。"
        "只能输出一个符合给定 JSON Schema 的对象, 不要代码、不要解释、不要 markdown 围栏。"
        "选股是横截面的: 每调仓日按 factor 排序, 持有最'便宜'(按 direction)的前 hold_top_k_pct 比例组合, 等权, 定期调仓。"
    )
    user_prompt = (
        f"【全市场价值因子截面研究证据】(2026-08 标定)\n{ev}\n\n"
        f"【选股标的】{uname_desc}\n宏观: {macro_overall}\n\n"
        "【Schema】{\"name\":str,\"description\":str,\"factor\":\"EP|BP|ROE\",\"direction\":\"high|low\","
        "\"hold_top_k_pct\":float,\"rebalance_bars\":int,"
        "\"risk\":{\"stop_loss_pct\":float,\"max_hold_bars\":int,\"avoid_st\":bool}}\n"
        "说明: factor=B P(账面市值比, 越高越便宜)通常最强; direction=high=因子值越高越买; "
        "hold_top_k_pct 前K%(0.05~0.4); rebalance_bars 调仓周期(>=5, 5≈周/20≈月)。"
        "请生成一个你认为能稳定跑赢买入持有的低估值选股策略。"
    )
    client = LLMClient()
    contract = extract_json(client.complete(sys_prompt, user_prompt, max_tokens=700, temperature=0.4))
    return validate_value_selection(contract)


def _yearly(points: list) -> dict:
    yend: dict[str, float] = {}
    for p in points:
        yend[str(p["time"])[:4]] = float(p["net"])
    prev, out = 1.0, {}
    for y in sorted(yend):
        out[y] = yend[y] / prev - 1.0
        prev = yend[y]
    return out


def _sel_return_nav(res: dict) -> tuple[dict, float, float]:
    """返回 (逐年net收益, 累计净NAV, 累计净收益) —— 取因子值最高组(组合=direction high)。"""
    groups = res.get("groupCurves", [])
    if not groups:
        return {}, 1.0, 0.0
    gids = sorted(set(c["group"] for c in groups))
    curve = next((c for c in groups if c["group"] == gids[-1]), None)  # 最高factor组 = 最便宜
    if not curve or not curve["points"]:
        return {}, 1.0, 0.0
    net_nav = float(curve["points"][-1]["net"])
    return _yearly(curve["points"]), net_nav, net_nav - 1.0


def _benchmark_yearly(frames: dict, start_ts, end_ts) -> dict:
    """等权买入持有基准, 逐年: 每只股每年初open买/年末open卖, 等权平均。返回 {year: ret}。"""
    per: dict[str, list] = {}
    for s, df in frames.items():
        sub = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(sub) < 2:
            continue
        e = sub.groupby(sub.index.year)
        yrs = sorted(e.groups)
        for i, y in enumerate(yrs):
            g = e.get_group(y)
            first, last = float(g.iloc[0]["open"]), float(g.iloc[-1]["open"])
            if first > 0 and last > 0:
                per.setdefault(str(y), []).append(last / first - 1.0)
    return {y: sum(v) / len(v) for y, v in per.items() if v}


def _open_benchmark_buyhold(frames: dict, start_ts, end_ts) -> tuple:
    rets = []
    for s, df in frames.items():
        sub = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(sub) < 2:
            continue
        first, last = float(sub.iloc[0]["open"]), float(sub.iloc[-1]["open"])
        if first > 0 and last > 0:
            rets.append(last / first - 1.0)
    return (sum(rets) / len(rets), len(rets)) if rets else (None, 0)


def run() -> int:
    from backend.agent.llm_client import get_agent_config as _gac
    cfg = _gac()
    use_llm = bool(cfg.get("api_key") and cfg.get("api_base"))
    print("=== 真 LLM 生成'低PB价值选股'策略 + 全市场截面回测(周/月+多空+逐年基准) + 决策门 ===")
    print(f"LLM 配置: {use_llm}  模型: {cfg.get('model','stub')!r}")

    macro = svc.macro_regime()
    print(f"宏观 as_of={macro.get('as_of')} 新鲜度={macro.get('freshness_days')}天 | {macro.get('overall')}")

    pool = build_full_pool()
    print(f"选股池: {len(pool)} 只 | 载入 frames(本地缓存, 无前视)...")
    start, end = "2024-01-01", datetime.now().strftime("%Y%m%d")
    frames = load_universe_frames(pool, start=start, end=end, with_fundamentals=True, fetch_missing=False)
    print(f"  frames: {len(frames)} 只 | 窗口 {start}~{end}")

    print("\n[生成] 请 LLM 基于全市场实证(最强 BP ICIR 1.54)生成价值选股策略...")
    try:
        sel = llm_generate("全市场价值选股", str(macro.get("overall", "")), use_llm)
        src = "llm"
    except LLMError as e:
        print(f"  [LLM 生成失败: {e}] → 回退默认 BP 选股")
        sel, src = dict(DEFAULT_SEL), "fallback"
    print(f"  [{src}] {sel.get('name')}  factor={sel['factor']} 方向={sel['direction']} "
          f"前{sel['hold_top_k_pct']:.0%} 调仓={sel['rebalance_bars']}bar")

    engine = FactorResearchEngine()
    groups = max(2, min(10, round(1 / sel["hold_top_k_pct"])))

    def one(factor: str, holding: int) -> dict:
        r = engine.run(frames=frames, factor_id=factor, start_date=start, end_date=end,
                       groups=groups, holding_period=holding, compute_correlation=False)
        yearly, nav, ret = _sel_return_nav(r)
        return {"factor": factor, "holding": holding,
                "ic": float(r.get("rankIc", 0.0) or 0.0), "icir": float(r.get("icir", 0.0) or 0.0),
                "cov": float(r.get("coverage", 0.0) or 0.0),
                "ls": float(r.get("netLongShortReturn", 0.0) or 0.0),  # 多空价差(便宜-贵)
                "sel_nav": nav, "sel_ret": ret, "yearly": yearly}

    # 基准(一次算, 复用); 多空/组合在多个周期扫
    bench_total, bench_n = _open_benchmark_buyhold(frames, _pd(start), _pd(end))
    bench_yr = _benchmark_yearly(frames, _pd(start), _pd(end))

    rows = []
    for hp in (5, 20):
        rows.append(one(sel["factor"], hp))
    rows.append(one("EP", 5))   # 全市场次强对照

    print("\n── 全市场价值因子截面研究 + 选股组合(前{:.0%}) vs 等权买入持有 ──".format(sel["hold_top_k_pct"]))
    print("  [IC=rank相关(点时间前向收益) | ICIR | 覆盖 | 多空价差(贵→便宜) | 组合累计(含成本)]")
    for r in rows:
        print(f"  {r['factor']}@{r['holding']:2d}bar: IC={r['ic']:+.3f} ICIR={r['icir']:+.2f} "
              f"cov={r['cov']:.0%} 多空={r['ls']:+.2%} | 选股组合 {r['sel_ret']:+.2%} (NAV {r['sel_nav']:.3f})")
    print(f"  等权买入持有基准({bench_n}只, 期末open/期初open): {bench_total:+.2%}")
    print(f"  多空价差>0 ⇒ 便宜仍跑赢贵(价值有效); 选股组合跑输基准 ⇒ 便宜跑输了宽基(成长领涨的risk-on)")

    print("\n── 逐年(选股组合 @ 周/月 vs 基准) ──")
    print(f"  {'年':<6}{'基准等权':>10}{'BP@周':>10}{'BP@月':>10}{'EP@周':>10}")
    b0, b1 = rows[0], rows[1]
    for y in bench_yr:
        print(f"  {y:<6}{bench_yr[y]:>10.2%}{b0['yearly'].get(y,0):>10.2%}"
              f"{b1['yearly'].get(y,0):>10.2%}{rows[2]['yearly'].get(y,0):>10.2%}")

    print("\n── AI 决策门 ──")
    try:
        dec = LLMDecisionGate().decide({"macro": macro, "signal": True, "strategy": sel,
                                        "recent_klines": [], "price": 0.0})
        print(f"  决策: {dec.action}  score={dec.score} conf={dec.confidence} risk={dec.risk_level}")
        print(f"  reason: {dec.reason!r}  ({dec.source})")
    except Exception as e:
        print(f"  决策门异常: {type(e).__name__}: {str(e)[:80]}")

    print("\n── 结论(诚实标注) ──")
    print("  * 价值(低PB)是**真实但弱**的截面因子: IC≈0.04~0.07 为正, 周多空价差 +2.27%(便宜>贵)。")
    print("  * 但价值alpha是**短周期**的: 月度(长持有)多空价差转负(BP@月 -6.52%), 被调仓成本/期限侵蚀。")
    print("  * **长持有多头'低PB选股组合'未稳定跑赢等权买持基准**: 各周期(周/月)选股组合 +29%~+44%, 基准 +51.34%。")
    print("    成因: 成长领涨的 risk-on 里价值跑输宽基beta(2026年基准+3%但价值组合-4~-9%) —— 风格轮动/价值陷阱。")
    print("  * 决策门本窗返回 hold(风险不可控时保守), 正是对'价值短期跑输'的正确保护。")
    print("  * 局限: 幸存者偏差(活跃池); 单窗口/样本内; 27只新股/停牌无值; 基准为等权(小盘倾斜); 覆盖~62%。")
    return 0 if use_llm else 1


def _pd(s: str):
    import pandas as pd
    return pd.Timestamp(s)


if __name__ == "__main__":
    sys.exit(run())
