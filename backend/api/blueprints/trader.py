# -*- coding: utf-8 -*-
"""Trader blueprint — AI 操盘手 (长期自主 LLM 交易员，支持多个)。

GET    /api/trader/profiles               全部交易员列表(含账户摘要)
POST   /api/trader/profiles               新建交易员 {name, initial_capital, model, persona}
POST   /api/trader/profiles/<id>          更新交易员 {name, model, persona, enabled, ...}
DELETE /api/trader/profiles/<id>          删除交易员(含账户/决策/记忆，不可恢复)
GET    /api/trader/overview               总览: 各交易员净值曲线 + 沪深300 对比 + 统计
GET    /api/trader/state?profile_id=      单交易员概览
GET    /api/trader/decisions?profile_id=  历史决策列表
GET    /api/trader/decision/<date>?profile_id=
GET    /api/trader/memory?profile_id=
POST   /api/trader/memory/<id>/toggle
POST   /api/trader/run                    指定交易员立即决策 (job)
POST   /api/trader/run-all                所有启用交易员依次决策 (job)
GET    /api/trader/news                   今日市场快讯(预览)
"""
from __future__ import annotations

import json
import os
from datetime import date

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from .. import jobman
from ..paths import DATA_DIR

bp = Blueprint("trader", __name__, url_prefix="/api/trader")

HS300_PATH = os.path.join(DATA_DIR, "hs300.json")


def _require_profile(profile_id):
    from backend.trader import store
    pid = int(profile_id or 0)
    p = store.get_profile(pid) if pid else store.get_profile()
    if p is None:
        return None
    return p


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


# ───────────────────────── profiles CRUD ─────────────────────────

@bp.route("/profiles", methods=["GET"])
def profiles():
    from backend.trader import account as acct_mod
    items = acct_mod.list_traders()
    return ok({"items": items})


@bp.route("/profiles", methods=["POST"])
def create_profile():
    from backend.trader import account as acct_mod
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name") or "").strip() or "AI操盘手"
    cap = float(body.get("initial_capital") or 100000)
    model = str(body.get("model") or "").strip()
    persona = str(body.get("persona") or "").strip()
    try:
        p = acct_mod.create_trader(name, cap, model=model, persona=persona)
    except Exception as e:
        return err(500, "trader_create_failed", str(e)[:200], retriable=False)
    return ok({"profile": p, "summary": _summary(p["account_id"])})


@bp.route("/profiles/<int:pid>", methods=["POST"])
def update_profile(pid: int):
    from backend.trader import store
    body = request.get_json(force=True, silent=True) or {}
    if pid <= 0:
        return err(400, "bad_profile_id", "profile_id 非法", retriable=False)
    p = store.get_profile(pid)
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    fields = {}
    for k in ("name", "persona", "model", "enabled", "risk_rules", "auto_execute"):
        if k in body:
            fields[k] = body[k]
    if fields:
        p = store.update_profile(pid, **fields)
    return ok({"profile": p})


@bp.route("/profiles/<int:pid>", methods=["DELETE"])
def delete_profile(pid: int):
    from backend.trader import account as acct_mod
    if pid <= 0:
        return err(400, "bad_profile_id", "profile_id 非法", retriable=False)
    okk = acct_mod.delete_trader(pid)
    if not okk:
        return err(404, "not_found", "交易员不存在", retriable=False)
    return ok({"deleted": pid})


# ───────────────────────── overview ─────────────────────────

def _hs300_series() -> dict:
    try:
        with open(HS300_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {"dates": d.get("dates") or [], "closes": [float(x) for x in d.get("closes") or []]}
    except Exception:
        return {"dates": [], "closes": []}


@bp.route("/overview", methods=["GET"])
def overview():
    from backend.trader import account as acct_mod
    from backend.trade_engine.engine import TradeEngine
    engine = TradeEngine()
    traders = []
    for p in acct_mod.list_traders():
        nav = engine.get_nav_history(int(p["account_id"])) or {}
        vals = []
        for d_, n_, ta in zip(nav.get("dates", []), nav.get("nav", []), nav.get("total_assets", [])):
            vals.append({"date": d_, "nav": round(float(n_), 5),
                         "total_assets": round(float(ta), 2)})
        s = p.get("summary") or {}
        traders.append({
            "profile_id": p["id"], "name": p["name"], "model": p.get("model") or "",
            "enabled": p.get("enabled", 1), "created_at": p.get("created_at"),
            "initial_capital": s.get("initial_capital") or p.get("initial_capital"),
            "summary": s,
            "nav": vals,
            "nav_format": "倍数",
        })
    hs = _hs300_series()
    # 基准归一：以所有交易员第一条净值日期的沪深300值为 1.0（无交易数据时用整体首日）
    trader_dates = sorted({v["date"] for t in traders for v in t["nav"]})
    bench = {"dates": hs["dates"], "values": []}
    if hs["dates"] and hs["closes"]:
        base_idx = 0
        if trader_dates:
            # 找 >= 最早交易日的第一个基准点
            for i, dd in enumerate(hs["dates"]):
                if dd >= trader_dates[0]:
                    base_idx = i
                    break
        base = hs["closes"][base_idx] or 1.0
        bench["values"] = [round(c / base, 5) for c in hs["closes"]]
    return ok({
        "as_of": date.today().isoformat(),
        "benchmark": {"name": "沪深300", **bench},
        "traders": traders,
    })


# ───────────────────────── 单交易员 ─────────────────────────

def _pid_arg():
    v = request.args.get("profile_id") or request.args.get("pid")
    if v:
        try:
            return int(v)
        except Exception:
            return 0
    return 0


@bp.route("/state", methods=["GET"])
def state():
    from backend.trader import store
    from backend.agent.llm_client import get_agent_config
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    pid = int(p["id"])
    today = date.today().isoformat()
    cfg = get_agent_config()
    decisions = store.list_decisions(pid, limit=1)
    mem_count = len(store.list_memory(pid, active_only=True, limit=10000))
    return ok({
        "profile": p,
        "summary": _summary(p["account_id"]),
        "today": today,
        "today_decision": store.get_decision(pid, today),
        "latest_decision": decisions[0] if decisions else None,
        "memory_count": mem_count,
        "llm_configured": bool(cfg.get("api_key") and cfg.get("api_base")),
        "model": p.get("model") or cfg.get("model", ""),
        "default_model": cfg.get("model", ""),
    })


@bp.route("/decisions", methods=["GET"])
def decisions():
    from backend.trader import store
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    limit = int_arg(request.args.get("limit"), 30, 1, 200)
    offset = int_arg(request.args.get("offset"), 0, 0, 100000)
    items = store.list_decisions(int(p["id"]), limit=limit, offset=offset)
    return ok({"items": items, "limit": limit, "offset": offset})


@bp.route("/decision/<trade_date>", methods=["GET"])
def decision_detail(trade_date: str):
    from backend.trader import store
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    d = store.get_decision(int(p["id"]), trade_date)
    if d is None:
        return err(404, "not_found", "该日期没有决策记录", retriable=False)
    return ok(d)


@bp.route("/memory", methods=["GET"])
def memory():
    from backend.trader import store
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
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


def _run_all(payload, on_progress):
    from backend.trader.daily import run_all_daily_decisions
    return {"results": run_all_daily_decisions(
        trigger=(payload or {}).get("trigger") or "manual",
        force=bool((payload or {}).get("force", True)),
        dry_run=bool((payload or {}).get("dry_run", False)),
        progress=lambda snap: on_progress(snap if isinstance(snap, dict) else {"msg": str(snap)}))}


@bp.route("/run", methods=["POST"])
def run():
    body = request.get_json(force=True, silent=True) or {}
    pid = int(body.get("profile_id") or 0)
    p = _require_profile(pid)
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
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


@bp.route("/run-all", methods=["POST"])
def run_all():
    body = request.get_json(force=True, silent=True) or {}
    payload = {
        "trigger": "manual",
        "force": bool(body.get("force", True)),
        "dry_run": bool(body.get("dry_run", False)),
    }
    job = jobman.submit("trader_all", _run_all, payload)
    return ok(job)


@bp.route("/news", methods=["GET"])
def news_preview():
    from backend.trader import news as news_mod
    limit = int_arg(request.args.get("limit"), 15, 1, 50)
    return ok({"items": news_mod.market_news(limit=limit)})


@bp.route("/selection", methods=["GET"])
def selection_preview():
    """选股链路审计：候选股从哪来、被什么规则过滤、按什么口径打分。

    参数: date=YYYY-MM-DD 时按该日 as-of 截断（回放/回测），不传则用最新数据。
    """
    from backend.trader.selection import build_snapshot
    ref = request.args.get("date") or None
    top_n = int_arg(request.args.get("top"), 12, 1, 50)
    weights = request.args.get("weights") or None
    source = str(request.args.get("source") or "scorecard")
    return ok(build_snapshot(ref, top_n=top_n, with_events=not ref, weights=weights, source=source))


@bp.route("/rules", methods=["GET"])
def rules():
    """当前生效的纪律规则（自省结论 → 交易系统强制执行）。"""
    from backend.trader import discipline
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    ref = request.args.get("date") or None
    rs = discipline.active_rules(int(p["id"]), ref)
    return ok({"profile_id": int(p["id"]), "as_of": ref or "最新",
               "protection": discipline.protection_rules(int(p["id"]), ref),
               "presets": {k: v for k, v in discipline.DEFAULT_PROTECTION.items()},
               "rules": discipline.describe_rules(rs)})


@bp.route("/performance", methods=["GET"])
def performance():
    """交易员战绩：胜率/盈亏比/回撤/最近已平仓交易（自我提升的依据）。"""
    from backend.trader.performance import performance_block
    p = _require_profile(_pid_arg())
    if p is None:
        return err(404, "not_found", "交易员不存在", retriable=False)
    ref = request.args.get("date") or None
    return ok(performance_block(int(p["id"]), int(p["account_id"]), as_of=ref))


# ───────────────────────── 纵向回放 ─────────────────────────

def _run_replay(payload, on_progress):
    from backend.trader.replay import run_replay_batch
    return run_replay_batch(
        int((payload or {}).get("run_id") or 0),
        days=int((payload or {}).get("days") or 30),
        progress=lambda snap: on_progress(snap if isinstance(snap, dict) else {"msg": str(snap)}))


@bp.route("/replays", methods=["GET"])
def replays():
    from backend.trader import account as acct_mod
    return ok({"items": acct_mod.list_traders(kind="replay")})


@bp.route("/replay", methods=["POST"])
def create_replay_run():
    from backend.trader.replay import create_replay
    body = request.get_json(force=True, silent=True) or {}
    try:
        prof = create_replay(
            int(body.get("source_profile_id") or 0),
            str(body.get("start_date") or "").strip(),
            days=int(body.get("days") or 30),
            initial_capital=body.get("initial_capital"),
            model=body.get("model"),
            weights=body.get("weights"),
        )
    except Exception as e:
        return err(400, "replay_create_failed", str(e)[:200], retriable=False)
    job = jobman.submit("trader_replay", _run_replay,
                        {"run_id": int(prof["id"]), "days": int(body.get("days") or 30)})
    return ok({"profile": prof, "job": job})


@bp.route("/replay/<int:rid>", methods=["GET"])
def replay_detail(rid: int):
    from backend.trader import store
    from backend.trade_engine.engine import TradeEngine
    p = store.get_profile(rid)
    if p is None or p.get("kind") != "replay":
        return err(404, "not_found", "回放档案不存在", retriable=False)
    eng = TradeEngine()
    nav = eng.get_nav_history(int(p["account_id"])) or {}
    nav_rows = [{"date": d, "nav": n, "total_assets": ta}
                for d, n, ta in zip(nav.get("dates", []), nav.get("nav", []), nav.get("total_assets", []))]
    decisions = store.list_decisions(rid, limit=int_arg(request.args.get("limit"), 60, 1, 400))
    perf, mem = {}, []
    try:
        from backend.trader.performance import performance_block
        perf = performance_block(rid, int(p["account_id"]))
    except Exception:
        perf = {}
    try:
        mem = store.list_memory(rid, active_only=True, limit=60)
    except Exception:
        mem = []
    return ok({"profile": p, "summary": _summary(p["account_id"]),
               "nav": nav_rows, "decisions": decisions,
               "performance": perf, "memory": mem})


@bp.route("/replay/<int:rid>/continue", methods=["POST"])
def continue_replay(rid: int):
    from backend.trader import store
    body = request.get_json(force=True, silent=True) or {}
    p = store.get_profile(rid)
    if p is None or p.get("kind") != "replay":
        return err(404, "not_found", "回放档案不存在", retriable=False)
    days = int(body.get("days") or 30)
    job = jobman.submit("trader_replay", _run_replay, {"run_id": rid, "days": days})
    return ok({"job": job})


@bp.route("/replay/<int:rid>/distill", methods=["POST"])
def distill_replay(rid: int):
    from backend.trader.replay import distill_to_live
    body = request.get_json(force=True, silent=True) or {}
    target = int(body.get("target_profile_id") or 0)
    if not target:
        return err(400, "missing_target", "target_profile_id 必填", retriable=False)
    r = distill_to_live(rid, target)
    if r.get("error"):
        return err(400, "distill_failed", r["error"], retriable=False)
    return ok(r)
