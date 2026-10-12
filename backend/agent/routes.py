# -*- coding: utf-8 -*-
"""Agent Gateway v1 — Flask Blueprint，挂载 /api/agent/v1。

能力分级：R(读) / W(工作区写) / B(回测) / T(交易, paper-only)。
回测走异步 job(提交→轮询→SSE 流)，变更类支持 Idempotency-Key。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from flask import Blueprint, Response, jsonify, request

from . import gateway as gw
from . import jobs as jobs_mod
from . import services as svc

agent_bp = Blueprint("agent_v1", __name__, url_prefix="/api/agent/v1")


def envelope(data=None, code=0, message="ok", meta=None):
    body = {"code": code, "data": data, "message": message}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body)


def error(http, code, message, retriable=False, details=None):
    body = {"code": http, "error": {"code": code, "message": message, "retriable": retriable}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), http


def _req_hash():
    return hashlib.sha256(request.get_data()).hexdigest() or "null"


def _idem_key():
    return request.headers.get("Idempotency-Key", "").strip()


# ── 健康 & 与我相关 ───────────────────────────────────────────────
@agent_bp.route("/health")
@gw.require_agent(gw.SCOPE_R)
def health():
    from ..data_manager import check_health
    return envelope({"status": "ok", "service": "stock-classroom-agent",
                     "time": datetime.now().isoformat(), "data": check_health()})


@agent_bp.route("/me/tokens")
@gw.require_agent(gw.SCOPE_R)
def my_tokens():
    rows = gw.list_tokens(request.agent_id)
    rows = [{**r, "token_hash": None, "full_token": None} for r in rows]
    return envelope(rows)


# ── 宏观 R ───────────────────────────────────────────────────────
@agent_bp.route("/macro/regime")
@gw.require_agent(gw.SCOPE_R)
def macro_regime():
    return envelope(svc.macro_regime())


@agent_bp.route("/macro/indicators")
@gw.require_agent(gw.SCOPE_R)
def macro_indicators():
    return envelope(svc.macro_indicators(request.args.get("category")))


# ── 目录 R ───────────────────────────────────────────────────────
@agent_bp.route("/catalog/stats")
@gw.require_agent(gw.SCOPE_R)
def catalog_stats():
    return envelope(svc.catalog_stats())


@agent_bp.route("/catalog/sectors")
@gw.require_agent(gw.SCOPE_R)
def catalog_sectors():
    return envelope(svc.catalog_sectors())


@agent_bp.route("/catalog/select")
@gw.require_agent(gw.SCOPE_R)
def catalog_select():
    kw = {k: request.args.get(k) for k in
          ("sector", "board", "status", "name_kw") if request.args.get(k)}
    try:
        return envelope({"items": svc.catalog_select(**kw), "count": 0})
    except ValueError as e:
        return error(400, "invalid_selector", str(e), details={"hint": "用 /catalog/sectors 枚举"})


@agent_bp.route("/catalog/describe/<code>")
@gw.require_agent(gw.SCOPE_R)
def catalog_describe(code):
    d = svc.catalog_describe(code)
    if not d:
        return error(404, "not_found", f"代码 {code} 不在目录中")
    return envelope(d)


@agent_bp.route("/catalog/search")
@gw.require_agent(gw.SCOPE_R)
def catalog_search():
    return envelope(svc.catalog_search(request.args.get("q", ""), int(request.args.get("limit", 30))))


@agent_bp.route("/catalog/boards")
@gw.require_agent(gw.SCOPE_R)
def catalog_boards():
    return envelope(svc.catalog_board_overview(int(request.args.get("limit", 20)),
                                               request.args.get("type")))


@agent_bp.route("/catalog/leader-of")
@gw.require_agent(gw.SCOPE_R)
def catalog_leader_of():
    d = svc.catalog_leader_of(request.args.get("name", ""))
    if not d:
        return error(404, "not_found", "未找到该板块")
    return envelope(d)


# ── 因子 & K线 R ─────────────────────────────────────────────────
@agent_bp.route("/factors")
@gw.require_agent(gw.SCOPE_R)
def factors():
    return envelope(svc.factors_list(request.args.get("category")))


@agent_bp.route("/klines")
@gw.require_agent(gw.SCOPE_R)
def klines():
    code = request.args.get("code", "").strip()
    if not code:
        return error(400, "missing_code", "需要 code")
    return envelope(svc.klines(code, int(request.args.get("days", 180))))


# ── 组合 R ───────────────────────────────────────────────────────
@agent_bp.route("/positions")
@gw.require_agent(gw.SCOPE_R)
def positions():
    return envelope(svc.portfolio_positions(request.agent_id))


# ── 声明式策略 W ──────────────────────────────────────────────────
@agent_bp.route("/strategies", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def list_strategies():
    return envelope(svc.list_strategies(request.agent_id))


@agent_bp.route("/strategies", methods=["POST"])
@gw.require_agent(gw.SCOPE_W)
def create_strategy():
    body = request.get_json(silent=True) or {}
    try:
        s = svc.create_strategy(request.agent_token_id, request.agent_id, body)
    except ValueError as e:
        return error(400, "invalid_contract", str(e))
    except Exception as e:
        return error(500, "strategy_create_failed", str(e))
    return envelope(s, code=0, message="created")


@agent_bp.route("/strategies/<int:sid>", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def get_strategy(sid):
    s = svc.get_strategy(request.agent_id, sid)
    if not s:
        return error(404, "not_found", "策略不存在")
    return envelope(s)


@agent_bp.route("/strategies/<int:sid>", methods=["PATCH"])
@gw.require_agent(gw.SCOPE_W)
def update_strategy(sid):
    body = request.get_json(silent=True) or {}
    try:
        s = svc.update_strategy(request.agent_id, sid, body)
    except ValueError as e:
        return error(400, "invalid_contract", str(e))
    if not s:
        return error(404, "not_found", "策略不存在")
    return envelope(s, code=0, message="updated")


@agent_bp.route("/strategies/<int:sid>", methods=["DELETE"])
@gw.require_agent(gw.SCOPE_W)
def delete_strategy(sid):
    if not svc.delete_strategy(request.agent_id, sid):
        return error(404, "not_found", "策略不存在")
    return envelope(sid, code=0, message="deleted")


# ── watchlist W ──────────────────────────────────────────────────
@agent_bp.route("/watchlist", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def watchlist_list():
    return envelope(svc.watchlist_list(request.agent_id))


@agent_bp.route("/watchlist", methods=["POST"])
@gw.require_agent(gw.SCOPE_W)
def watchlist_add():
    body = request.get_json(silent=True) or {}
    code = str(body.get("code", "")).strip()
    if not code:
        return error(400, "missing_code", "需要 code")
    return envelope(svc.watchlist_add(request.agent_token_id, request.agent_id,
                                      code, body.get("name", "")))


@agent_bp.route("/watchlist/<code>", methods=["DELETE"])
@gw.require_agent(gw.SCOPE_W)
def watchlist_remove(code):
    return envelope({"removed": svc.watchlist_remove(request.agent_id, code)})


# ── 异步回测 B ───────────────────────────────────────────────────
@agent_bp.route("/backtest/run", methods=["POST"])
@gw.require_agent(gw.SCOPE_B)
def run_backtest():
    body = request.get_json(silent=True) or {}
    sid = int(body.get("strategy_id") or 0)
    if not sid:
        return error(400, "missing_strategy_id", "需要 strategy_id")
    strategy = svc.get_strategy(request.agent_id, sid)
    if not strategy:
        return error(404, "not_found", "策略不存在")

    idem = _idem_key()
    if idem:
        reservation = gw.idempotency_reserve(request.agent_token_id, "POST",
                                             "/api/agent/v1/backtest/run", idem, _req_hash())
        if reservation["action"] == "replay":
            return envelope({"job_id": reservation["job_id"], "replayed": True, "status": "queued"})
        if reservation["action"] == "in_progress":
            return error(409, "idempotency_in_progress", "该幂等键任务仍在进行", retriable=True)

    runner = svc.build_backtest_runner(request.agent_id, sid)
    job = jobs_mod.submit_job("backtest", {"strategy_id": sid, "params": body.get("params") or {}},
                              runner, request.agent_token_id, request.agent_id,
                              idempotency_key=idem)
    if idem:
        gw.idempotency_complete(request.agent_token_id, "POST", "/api/agent/v1/backtest/run",
                                idem, job["job_id"], "succeeded")
    return envelope(job, code=0, message="backtest queued")


@agent_bp.route("/jobs/<job_id>", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def get_job(job_id):
    j = jobs_mod.get_job(job_id, request.agent_id)
    if not j:
        return error(404, "not_found", "job 不存在")
    return envelope(j)


@agent_bp.route("/jobs/<job_id>/stream", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def stream_job(job_id):
    since = int(request.args.get("since", 0))
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(jobs_mod.stream_job(job_id, request.agent_id, since),
                    mimetype="text/event-stream", headers=headers)


@agent_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
@gw.require_agent(gw.SCOPE_B)
def cancel_job(job_id):
    if not jobs_mod.cancel_job(job_id, request.agent_id):
        return error(409, "not_cancellable", "job 不可取消(不存在或已结束)")
    return envelope({"job_id": job_id, "status": "cancelled"})


@agent_bp.route("/jobs", methods=["GET"])
@gw.require_agent(gw.SCOPE_R)
def list_jobs():
    return envelope(jobs_mod.list_jobs(request.agent_id,
                                       kind=request.args.get("kind"),
                                       limit=int(request.args.get("limit", 50)),
                                       cursor=int(request.args.get("cursor", 0))))


# ── paper 交易 T(仅 paper) ───────────────────────────────────────
@agent_bp.route("/paper/orders", methods=["POST"])
@gw.require_agent(gw.SCOPE_T)
def paper_order():
    if not getattr(request, "agent_paper_only", True):
        return error(403, "live_not_enabled", "本部署仅 paper 交易(实盘未启用)")
    body = request.get_json(silent=True) or {}
    res = svc.paper_order(request.agent_token_id, request.agent_id, body,
                          paper_only=request.agent_paper_only)
    if "error" in res:
        return error(400, "order_rejected", res["error"], details=res.get("code"))
    return envelope(res, code=0, message="paper order accepted")


@agent_bp.route("/paper/kill-switch", methods=["POST"])
@gw.require_agent(gw.SCOPE_T)
def paper_kill_switch():
    """一键熔断：撤销该 agent 全部未成交 paper 单 + 吊销其全部 token。"""
    from ..trade_engine.engine import TradeEngine
    engine = TradeEngine()
    accounts = engine.list_accounts()
    cancelled = 0
    for a in accounts:
        if not a.get("is_active"):
            continue
        for o in engine.get_orders(a["id"], status="pending"):
            engine.cancel_order(o["id"])
            cancelled += 1
    revoked = gw.revoke_all_tokens(request.agent_id)  # 吊销该 agent 的全部 token
    return envelope({"cancelled_paper_orders": cancelled, "revoked_tokens": revoked,
                     "kill_switch_done": True})


def register(app):
    app.register_blueprint(agent_bp)
    return agent_bp
