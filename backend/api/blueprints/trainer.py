# -*- coding: utf-8 -*-
"""Trainer blueprint — K-line step-through trading simulator."""
import sys
import os
import threading
import time
from flask import Blueprint, request

from ..envelope import ok, err

bp = Blueprint("trainer", __name__, url_prefix="/api/trainer")

# Make trainer engine importable (原 PyQt5 旧版从 frontend/plugins/trainer 的 engine import,
# 已统一为 backend.trainer_engine; 此处 import 仅保证模块注册)
import backend.trainer_engine  # noqa: F401

# In-memory session store (per-server-process) + TTL 清理
_sessions: dict = {}
_sessions_lock = threading.Lock()
_next_id = 1
_SESSION_TTL = 6 * 3600  # 6 小时未活跃自动回收
_cleanup_at = 0.0


def _cleanup():
    """惰性回收过期训练会话(无请求会话持续挂内存)."""
    global _cleanup_at
    now = time.time()
    if now - _cleanup_at < 3600:
        return
    _cleanup_at = now
    with _sessions_lock:
        for sid in [s for s, v in _sessions.items() if now - v["last_used"] > _SESSION_TTL]:
            _sessions.pop(sid, None)


def _session(sid):
    _cleanup()
    s = _sessions.get(sid)
    if s:
        s["last_used"] = time.time()
    return s


@bp.route("/start", methods=["POST"])
def start_session():
    """Create a new training session with K-line data."""
    global _next_id
    body = request.get_json(force=True, silent=True) or {}
    code = body.get("code", "")
    days = body.get("days", 250)
    initial_balance = body.get("initial_balance", 100000)
    if not code:
        return err(400, "missing_code", "code required", retriable=False)
    try:
        from backend.data_manager import get_kline_data
        bars = get_kline_data(code, days=days)
        if not bars:
            return err(404, "not_found", "no kline data", retriable=False)
        from backend.trainer_engine import TrainingEngine
        engine = TrainingEngine(bars, {"initial_balance": initial_balance})
        with _sessions_lock:
            sid = _next_id
            _next_id += 1
            _sessions[sid] = {"engine": engine, "code": code, "bars": bars,
                              "last_used": time.time()}
        return ok({"session_id": sid, "code": code, "total_bars": engine.total_bars,
                   "snapshot": engine.snapshot()})
    except Exception as e:
        return err(500, "trainer_start_failed", str(e), retriable=False)


@bp.route("/<int:sid>/step", methods=["POST"])
def step_forward(sid):
    """Step forward one bar."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    engine = s["engine"]
    engine.step()
    return ok({"snapshot": engine.snapshot(), "bar": engine.current_bar})


@bp.route("/<int:sid>/step-back", methods=["POST"])
def step_back(sid):
    """Step back one bar."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    engine = s["engine"]
    engine.step_back()
    return ok({"snapshot": engine.snapshot(), "bar": engine.current_bar})


@bp.route("/<int:sid>/goto", methods=["POST"])
def goto_bar(sid):
    """Jump to specific bar index."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    body = request.get_json(force=True, silent=True) or {}
    idx = body.get("idx", 0)
    engine = s["engine"]
    engine.goto(idx)
    return ok({"snapshot": engine.snapshot(), "bar": engine.current_bar})


@bp.route("/<int:sid>/order", methods=["POST"])
def place_order(sid):
    """Place a buy/sell order at current bar."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    body = request.get_json(force=True, silent=True) or {}
    side = body.get("side", "long")
    qty = body.get("qty", 100)
    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")
    engine = s["engine"]
    order = engine.place_order(side, qty, stop_loss=stop_loss, take_profit=take_profit)
    if order is None:
        return err(400, "order_rejected", "cannot place order", retriable=False)
    return ok({"snapshot": engine.snapshot(),
               "order": {"side": order.side, "qty": order.qty, "entry_price": order.entry_price}})


@bp.route("/<int:sid>/cancel", methods=["POST"])
def cancel_order(sid):
    """Cancel an open order."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    body = request.get_json(force=True, silent=True) or {}
    idx = body.get("order_idx", 0)
    engine = s["engine"]
    if 0 <= idx < len(engine.open_orders):
        engine.cancel_order(engine.open_orders[idx])
    return ok({"snapshot": engine.snapshot()})


@bp.route("/<int:sid>/bars", methods=["GET"])
def get_bars(sid):
    """Get all K-line bars for chart rendering."""
    s = _session(sid)
    if not s:
        return err(404, "not_found", "session not found", retriable=False)
    return ok(s["bars"])


@bp.route("/<int:sid>", methods=["DELETE"])
def end_session(sid):
    """End and cleanup a training session."""
    with _sessions_lock:
        _sessions.pop(sid, None)
    return ok(None)
