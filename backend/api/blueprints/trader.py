# -*- coding: utf-8 -*-
"""Trader blueprint — AI 操盘手 (长期自主 LLM 交易员)。

GET  /api/trader/profile              操盘手档案 + 绑定账户
POST /api/trader/profile              更新人设/风险约束/开关
GET  /api/trader/state                概览: 档案 + 账户摘要 + 最新决策 + 统计
GET  /api/trader/decisions            历史决策列表
GET  /api/trader/decision/<date>      单日决策详情
GET  /api/trader/memory               长期记忆列表
POST /api/trader/memory/<id>/toggle   启用/停用一条记忆
POST /api/trader/run                  立即决策 (job)
GET  /api/trader/news                 今日市场快讯(预览)
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from .. import jobman

bp = Blueprint("trader", __name__, url_prefix="/api/trader")


def _profile():
    from backend.trader import account as acct_mod
    return acct_mod.ensure_profile()


def _summary(account_id: int) -> dict:
    try:
        from backend.trade_engine.engine import TradeEngine
        s = TradeEngine().get_summary(int(account_id)) or {}
        return {k: s.get(k) for k in (
            "account_id", "name", "initial_capital", "balance", "frozen", "market_value",
            "float_pnl", "total_assets", "total_profit", "total_profit_pct",
            "positions", "pending_orders", "total_trades")}
    except Exception as e:
        return {"error": str(e)[:120]}


def _run_decision(payload, on_progress):
    from backend.trader.daily import run_daily_decision
    return run_daily_decision(
        profile_id=(payload or {}).get("profile_id"),
        trigger=(payload or {}).get("trigger") or "manual",
        force=bool((payload or {}).get("force", True)),
        dry_run=bool((payload or {}).get("dry_run", False)),
        with_candidates=bool((payload or {}).get("with_candidates", True)),
        with_news=bool((payload or {}).get("with_news", True)),
        progress=lambda snap: on_progress(snap if isinstance(snap, dict) else {"msg": str(snap)}))


@bp.route("/profile", methods=["GET"])
def get_profile():
    p = _profile()
    if p is None:
        return err(500, "profile_init_failed", "操盘手档案初始化失败", retriable=False)
    return ok({"profile": p, "summary": _summary(p["account_id"])})


@bp.route("/profile", methods=["POST"])
def save_profile():
    from backend.trader import store
    body = request.get_json(force=True, silent=True) or {}
    p = _profile()
    fields = {}
    for k in ("name", "persona", "risk_rules", "auto_execute", "enabled"):
        if k in body:
            fields[k] = body[k]
    if not fields:
        return ok({"profile": p})
    updated = store.update_profile(int(p["id"]), **fields)
    return ok({"profile": updated})


@bp.route("/state", methods=["GET"])
def state():
    from backend.trader import store
    from backend.agent.llm_client import get_agent_config
    p = _profile()
    if p is None:
        return err(500, "profile_init_failed", "操盘手档案初始化失败", retriable=False)
    pid = int(p["id"])
    today = date.today().isoformat()
    cfg = get_agent_config()
    decisions = store.list_decisions(pid, limit=1)
    mem = store.list_memory(pid, active_only=True, limit=1)
    return ok({
        "profile": p,
        "summary": _summary(p["account_id"]),
        "today": today,
        "today_decision": store.get_decision(pid, today),
        "latest_decision": decisions[0] if decisions else None,
        "memory_count": len(mem) if mem is not None else 0,
        "llm_configured": bool(cfg.get("api_key") and cfg.get("api_base")),
        "model": cfg.get("model", ""),
    })


@bp.route("/decisions", methods=["GET"])
def decisions():
    from backend.trader import store
    p = _profile()
    limit = int_arg(request.args.get("limit"), 30, 1, 200)
    offset = int_arg(request.args.get("offset"), 0, 0, 100000)
    items = store.list_decisions(int(p["id"]), limit=limit, offset=offset)
    return ok({"items": items, "limit": limit, "offset": offset})


@bp.route("/decision/<trade_date>", methods=["GET"])
def decision_detail(trade_date: str):
    from backend.trader import store
    p = _profile()
    d = store.get_decision(int(p["id"]), trade_date)
    if d is None:
        return err(404, "not_found", "该日期没有决策记录", retriable=False)
    return ok(d)


@bp.route("/memory", methods=["GET"])
def memory():
    from backend.trader import store
    p = _profile()
    kind = request.args.get("kind") or None
    active = request.args.get("active", "1") not in ("0", "false", "False")
    items = store.list_memory(int(p["id"]), active_only=active, kind=kind)
    return ok({"items": items})


@bp.route("/memory/<int:mid>/toggle", methods=["POST"])
def toggle_memory(mid: int):
    from backend.trader import store
    body = request.get_json(force=True, silent=True) or {}
    store.set_memory_active(mid, bool(body.get("active", False)))
    return ok({"id": mid, "active": bool(body.get("active", False))})


@bp.route("/run", methods=["POST"])
def run():
    body = request.get_json(force=True, silent=True) or {}
    p = _profile()
    payload = {
        "profile_id": int(p["id"]),
        "trigger": "manual",
        "force": bool(body.get("force", True)),
        "dry_run": bool(body.get("dry_run", False)),
        "with_candidates": bool(body.get("with_candidates", True)),
        "with_news": bool(body.get("with_news", True)),
    }
    job = jobman.submit("trader", _run_decision, payload)
    return ok(job)


@bp.route("/news", methods=["GET"])
def news_preview():
    from backend.trader import news as news_mod
    limit = int_arg(request.args.get("limit"), 15, 1, 50)
    return ok({"items": news_mod.market_news(limit=limit)})
