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
    sid = request.args.get("strategy", "").strip()
    days = int_arg(request.args.get("days"), 500, 5, 5000)
    start_date = request.args.get("start", "").strip()   # YYYY-MM-DD 或 YYYYMMDD
    end_date = request.args.get("end", "").strip()
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    if not sid:
        return err(400, "missing_strategy", "需要 strategy 参数")
    try:
        from data_manager import get_kline_data
        from indicators import enrich_kline
        from backend.strategy.replay import replay_contract

        # 统一多取 warmup 根(指标/因子预热用): 默认回放最近 days 根, 预热段不出现在展示区
        warmup = 150
        kd = get_kline_data(code, days + warmup)
        if not kd:
            return err(404, "no_kline", f"{code} 无K线数据")
        kd = enrich_kline(kd)

        # 日期区间截取(含预热窗口): 展示区间= [start, end], 预热窗口取 start 前 150 根
        start_compact = start_date.replace("-", "")[:8] if start_date else ""
        end_compact = end_date.replace("-", "")[:8] if end_date else ""
        warmup_bars = 0
        if start_compact or end_compact:
            dates = [str(k.get("date", ""))[:8] for k in kd]
            lo = 0
            hi = len(kd)
            if start_compact:
                for i, d in enumerate(dates):
                    if d >= start_compact:
                        lo = i
                        break
            if end_compact:
                for i in range(len(dates) - 1, -1, -1):
                    if dates[i] <= end_compact:
                        hi = i + 1
                        break
            if start_compact:
                warmup_bars = max(0, lo)
                lo = max(0, lo - warmup)
            kd = kd[lo:hi]
            if not start_compact:
                warmup_bars = 0
            else:
                warmup_bars = min(warmup, warmup_bars)
        else:
            # 默认: 数据已多取 warmup 根, 优先保留 warmup 根作预热(均线/因子准确),
            # 展示段=预热后的全部(数据不足 days 则展示较少, 如早期上市股);
            # 不裁剪, 由 replay_contract 按 warmup_bars 跳过预热段输出展示区
            warmup_bars = warmup if len(kd) > warmup else 0

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

        # 单标的契约: 确保 universe 指向当前股票
        if contract.get("universe"):
            contract = dict(contract)
            contract["universe"] = dict(contract["universe"])
            contract["universe"]["code"] = code

        # 交易环境参数覆盖(前端可调)
        overrides = {}
        try:
            ib = float(request.args.get("initial_balance", "") or 0)
            if ib > 0:
                overrides["initial_balance"] = ib
        except ValueError:
            pass
        try:
            sl = float(request.args.get("slippage", "") or 0)
            if sl >= 0:
                overrides["slippage"] = sl
        except ValueError:
            pass
        fees_override = {}
        try:
            cr = float(request.args.get("commission_rate", "") or 0)
            if cr >= 0:
                fees_override["commission_rate"] = cr
        except ValueError:
            pass
        try:
            mc = float(request.args.get("min_commission", "") or 0)
            if mc >= 0:
                fees_override["min_commission"] = mc
        except ValueError:
            pass
        try:
            st = float(request.args.get("stamp_tax_rate", "") or 0)
            if st >= 0:
                fees_override["stamp_tax_rate"] = st
        except ValueError:
            pass
        if fees_override:
            overrides["fees"] = fees_override
        sm = request.args.get("sizing_mode", "").strip()
        if sm in ("percent_of_equity", "fixed_capital", "fixed_qty"):
            overrides["sizing_mode"] = sm
        try:
            sv = float(request.args.get("sizing_value", "") or 0)
            if sv > 0:
                overrides["sizing_value"] = sv
        except ValueError:
            pass

        result = replay_contract(kd, contract, overrides=overrides, warmup_bars=warmup_bars)
        if "error" in result:
            return err(500, "replay_error", result["error"])
        return ok(result)
    except Exception as e:
        return err(500, "replay_error", str(e))
