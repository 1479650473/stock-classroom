# -*- coding: utf-8 -*-
"""optimize_loop.py — 自主策略进化闭环(核心验收).

一个函数跑通: 5因子家族回测(精确指标α/年化/总收益/胜率/夏普/回撤) → 指标+买卖条件喂给
LLM → LLM 提出新优化因子契约 → 回测新契约(同样精确指标) → 与现有最优对比 → 若胜出,
写入模拟盘(portfolio_paper 重平衡到 AI账户) + 每日交易/操作进 paper ledger.

LLM 不可用时用 Stub 后端(确定性: 挑当前最强家族, 微调权重)也能跑通全链 —— 验证闭环本身.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..api.paths import DATA_DIR


# ── Stub 优化后端(确定性, 无 LLM key 时验证闭环) ────────────────
class StubOptimizer:
    """按当前最强家族做微调: 保持因子, 抬升 top_k_pct 或缩短持有期(见实证)."""
    name = "stub"

    def propose(self, families: dict, context: dict) -> dict:
        # 挑 metrics 里 total_return 最高的家族作为蓝本
        best_name, best_c = None, None
        for n, c in families.items():
            c = c or {}
            if c.get("error"):
                continue
            m = c.get("metrics") or {}
            if best_c is None or (m.get("total_return") or 0) > (best_c.get("metrics", {}).get("total_return") or 0):
                best_name, best_c = n, c
        if best_name is None:
            return {"error": "无可参考家族"}
        # 微调: 把 top_k_pct 略降(更集中) 或 rebalance_bars 缩短, 生成"改进版"
        import copy
        base = best_c.get("contract")
        new = copy.deepcopy(base)
        # 用描述里的基础三因子(或单因子家族)构建新契约
        nm = f"{best_name}-LLM优化"
        # 保留原因子/权重, 仅微调 top_k + 持有期(demo: 缩短20%持有期)
        new.rebalance_bars = max(5, int(base.rebalance_bars * 0.8))
        new.top_k_pct = min(0.5, base.top_k_pct * 0.8)
        new.use_tilt = base.use_tilt
        return {
            "name": nm,
            "description": f"由 {best_name} 演化: 持有期{base.rebalance_bars}->{new.rebalance_bars}, "
                           f"top_k {base.top_k_pct:.0%}->{new.top_k_pct:.0%}",
            "contract": new,
            "blueprint": best_name,
            "reason": f"延续最强家族 {best_name} 的因子结构, 缩短持有期+收紧选股集中度",
            "source": "stub",
        }


class LLMOptimizer:
    """真实 LLM: 输入家族精确指标 + 买卖条件, 提出改进契约(因子权重/持有期/top_k)."""
    name = "llm"

    def __init__(self):
        from ..agent.llm_client import LLMClient, extract_json, LLMError
        self._client = LLMClient()
        self._extract = extract_json

    def propose(self, families: dict, context: dict) -> dict:
        # 构建家族指标+条件表
        rows = []
        for n, c in families.items():
            c = c or {}
            if c.get("error"):
                continue
            m = c.get("metrics") or {}
            d = c.get("describe") or {}
            win = m.get("win_rate")
            win_s = f"{win*100:.1f}%" if win is not None else "N/A"
            alpha = m.get("alpha")
            alpha_s = f"{alpha*100:.1f}%" if alpha is not None else "N/A"
            rows.append(
                f"- {n}: 因子={c.get('strategy_name', n)}, 买入={d.get('buy_condition','')[:60]}；"
                f"总收益={m.get('total_return',0)*100:+.1f}% 年化={m.get('cagr',0)*100:+.1f}% "
                f"夏普={m.get('sharpe',0):.2f} 最大回撤={m.get('max_drawdown',0)*100:.1f}% "
                f"α={alpha_s} 胜率={win_s}")
        fam_tbl = "\n".join(rows)
        prompt = (
            "你是A股量化组合策略研究员。以下是5个因子家族策略的精确回测指标与买卖条件：\n\n"
            + fam_tbl +
            "\n\n请基于这些指标提出一个**优化版组合因子契约**(声明式JSON, 不是代码)，"
            "只允许调整：factors(因子列表, 从 BP/REVERSAL_20/VOLATILITY_20/EP/ROE 选)、"
            "base_weights(各因子权重, 可正可负)、top_k_pct(0~0.5)、rebalance_bars(5/10/20/40)、"
            "use_tilt(布尔)。目标是提高年化α、控制回撤、提升夏普。"
            "输出JSON格式：{\"name\":str,\"description\":str,\"factors\":[...],"
            "\"base_weights\":{...},\"top_k_pct\":float,\"rebalance_bars\":int,\"use_tilt\":bool}\n"
            "不要输出markdown围栏，不要解释。\n"
        )
        from ..agent.llm_client import LLMError
        try:
            text = self._client.complete(
                "你是A股量化策略研究员, 只输出声明式JSON契约。", prompt)
            data = self._extract(text)
        except LLMError:
            return {"error": "LLM不可用"}
        return {
            "name": data.get("name", "LLM-优化"),
            "description": data.get("description", ""),
            "factors": data.get("factors", ["BP", "REVERSAL_20", "VOLATILITY_20"]),
            "base_weights": data.get("base_weights", {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}),
            "top_k_pct": float(data.get("top_k_pct", 0.2)),
            "rebalance_bars": int(data.get("rebalance_bars", 20)),
            "use_tilt": bool(data.get("use_tilt", True)),
            "reason": data.get("description", ""),
            "source": "llm",
        }


def build_optimizer(use_llm: bool = True):
    if use_llm:
        try:
            return LLMOptimizer()
        except Exception:
            pass
    return StubOptimizer()


def run_optimize_loop(use_llm: bool = True, hp: int = 20, account_id: Optional[int] = None,
                      fwd_start: str = "2024-01-01", progress: Optional[Callable] = None,
                      persist: bool = True) -> dict:
    """自主策略进化闭环. 返回 {families, best, llm_proposal, new_backtest, verdict, new_strategy}."""
    def _emit(m):
        if progress:
            try:
                progress(m)
            except Exception:
                pass
    import copy, json
    from backend.paper_worker import run_paper_multi, _strategy_contracts
    from backend.strategy.metrics import compute_full_metrics
    from backend.strategy.describe import describe_contract
    from backend.strategy.factor_selector import build_wide_pool
    from backend.strategy.factor_research import FactorResearchEngine
    from backend.strategy.factor_data import load_universe_frames

    # ① 5家族回测(带精确指标+买卖条件). 优先复用已缓存的 paper_runs.json(快), hp 匹配才用.
    _emit("① 5因子家族回测(精确指标)...")
    r = None
    try:
        import os as _os
        _cpath = _os.path.join(DATA_DIR, 'paper_runs.json')
        with open(_cpath, encoding='utf-8') as f:
            _cached = json.load(f)
        if int(_cached.get("hp", -1)) == hp:
            families = dict(_cached.get("runs") or {})
            bh = _cached.get("buyhold") or {}
            # 补 contract 对象(describe/metrics 已在 runs 里; contract 需重建)
            contracts = _strategy_contracts(hp)
            for n in families:
                if isinstance(families[n], dict) and not families[n].get("error"):
                    families[n]["contract"] = contracts[n]
            r = {"families": families, "buyhold": bh, "as_of": _cached.get("as_of"), "pool_size": _cached.get("pool_size")}
            _emit(f"   复用缓存 paper_runs (as_of={_cached.get('as_of')})")
    except Exception:
        r = None
    if r is None:
        r = run_paper_multi(hp=hp, fwd_start=fwd_start)
        if r.get("error"):
            return {"error": r["error"]}
        families = r["runs"]
        contracts = _strategy_contracts(hp)
        for n in families:
            if isinstance(families[n], dict) and not families[n].get("error"):
                families[n]["contract"] = contracts[n]
        bh = r["buyhold"]
    _emit(f"   买持基准: 总收益{(bh.get('metrics') or {}).get('total_return',0)*100:+.1f}%")
    best = max((n for n, c in families.items() if isinstance(c, dict) and not c.get("error")),
               key=lambda n: (families[n].get("metrics") or {}).get("total_return", -1e9))
    _emit(f"   现有最强: {best} 总收益{(families[best].get('metrics') or {}).get('total_return',0)*100:+.1f}%")

    # ② LLM/Stub 提出新优化契约
    opt = build_optimizer(use_llm)
    _emit(f"② 优化器({opt.name})提出新策略...")
    proposal = opt.propose(families, {"hp": hp, "as_of": r["as_of"], "pool_size": r["pool_size"]})
    if proposal.get("error"):
        return {"families": families, "buyhold": bh, "error": proposal["error"]}
    _emit(f"   提议: {proposal.get('name','')} | {proposal.get('description','')[:60]}")

    # ③ 回测新契约(带基准 α). 用与 5家族纸面盘一致的帧(缓存, start=WARM, 含基本面).
    _emit("③ 回测新契约...")
    from backend.paper_worker import _load_frames
    frames = _load_frames()
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    import pandas as pd
    from backend.strategy.portfolio_rebalance import forward_paper_run, SelectionContract
    # 统一构造契约: LLM 给 factors/base_weights 参数; Stub 直接给 contract 对象
    if "contract" in proposal:
        nc = proposal["contract"]
    else:
        nc = SelectionContract(
            factors=proposal.get("factors", ["BP", "REVERSAL_20", "VOLATILITY_20"]),
            base_weights=proposal.get("base_weights", {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}),
            top_k_pct=float(proposal.get("top_k_pct", 0.2)),
            rebalance_bars=int(proposal.get("rebalance_bars", 20)),
            use_tilt=bool(proposal.get("use_tilt", True)),
            initial_balance=1_000_000.0)
    fwd_end = str(pd.Timestamp(close.index[-1]).date())
    fw = forward_paper_run(frames, nc, fwd_start, fwd_end, initial_balance=1_000_000.0)
    m = compute_full_metrics(fw["nav_n"], freq_bars=nc.rebalance_bars)
    # 与买持对比 α
    new_backtest = {"contract": nc, "metrics": m, "dates": fw["dates"], "nav": fw["nav_n"],
                    "final_holdings": fw["final_holdings"], "rebalances": fw["rebalances"],
                    "describe": describe_contract(nc),
                    "buyhold_nav": bh.get("nav", [])}
    _emit(f"   新策略: 总收益{m.get('total_return',0)*100:+.1f}% 年化{m.get('cagr',0)*100:+.1f}% "
          f"夏普{m.get('sharpe',0):.2f} 回撤{m.get('max_drawdown',0)*100:.1f}%")

    # ④ 对比裁决
    old_tr = (families[best].get("metrics") or {}).get("total_return", 0)
    new_tr = m.get("total_return", 0)
    old_mdd = abs((families[best].get("metrics") or {}).get("max_drawdown", 0) or 0)
    new_mdd = abs(m.get("max_drawdown", 0) or 0)
    # 胜出判据: 收益更高 且 回撤不显著变差(≤+5pp)
    verdict = "accept" if (new_tr > old_tr and (new_mdd - old_mdd) <= 0.05) else "reject"
    _emit(f"④ 裁决: {verdict} (新{new_tr*100:+.1f}% vs 旧{old_tr*100:+.1f}%, "
          f"回撤 {new_mdd*100:.1f}% vs {old_mdd*100:.1f}%)")
    new_strategy = None
    if verdict == "accept":
        new_strategy = {
            "name": proposal.get("name", best + "-opt"),
            "source": proposal.get("source", best),
            "reason": proposal.get("reason", ""),
            "contract": nc, "metrics": m, "describe": describe_contract(nc),
            "as_of": r["as_of"],
        }
        # ⑤ 写入模拟盘: 组合重平衡到 AI账户 (若 account_id 给定)
        if account_id is not None:
            _emit("⑤ 写入模拟盘(重平衡到 AI账户)...")
            from backend.agent.research_loop import build_operate_loop
            loop = build_operate_loop(use_llm=False)  # 组合重平衡为规则因子, 与LLM无关
            pp = loop.portfolio_paper(gw=loop.gw, contract=nc, account_id=account_id,
                                      max_pool=200, progress=_emit)
            new_strategy["paper"] = pp

    # ⑥ 持久化优化结果(供持仓页/后续)
    if persist and verdict == "accept":
        try:
            import os
            with open(os.path.join(DATA_DIR, 'optimizer_result.json'), 'w', encoding='utf-8') as f:
                json.dump({"as_of": r["as_of"], "verdict": verdict,
                           "best": best, "new_strategy": {
                               "name": new_strategy["name"], "source": new_strategy["source"],
                               "metrics": new_strategy["metrics"], "describe": new_strategy["describe"],
                               "reason": new_strategy["reason"],
                               "contract": {k: str(v) for k, v in vars(nc).items() if k != 'start'}},
                           "families": {n: {"metrics": c.get("metrics"), "describe": c.get("describe")}
                                        for n, c in families.items() if unchanged(c)}},
                          f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    return {"families": families, "buyhold": bh, "best": best, "proposal": proposal,
            "new_backtest": new_backtest, "verdict": verdict, "new_strategy": new_strategy}


def unchanged(c):
    return isinstance(c, dict) and not c.get("error")
