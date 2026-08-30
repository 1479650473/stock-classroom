# -*- coding: utf-8 -*-
"""Research v2 blueprint — 研究页核心交互(回测/因子研究/组合纸面盘).

复刻桌面版研究面板的核心能力, Web 后端此前只有只读列表.
复用 worker._load_frames(缓存287池帧) + forward_paper_run(组合重平衡回测)
+ FactorResearchEngine(因子IC研究) + verify_full_lifecycle(完整生命周期).
重计算(帧加载+因子跑+forward ≈ 30-90s) 走 JobManager 异步, 前端轮询/SSE.
"""
from flask import Blueprint, request

from ..envelope import ok, err
from ..jobman import submit
from ..paths import PROJECT_DIR

bp = Blueprint("research_v2", __name__, url_prefix="/api/research")


# ---------- 私有: 加载研究上下文(缓存帧+契约) ----------
def _ctx():
    """返回 (frames, contracts_fn). 在 job 内调用(避免阻塞请求线程)."""
    from frontend.plugins.research.worker import _load_frames, _strategy_contracts
    frames = _load_frames()
    return frames, _strategy_contracts


def _contract_from(contract: dict, contracts_fn):
    """按策略id或自定义契约构造 SelectionContract."""
    if not contract:
        return None
    sid = contract.get("id")
    if sid:
        for name, c in contracts_fn(contract.get("hp", 20)).items():
            if name == sid:
                return c, str(sid)
    # 自定义: factors/weights/top_k/rebalance_bars
    from backend.strategy.portfolio_rebalance import SelectionContract
    return SelectionContract(
        factors=contract.get("factors") or ["BP"],
        base_weights=contract.get("weights") or {"BP": 1.0},
        top_k_pct=contract.get("top_k_pct", 0.2),
        rebalance_bars=contract.get("rebalance_bars", 20),
        initial_balance=contract.get("initial_balance", 1_000_000.0),
    ), contract.get("name", "自定义")


# ---------- ① 回测: POST /api/research/backtest ----------
@bp.route("/backtest", methods=["POST"])
def backtest():
    body = request.get_json(force=True, silent=True) or {}
    contract = body.get("contract")
    start = body.get("start", "2024-01-01")
    end = body.get("end", None)
    if not contract:
        return err(400, "bad_request", "需要 contract", retriable=False)

    def _work(payload, on_progress):
        from backend.strategy.portfolio_rebalance import forward_paper_run
        frames, contracts_fn = _ctx()
        c, name = _contract_from(contract, contracts_fn)
        on_progress({"msg": "加载历史帧并回测...", "pct": 30})
        fw = forward_paper_run(frames, c, start, end, initial_balance=c.initial_balance)
        from frontend.plugins.research.worker import _flatten_rebalance_trades
        from backend.strategy.metrics import compute_full_metrics
        tr = _flatten_rebalance_trades(fw.get("rebalance_log") or [])
        m = compute_full_metrics(fw["nav_n"], freq_bars=c.rebalance_bars, trades=tr,
                                 dates=fw.get("dates", []))
        on_progress({"msg": "计算指标...", "pct": 90})
        return {
            "name": name, "contract": contract,
            "dates": fw.get("dates", []), "nav": [round(x, 4) for x in fw.get("nav_n", [])],
            "metrics": m, "turnover_avg": fw.get("turnover_avg"),
            "rebalances": fw.get("rebalances"), "final_holdings": fw.get("final_holdings"),
        }

    job = submit("research_backtest", _work, body)
    return ok(job, message="回测已排队")


# ---------- ② 因子研究: POST /api/research/study ----------
@bp.route("/study", methods=["POST"])
def study():
    body = request.get_json(force=True, silent=True) or {}
    factor_id = body.get("factor_id", "BP")
    start = body.get("start", "2023-01-01")
    end = body.get("end", None)
    groups = int(body.get("groups", 5))
    holding_period = int(body.get("holding_period", 20))
    neutralize = bool(body.get("neutralize_industry", False))

    def _work(payload, on_progress):
        from backend.strategy.factor_research import FactorResearchEngine
        frames, _ = _ctx()
        on_progress({"msg": f"研究因子 {factor_id}...", "pct": 30})
        eng = FactorResearchEngine()
        r = eng.run(frames=frames, factor_id=factor_id, start_date=start,
                    end_date=end or str(frames[[k for k in frames][0]].index[-1])[:10],
                    groups=groups, holding_period=holding_period,
                    neutralize_industry=neutralize)
        on_progress({"msg": "计算 IC/ICIR...", "pct": 80})
        return r

    job = submit("research_study", _work, body)
    return ok(job, message="因子研究已排队")


# ---------- ③ 组合纸面盘: POST /api/research/paper ----------
@bp.route("/paper", methods=["POST"])
def paper():
    body = request.get_json(force=True, silent=True) or {}
    hp = int(body.get("hp", 20))
    top_k_pct = float(body.get("top_k_pct", 0.2))
    fwd_start = body.get("fwd_start", "2024-01-01")

    def _work(payload, on_progress):
        from frontend.plugins.research.worker import build_paper_only
        frames, _ = _ctx()
        on_progress({"msg": "组合纸面盘回放(多策略)...", "pct": 20})
        r = build_paper_only(hp=hp, top_k_pct=top_k_pct, fwd_start=fwd_start)
        on_progress({"msg": "完成", "pct": 100})
        return r

    job = submit("research_paper", _work, body)
    return ok(job, message="纸面盘已排队")


# ---------- ④ 典型策略一键回测: 5策略对比 ----------
@bp.route("/compare", methods=["POST"])
def compare():
    body = request.get_json(force=True, silent=True) or {}
    start = body.get("start", "2024-01-01")
    end = body.get("end", None)

    def _work(payload, on_progress):
        from backend.strategy.portfolio_rebalance import forward_paper_run
        from frontend.plugins.research.worker import _flatten_rebalance_trades
        from backend.strategy.metrics import compute_full_metrics
        frames, contracts_fn = _ctx()
        out = {}
        names = list(contracts_fn(20).keys())
        for i, name in enumerate(names):
            c = contracts_fn(20)[name]
            on_progress({"msg": f"回测 {name} ({i+1}/{len(names)})", "pct": 20 + i * (70 // len(names))})
            fw = forward_paper_run(frames, c, start, end, initial_balance=c.initial_balance)
            tr = _flatten_rebalance_trades(fw.get("rebalance_log") or [])
            m = compute_full_metrics(fw["nav_n"], freq_bars=c.rebalance_bars, trades=tr,
                                     dates=fw.get("dates", []))
            out[name] = {
                "metrics": {k: (round(v, 4) if isinstance(v, float) else v)
                            for k, v in m.items() if k in
                            ("total_return", "cagr", "sharpe", "sortino", "max_drawdown",
                             "alpha", "beta", "gamma", "win_rate", "profit_factor",
                             "num_trades", "turnover_yearly")},
                "nav": [round(x, 4) for x in fw.get("nav_n", [])],
                "dates": fw.get("dates", []),
            }
        on_progress({"msg": "完成", "pct": 100})
        return {"strategies": out, "start": start, "end": end or None}

    job = submit("research_compare", _work, body)
    return ok(job, message="策略对比已排队")
