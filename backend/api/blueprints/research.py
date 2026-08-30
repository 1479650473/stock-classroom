# -*- coding: utf-8 -*-
"""Research blueprint — regime, metrics, strategy describe."""
from flask import Blueprint, jsonify, request

bp = Blueprint("research", __name__, url_prefix="/api/research")


@bp.route("/regime", methods=["GET"])
def get_regime():
    """Current market regime (bull/bear/range) from HS300."""
    try:
        from backend.strategy.regime import run as regime_run
        data = regime_run()
        return jsonify({"code": 0, "data": data, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/metrics", methods=["POST"])
def compute_metrics():
    """Compute full metrics from a NAV sequence."""
    body = request.get_json(force=True, silent=True) or {}
    nav = body.get("nav")
    if not nav or not isinstance(nav, list) or len(nav) < 2:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "nav must be a list with >=2 points", "retriable": False}}), 400
    try:
        from backend.strategy.metrics import full_metrics
        bench = body.get("bench")
        dates = body.get("dates")
        result = full_metrics(nav, bench=bench, dates=dates)
        return jsonify({"code": 0, "data": result, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/strategy/describe", methods=["POST"])
def describe_strategy():
    """Describe a strategy contract in Chinese."""
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "empty body", "retriable": False}}), 400
    try:
        from backend.strategy.describe import describe_contract
        data = describe_contract(body)
        return jsonify({"code": 0, "data": data, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/factors", methods=["GET"])
def get_factors():
    """List available factor groups and descriptions."""
    factors = [
        {"id": "BP", "name": "市净率倒数", "group": "价值", "desc": "股价/每股净资产的倒数，越高越便宜"},
        {"id": "EP", "name": "市盈率倒数", "group": "价值", "desc": "每股收益/股价，越高越便宜"},
        {"id": "REVERSAL_20", "name": "20日反转", "group": "动量", "desc": "过去20日收益率取反，捕捉超跌反弹"},
        {"id": "REVERSAL_60", "name": "60日反转", "group": "动量", "desc": "过去60日收益率取反"},
        {"id": "VOLATILITY_20", "name": "20日波动率", "group": "风险", "desc": "20日收益率标准差，低波优先"},
        {"id": "VOLUME_RATIO", "name": "量比", "group": "情绪", "desc": "当日成交量/5日均量"},
        {"id": "PRICE_POS", "name": "价格位置", "group": "技术", "desc": "当前价在20日高低点中的位置"},
    ]
    return jsonify({"code": 0, "data": factors, "message": "ok"})


@bp.route("/strategies", methods=["GET"])
def get_strategies():
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
