# -*- coding: utf-8 -*-
"""AgentOps blueprint — AI stock scanning, deep analysis, portfolio rebalance."""
from flask import Blueprint, request

from ..envelope import ok, err

bp = Blueprint("agentops", __name__, url_prefix="/api/agentops")


@bp.route("/scan", methods=["POST"])
def scan_entry_signals():
    """Evaluate entry signals for a stock against a strategy contract."""
    body = request.get_json(force=True, silent=True) or {}
    code = body.get("code")
    contract = body.get("contract")
    if not code or not contract:
        return err(400, "missing_fields", "code and contract required", retriable=False)
    try:
        from backend.agent.research_loop import eval_entry_signal
        triggered, price = eval_entry_signal(code, contract)
        return ok({"code": code, "triggered": triggered, "price": price})
    except Exception as e:
        return err(500, "agentops_scan_failed", str(e), retriable=False)


@bp.route("/deep", methods=["POST"])
def deep_analyze():
    """Deep news analysis + LLM verdict for candidate stocks."""
    body = request.get_json(force=True, silent=True) or {}
    candidates = body.get("candidates", [])
    if not candidates:
        return err(400, "missing_candidates", "candidates list required", retriable=False)
    try:
        from backend.strategy.stock_deep import deep_analyze
        result = deep_analyze(candidates)
        return ok(result)
    except Exception as e:
        return err(500, "agentops_deep_failed", str(e), retriable=False)


@bp.route("/portfolio/rebalance", methods=["POST"])
def portfolio_rebalance():
    """Preview portfolio rebalance: target weights + suggested trades."""
    from backend.data_manager import fetch_realtime_prices
    body = request.get_json(force=True, silent=True) or {}
    account_id = body.get("account_id")
    if account_id is None:
        return err(400, "missing_account_id", "account_id required", retriable=False)
    try:
        from backend.trade_engine.engine import TradeEngine
        from backend.trade_engine.schema import get_db_path
        engine = TradeEngine(get_db_path())
        account_id = int(account_id)
        account = engine.get_account(account_id)
        if not account:
            return err(404, "not_found", "account not found", retriable=False)

        positions = engine.get_positions(account_id)
        holdings = {p["code"]: p["qty"] for p in positions}
        cash = account["balance"]

        codes = list(holdings.keys())
        prices_list = fetch_realtime_prices(codes) if codes else []
        prices = {p["code"]: p["price"] for p in prices_list}

        total_assets = cash + sum(holdings.get(c, 0) * prices.get(c, 0) for c in holdings)
        current_weights = {}
        for c, q in holdings.items():
            mv = q * prices.get(c, 0)
            current_weights[c] = mv / total_assets if total_assets > 0 else 0

        # ── 建议调仓单(真实计算): 目标=持仓等权, 差额按100股整手取整 ──
        suggested_trades = []
        if holdings and total_assets > 0 and prices:
            n = len(holdings)
            name_of = {p["code"]: p["name"] for p in positions}
            for c, q in sorted(holdings.items()):
                px = prices.get(c) or 0
                if px <= 0:
                    continue
                target_qty = int(total_assets / n / px / 100) * 100
                diff = target_qty - q
                if diff == 0:
                    continue
                side = "buy" if diff > 0 else "sell"
                qty = abs(diff)
                if side == "sell" and qty > q:
                    qty = q
                suggested_trades.append({
                    "code": c, "name": name_of.get(c, c),
                    "side": side, "qty": qty, "price": round(px, 2),
                    "reason": f"{side == 'buy' and '加仓' or '减仓'}至等权",
                    "value": round(qty * px, 2),
                })

        return ok({
            "account_id": account_id,
            "name": account["name"],
            "cash": cash,
            "total_assets": total_assets,
            "holdings": holdings,
            "prices": prices,
            "current_weights": current_weights,
            "suggested_trades": suggested_trades,
        })
    except Exception as e:
        return err(500, "agentops_rebalance_failed", str(e), retriable=False)


@bp.route("/strategies", methods=["GET"])
def list_strategies():
    """List available strategy contracts with Chinese descriptions (真实5策略, 与研究页一致)."""
    try:
        from backend.paper_worker import _strategy_contracts
        from backend.strategy.describe import describe_contract
        out = []
        for name, c in _strategy_contracts(20).items():
            d = {}
            try:
                d = describe_contract(c)
            except Exception:
                pass
            facs = [str(x) for x in (getattr(c, "factors", None) or [])]
            out.append({
                "id": name, "name": name, "kind": "multi_factor" if len(facs) > 1 else "single",
                "factors": facs,
                "desc": str(d.get("summary") or d.get("desc") or " + ".join(facs)),
                "buy_condition": str(d.get("buy_condition", "")),
                "sell_condition": str(d.get("sell_condition", "")),
                "rebalance_bars": getattr(c, "rebalance_bars", 20),
                "top_k_pct": getattr(c, "top_k_pct", 0.2),
                "use_tilt": bool(getattr(c, "use_tilt", False)),
            })
        return ok(out)
    except Exception as e:
        return err(500, "agentops_strategies_failed", str(e), retriable=False)
