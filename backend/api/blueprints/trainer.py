# -*- coding: utf-8 -*-
"""Trainer blueprint — K-line step-through trading simulator."""
import sys
import os
from flask import Blueprint, jsonify, request

bp = Blueprint("trainer", __name__, url_prefix="/api/trainer")

# Make trainer engine importable
_TRAINER_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "plugins", "trainer"))
if _TRAINER_DIR not in sys.path:
    sys.path.insert(0, _TRAINER_DIR)

# In-memory session store (per-server-process)
_sessions: dict = {}
_next_id = 1


@bp.route("/start", methods=["POST"])
def start_session():
    """Create a new training session with K-line data."""
    global _next_id
    body = request.get_json(force=True, silent=True) or {}
    code = body.get("code", "")
    days = body.get("days", 250)
    initial_balance = body.get("initial_balance", 100000)
    if not code:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "code required", "retriable": False}}), 400
    try:
        from backend.data_manager import get_kline_data
        bars = get_kline_data(code, days=days)
        if not bars:
            return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "no kline data", "retriable": False}}), 404
        from engine import TrainingEngine
        engine = TrainingEngine(bars, {"initial_balance": initial_balance})
        sid = _next_id
        _next_id += 1
        _sessions[sid] = {"engine": engine, "code": code, "bars": bars}
        return jsonify({"code": 0, "data": {"session_id": sid, "code": code, "total_bars": engine.total_bars, "snapshot": engine.snapshot()}, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500


@bp.route("/<int:sid>/step", methods=["POST"])
def step_forward(sid):
    """Step forward one bar."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    engine = s["engine"]
    engine.step()
    return jsonify({"code": 0, "data": {"snapshot": engine.snapshot(), "bar": engine.current_bar}, "message": "ok"})


@bp.route("/<int:sid>/step-back", methods=["POST"])
def step_back(sid):
    """Step back one bar."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    engine = s["engine"]
    engine.step_back()
    return jsonify({"code": 0, "data": {"snapshot": engine.snapshot(), "bar": engine.current_bar}, "message": "ok"})


@bp.route("/<int:sid>/goto", methods=["POST"])
def goto_bar(sid):
    """Jump to specific bar index."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    body = request.get_json(force=True, silent=True) or {}
    idx = body.get("idx", 0)
    engine = s["engine"]
    engine.goto(idx)
    return jsonify({"code": 0, "data": {"snapshot": engine.snapshot(), "bar": engine.current_bar}, "message": "ok"})


@bp.route("/<int:sid>/order", methods=["POST"])
def place_order(sid):
    """Place a buy/sell order at current bar."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    body = request.get_json(force=True, silent=True) or {}
    side = body.get("side", "long")
    qty = body.get("qty", 100)
    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")
    engine = s["engine"]
    order = engine.place_order(side, qty, stop_loss=stop_loss, take_profit=take_profit)
    if order is None:
        return jsonify({"code": 400, "data": None, "error": {"code": 400, "message": "cannot place order", "retriable": False}}), 400
    return jsonify({"code": 0, "data": {"snapshot": engine.snapshot(), "order": {"side": order.side, "qty": order.qty, "entry_price": order.entry_price}}, "message": "ok"})


@bp.route("/<int:sid>/cancel", methods=["POST"])
def cancel_order(sid):
    """Cancel an open order."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    body = request.get_json(force=True, silent=True) or {}
    idx = body.get("order_idx", 0)
    engine = s["engine"]
    if idx < len(engine.open_orders):
        engine.cancel_order(engine.open_orders[idx])
    return jsonify({"code": 0, "data": {"snapshot": engine.snapshot()}, "message": "ok"})


@bp.route("/<int:sid>/bars", methods=["GET"])
def get_bars(sid):
    """Get all K-line bars for chart rendering."""
    s = _sessions.get(sid)
    if not s:
        return jsonify({"code": 404, "data": None, "error": {"code": 404, "message": "session not found", "retriable": False}}), 404
    return jsonify({"code": 0, "data": s["bars"], "message": "ok"})


@bp.route("/<int:sid>", methods=["DELETE"])
def end_session(sid):
    """End and cleanup a training session."""
    _sessions.pop(sid, None)
    return jsonify({"code": 0, "data": None, "message": "ok"})
