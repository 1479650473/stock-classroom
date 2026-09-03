# -*- coding: utf-8 -*-
"""Optimize blueprint — 自主策略进化闭环 (分阶段多 job, 用户可中途干预).

四阶段(每阶段独立 job, 前端自由决定下一步/改参数重跑):
  1. families   5因子家族回测(优先复用 paper_runs.json 缓存, hp 匹配才用)
  2. propose    LLM/Stub 提出新契约(factors/base_weights/top_k/rebalance_bars)
  3. backtest   回测提案契约(精确指标 α/夏普/回撤/胜率)
  4. verdict    对比裁决(新 vs 旧最强, 收益+回撤判据) + 可选 write 写入 AI账户

也可以用 /all 一键跑完五阶段(单 job, 进度帧按阶段推送).
"""
from flask import Blueprint, request

from ..envelope import ok, err
from ..jobman import submit

bp = Blueprint("optimize", __name__, url_prefix="/api/optimize")


# ---------- 公共 ----------
def _load_cache(hp: int):
    """读取 paper_runs.json 缓存(若 hp 匹配), 返回 families dict 或 None."""
    import os
    import json
    from frontend.plugins.research.worker import _strategy_contracts
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "data", "paper_runs.json")
    try:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if int(cached.get("hp", -1)) != int(hp):
            return None
        families = dict(cached.get("runs") or {})
        contracts = _strategy_contracts(hp)
        for n in families:
            if isinstance(families[n], dict) and not families[n].get("error"):
                families[n]["contract"] = contracts[n]
        return {"families": families, "buyhold": cached.get("buyhold"),
                "as_of": cached.get("as_of"), "pool_size": cached.get("pool_size"),
                "cached": True}
    except Exception:
        return None


def _families_json(families):
    """把契约对象转成可序列化 json(便于前端展示与回传)."""
    out = {}
    for n, c in families.items():
        if not isinstance(c, dict) or c.get("error"):
            continue
        m = c.get("metrics") or {}
        d = c.get("describe") or {}
        contract = c.get("contract")
        facs = [str(x) for x in (getattr(contract, "factors", None) or [])] if contract else []
        out[n] = {
            "strategy_name": c.get("strategy_name", n),
            "metrics": {k: v for k, v in m.items() if isinstance(v, (int, float))},
            "describe": {"summary": str(d.get("summary", "")) if isinstance(d, dict) else "",
                         "buy_condition": str(d.get("buy_condition", "")) if isinstance(d, dict) else ""},
            "factors": facs,
            "rebalance_bars": getattr(contract, "rebalance_bars", 20) if contract else 20,
            "top_k_pct": getattr(contract, "top_k_pct", 0.2) if contract else 0.2,
            "use_tilt": bool(getattr(contract, "use_tilt", False)) if contract else False,
            "status": c.get("status", "ok"),
            "total_return": m.get("total_return"),
        }
    return out


# ---------- ① 5家族回测 ----------
@bp.route("/families", methods=["POST"])
def stage_families():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    fwd_start = body.get("fwd_start", "2024-01-01")

    def _work(payload, on_progress):
        from frontend.plugins.research.worker import run_paper_multi
        on_progress({"msg": "读取家族回测(优先缓存)...", "pct": 10})
        cached = _load_cache(hp)
        if cached:
            on_progress({"msg": "命中缓存 paper_runs", "pct": 100})
            return cached
        on_progress({"msg": "全量跑 5 家族回测(约5-8min)...", "pct": 40})
        r = run_paper_multi(hp=hp, fwd_start=fwd_start)
        if r.get("error"):
            raise RuntimeError(r["error"])
        families = r["runs"]
        from frontend.plugins.research.worker import _strategy_contracts
        contracts = _strategy_contracts(hp)
        for n in families:
            if isinstance(families[n], dict) and not families[n].get("error"):
                families[n]["contract"] = contracts[n]
        on_progress({"msg": "完成", "pct": 100})
        return {"families": families, "buyhold": r.get("buyhold"),
                "as_of": r.get("as_of"), "pool_size": r.get("pool_size"), "cached": False}

    job = submit("optimize_families", _work, body)
    return ok(job, message="家族回测已排队")


# ---------- ② LLM 提案 ----------
@bp.route("/propose", methods=["POST"])
def stage_propose():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    use_llm = bool(body.get("use_llm", True))
    families = body.get("families") or {}

    def _work(payload, on_progress):
        from backend.strategy.optimize_loop import build_optimizer
        on_progress({"msg": f"优化器提出新策略({'LLM' if use_llm else 'Stub'})...", "pct": 20})
        opt = build_optimizer(use_llm=use_llm)
        proposal = opt.propose(families, {"hp": hp, "as_of": body.get("as_of", "")})
        if proposal.get("error"):
            raise RuntimeError(proposal["error"])
        on_progress({"msg": "提案生成", "pct": 100})
        c = proposal.get("contract")
        return {
            "name": proposal.get("name", "LLM-优化"),
            "description": proposal.get("description", ""),
            "source": proposal.get("source", ""),
            "reason": proposal.get("reason", ""),
            "factors": proposal.get("factors") or (list(c.factors) if c else []),
            "base_weights": proposal.get("base_weights") or (dict(c.base_weights) if c else {}),
            "top_k_pct": float(proposal.get("top_k_pct") or (getattr(c, "top_k_pct", 0.2) if c else 0.2)),
            "rebalance_bars": int(proposal.get("rebalance_bars") or (getattr(c, "rebalance_bars", 20) if c else 20)),
            "use_tilt": bool(proposal.get("use_tilt") or (getattr(c, "use_tilt", False) if c else False)),
        }

    job = submit("optimize_propose", _work, body)
    return ok(job, message="策略提案已排队")


# ---------- ③ 回测新契约 ----------
@bp.route("/backtest", methods=["POST"])
def stage_backtest():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    fwd_start = body.get("fwd_start", "2024-01-01")
    proposal = body.get("proposal") or {}
    if not proposal:
        return err(400, "missing_proposal", "需要 proposal(提案契约)", retriable=False)

    def _work(payload, on_progress):
        from backend.strategy.portfolio_rebalance import SelectionContract, forward_paper_run
        from backend.strategy.metrics import compute_full_metrics
        from backend.strategy.describe import describe_contract
        from frontend.plugins.research.worker import _load_frames, _strategy_contracts
        on_progress({"msg": "加载帧+回测提案契约...", "pct": 20})
        frames = _load_frames()
        nc = SelectionContract(
            factors=proposal.get("factors") or ["BP"],
            base_weights=proposal.get("base_weights") or {"BP": 1.0},
            top_k_pct=float(proposal.get("top_k_pct", 0.2)),
            rebalance_bars=int(proposal.get("rebalance_bars", 20)),
            use_tilt=bool(proposal.get("use_tilt", True)),
            initial_balance=1_000_000.0,
        )
        fw = forward_paper_run(frames, nc, fwd_start, "2099-12-31", initial_balance=1_000_000.0)
        on_progress({"msg": "计算指标...", "pct": 80})
        m = compute_full_metrics(fw["nav_n"], freq_bars=nc.rebalance_bars)
        on_progress({"msg": "完成", "pct": 100})
        return {
            "contract": proposal,
            "metrics": {k: v for k, v in m.items() if isinstance(v, (int, float))},
            "dates": fw.get("dates", []),
            "nav": [round(x, 4) for x in fw.get("nav_n", [])],
            "final_holdings": fw.get("final_holdings") or {},
            "rebalances": fw.get("rebalances"),
            "describe": describe_contract(nc),
        }

    job = submit("optimize_backtest", _work, body)
    return ok(job, message="新契约回测已排队")


# ---------- ④ 裁决(+可选写入) ----------
@bp.route("/verdict", methods=["POST"])
def stage_verdict():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    fwd_start = body.get("fwd_start", "2024-01-01")
    proposal = body.get("proposal") or {}
    new_backtest_body = body.get("new_backtest") or {}
    best_name = body.get("best")
    families_body = body.get("families") or {}
    write = bool(body.get("write", False))
    account_id = body.get("account_id")

    def _work(payload, on_progress):
        from backend.strategy.portfolio_rebalance import SelectionContract, forward_paper_run
        from backend.strategy.metrics import compute_full_metrics
        from backend.strategy.describe import describe_contract
        from frontend.plugins.research.worker import _load_frames
        on_progress({"msg": "读取裁决基准...", "pct": 10})
        families = dict(families_body) if isinstance(families_body, dict) else {}
        # 基准: 前端没传 families 则重算(用缓存优先)
        if not families:
            cached = _load_cache(hp)
            if cached:
                families = cached["families"]
            else:
                raise RuntimeError("缺少 families(请先跑 /families 或 /all)")
        best = best_name or None
        if not best and isinstance(families, dict):
            best = max((n for n, c in families.items()
                        if isinstance(c, dict) and not c.get("error")),
                       key=lambda n: ((families[n].get("metrics") or {}).get("total_return") or -1e9),
                       default=None)
        old_tr = float((families.get(best, {}).get("metrics") or {}).get("total_return") or 0) if best else 0.0
        old_mdd = abs(float((families.get(best, {}).get("metrics") or {}).get("max_drawdown") or 0)) if best else 0.0

        # 新契约指标: 前端传了则用, 否则重跑(校验/容错)
        new_m = dict((new_backtest_body or {}).get("metrics") or {})
        new_tr = float(new_m.get("total_return") or 0)
        new_mdd = abs(float(new_m.get("max_drawdown") or 0))
        new_backtest_proxy = new_backtest_body or {}
        if not new_m or not proposal.get("factors"):
            on_progress({"msg": "重跑提案契约(校验)...", "pct": 30})
            frames = _load_frames()
            nc = SelectionContract(
                factors=proposal.get("factors") or ["BP"],
                base_weights=proposal.get("base_weights") or {"BP": 1.0},
                top_k_pct=float(proposal.get("top_k_pct", 0.2)),
                rebalance_bars=int(proposal.get("rebalance_bars", 20)),
                use_tilt=bool(proposal.get("use_tilt", True)),
                initial_balance=1_000_000.0,
            )
            fw = forward_paper_run(frames, nc, fwd_start, "2099-12-31", initial_balance=1_000_000.0)
            new_m = compute_full_metrics(fw["nav_n"], freq_bars=nc.rebalance_bars)
            new_tr = float(new_m.get("total_return") or 0)
            new_mdd = abs(float(new_m.get("max_drawdown") or 0))
            new_backtest_proxy = {"metrics": new_m, "describe": describe_contract(nc)}

        verdict = "accept" if (new_tr > old_tr and (new_mdd - old_mdd) <= 0.05) else "reject"
        on_progress({"msg": f"裁决: {verdict} (新{new_tr*100:+.1f}% vs 旧{old_tr*100:+.1f}%)", "pct": 60})

        strategy = None
        if verdict == "accept" and write:
            on_progress({"msg": "写入模拟盘(重平衡到账户)...", "pct": 80})
            from backend.agent.research_loop import build_operate_loop
            nc = SelectionContract(
                factors=proposal.get("factors") or ["BP"],
                base_weights=proposal.get("base_weights") or {"BP": 1.0},
                top_k_pct=float(proposal.get("top_k_pct", 0.2)),
                rebalance_bars=int(proposal.get("rebalance_bars", 20)),
                use_tilt=bool(proposal.get("use_tilt", True)),
                initial_balance=1_000_000.0,
            )
            loop = build_operate_loop(use_llm=False)
            pp = loop.portfolio_paper(gw=loop.gw, contract=nc, account_id=int(account_id) if account_id else None,
                                      max_pool=200, progress=lambda m: on_progress({"msg": str(m), "pct": 85}))
            strategy = {"name": proposal.get("name", "LLM-优化"), "source": proposal.get("source", ""),
                        "metrics": new_m, "describe": describe_contract(nc), "paper": {
                            "rebalances": (pp or {}).get("rebalances"),
                            "final_holdings": (pp or {}).get("final_holdings"),
                            "nav_g": (pp or {}).get("nav_g"),
                            "cost_total": (pp or {}).get("cost_total")}}
            on_progress({"msg": "写入完成", "pct": 100})

        return {
            "best": best, "old_total_return": old_tr, "old_max_drawdown": old_mdd,
            "new_total_return": new_tr, "new_max_drawdown": new_mdd,
            "verdict": verdict, "new_strategy": strategy, "new_backtest": new_backtest_proxy,
        }

    job = submit("optimize_verdict", _work, body)
    return ok(job, message="裁决已排队")


# ---------- 一键: 五阶段单 job ----------
@bp.route("/all", methods=["POST"])
def run_all():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    fwd_start = body.get("fwd_start", "2024-01-01")
    use_llm = bool(body.get("use_llm", True))
    write = bool(body.get("write", False))
    account_id = body.get("account_id")

    def _work(payload, on_progress):
        from backend.strategy.optimize_loop import run_optimize_loop
        on_progress({"msg": "自主策略进化闭环开始...", "pct": 5})
        r = run_optimize_loop(use_llm=use_llm, hp=hp, fwd_start=fwd_start,
                              account_id=int(account_id) if account_id else None,
                              persist=True,
                              progress=lambda m: on_progress({"msg": str(m), "pct": min(95, 10 + len(str(m)) // 2)}))
        if r.get("error"):
            raise RuntimeError(r["error"])
        on_progress({"msg": "闭环完成", "pct": 100})
        return {
            "best": r.get("best"),
            "verdict": r.get("verdict"),
            "proposal": r.get("proposal") and {
                "name": r["proposal"].get("name"), "description": r["proposal"].get("description"),
                "source": r["proposal"].get("source"), "reason": r["proposal"].get("reason")} or None,
            "new_backtest": r.get("new_backtest") and {
                "metrics": {k: v for k, v in (r["new_backtest"].get("metrics") or {}).items()
                            if isinstance(v, (int, float))},
                "describe": r["new_backtest"].get("describe")} or None,
            "new_strategy": r.get("new_strategy"),
            "families": _families_json(r.get("families") or {}),
        }

    job = submit("optimize_all", _work, body)
    return ok(job, message="自主进化已排队")
