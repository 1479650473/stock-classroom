# -*- coding: utf-8 -*-
"""Replay blueprint — 策略回放器 API.

GET  /api/replay/strategies           策略库列表(单标的契约 + 5家族组合策略)
GET  /api/replay?code=&strategy=&days=  回放数据(逐日信号/事件/持仓区间/指标)
"""
from __future__ import annotations

import sqlite3

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from ..paths import KLINE_DB

bp = Blueprint("replay", __name__, url_prefix="/api/replay")


def _agent_strategies() -> list:
    """agent.db 中真实 LLM 生成策略(去重: 同名保留最新), 加家族策略."""
    out = []
    try:
        import os, json
        from backend.agent.store import DB_PATH as AGENT_DB
        conn = sqlite3.connect(AGENT_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, description, contract FROM agent_strategies "
            "ORDER BY id DESC LIMIT 300").fetchall()
        conn.close()
        seen = set()
        for r in rows:
            nm = r["name"]
            if nm in seen:
                continue
            seen.add(nm)
            try:
                c = json.loads(r["contract"])
            except Exception:
                continue
            out.append({
                "id": f"db-{r['id']}",
                "name": nm,
                "kind": "single",
                "desc": (r["description"] or "")[:120],
                "contract": c,
            })
    except Exception:
        pass

    # 5 策略家族(组合策略, 回放时用单标的 DSL 近似契约, 见 replay.family_to_single_contract)
    from backend.strategy.replay import FAMILY_DSL
    for sid in FAMILY_DSL:
        out.append({
            "id": f"family-{sid}",
            "name": sid,
            "kind": "family",
            "desc": "5策略家族组合策略(单标的回放用近似条件)",
            "contract": None,
        })
    return out


@bp.route("/strategies", methods=["GET"])
def strategies():
    try:
        return ok(_agent_strategies())
    except Exception as e:
        return err(500, "replay_error", str(e))


@bp.route("", methods=["GET"])
def replay():
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 500, 5, 5000)
    sid = request.args.get("strategy", "").strip()
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    if not sid:
        return err(400, "missing_strategy", "需要 strategy 参数")
    try:
        from data_manager import get_kline_data
        from indicators import enrich_kline
        from backend.strategy.replay import replay_contract

        kd = get_kline_data(code, days)
        if not kd:
            return err(404, "no_kline", f"{code} 无K线数据")
        kd = enrich_kline(kd)

        contract = None
        if sid.startswith("db-"):
            import os, json
            from backend.agent.store import DB_PATH as AGENT_DB
            sid_id = sid[3:]
            conn = sqlite3.connect(AGENT_DB, timeout=10)
            row = conn.execute(
                "SELECT contract FROM agent_strategies WHERE id=?", (sid_id,)).fetchone()
            conn.close()
            if row:
                try:
                    contract = json.loads(row[0])
                except Exception:
                    contract = None
        elif sid.startswith("family-"):
            from backend.strategy.replay import family_to_single_contract
            contract = family_to_single_contract(sid[7:])

        if not contract:
            return err(404, "strategy_not_found", f"策略不存在: {sid}")

        # 单标的契约: 确保 universe 指向当前股票(回放时只影响名称显示)
        if contract.get("universe"):
            contract = dict(contract)
            contract["universe"] = dict(contract["universe"])
            contract["universe"]["code"] = code

        result = replay_contract(kd, contract)
        if "error" in result:
            return err(500, "replay_error", result["error"])
        return ok(result)
    except Exception as e:
        return err(500, "replay_error", str(e))
