# -*- coding: utf-8 -*-
"""AgentOps blueprint — AI stock scanning, deep analysis, portfolio rebalance."""
from flask import Blueprint, jsonify, request

bp = Blueprint("agentops", __name__, url_prefix="/api/agentops")


@bp.route("/scan", methods=["POST"])
def scan_entry_signals():
    """Evaluate entry signals for a stock against a strategy contract."""
    body = request.get_json(force=True, silent=True) or {}
    code = body.get("code")
    contract = body.get("contract")
    if not code or not contract:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "code and contract required", "retriable": False}}), 400
    try:
        from backend.agent.research_loop import eval_entry_signal
        triggered, price = eval_entry_signal(code, contract)
        return jsonify({"code": 0, "data": {"code": code, "triggered": triggered, "price": price}, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/deep", methods=["POST"])
def deep_analyze():
    """Deep news analysis + LLM verdict for candidate stocks."""
    body = request.get_json(force=True, silent=True) or {}
    candidates = body.get("candidates", [])
    if not candidates:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "candidates list required", "retriable": False}}), 400
    try:
        from backend.strategy.stock_deep import deep_analyze
        result = deep_analyze(candidates)
        return jsonify({"code": 0, "data": result, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/portfolio/rebalance", methods=["POST"])
def portfolio_rebalance():
    """Preview portfolio rebalance: target weights + suggested trades."""
    body = request.get_json(force=True, silent=True) or {}
    account_id = body.get("account_id")
    if not account_id:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "account_id required", "retriable": False}}), 400
    try:
        from backend.trade_engine.engine import TradeEngine
        from backend.trade_engine.schema import get_db_path
        engine = TradeEngine(get_db_path())
        accounts = engine.list_accounts()
        account = next((a for a in accounts if a["account_id"] == account_id), None)
        if not account:
            return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "account not found", "retriable": False}}), 404

        positions = engine.get_positions(account_id)
        holdings = {p["code"]: p["qty"] for p in positions}
        cash = account["balance"]

        from backend.data_manager import fetch_realtime_prices
        codes = list(holdings.keys())
        prices_list = fetch_realtime_prices(codes) if codes else []
        prices = {p["code"]: p["price"] for p in prices_list}

        total_assets = cash + sum(holdings.get(c, 0) * prices.get(c, 0) for c in holdings)
        current_weights = {}
        for c, q in holdings.items():
            mv = q * prices.get(c, 0)
            current_weights[c] = mv / total_assets if total_assets > 0 else 0

        return jsonify({"code": 0, "data": {
            "account_id": account_id,
            "name": account["name"],
            "cash": cash,
            "total_assets": total_assets,
            "holdings": holdings,
            "prices": prices,
            "current_weights": current_weights,
        }, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/strategies", methods=["GET"])
def list_strategies():
    """List available strategy contracts with Chinese descriptions."""
    strategies = [
        {
            "id": "a_value",
            "name": "A价值",
            "kind": "multi_factor",
            "factors": ["BP", "EP", "REVERSAL_20"],
            "desc": "多因子价值+反转策略，适合震荡市",
            "rebalance_bars": 20,
            "top_k_pct": 0.2,
        },
        {
            "id": "b_momentum",
            "name": "B动量",
            "kind": "multi_factor",
            "factors": ["REVERSAL_60", "VOLATILITY_20", "PRICE_POS"],
            "desc": "趋势跟随+低波策略，适合牛市",
            "rebalance_bars": 20,
            "top_k_pct": 0.15,
        },
        {
            "id": "c_defensive",
            "name": "C防御",
            "kind": "multi_factor",
            "factors": ["BP", "VOLATILITY_20", "VOLUME_RATIO"],
            "desc": "低波+高股息防御策略，适合熊市",
            "rebalance_bars": 30,
            "top_k_pct": 0.1,
        },
    ]
    return jsonify({"code": 0, "data": strategies, "message": "ok"})
