# -*- coding: utf-8 -*-
"""基金套利（LOF 折溢价）blueprint。

GET  /api/fund-arb/overview                 概览（机会计数 / Top 列表 / 数据状态）
GET  /api/fund-arb/list                     机会表（可排序口径，参数化成本模型）
GET  /api/fund-arb/fund/<code>              单只明细（费率表/门槛/成本拆解/历史折溢价）
GET  /api/fund-arb/stats                    数据状态
POST /api/fund-arb/sync                     同步数据（job；mode=daily|fees|backfill|list）
"""
from __future__ import annotations

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from .. import jobman

bp = Blueprint("fund_arb", __name__, url_prefix="/api/fund-arb")

_NUM_KEYS = ("amount", "commission_rate", "commission_min", "buy_fee_discount",
             "transfer_fee", "slippage_ticks", "premium_days", "discount_days", "min_liquidity")


def _cfg_from_args(args) -> dict:
    cfg = {}
    for k in _NUM_KEYS:
        v = args.get(k)
        if v is None or v == "":
            continue
        try:
            cfg[k] = float(v)
        except (TypeError, ValueError):
            continue
    for k in ("premium_days", "discount_days"):
        if k in cfg:
            cfg[k] = int(cfg[k])
    return cfg


@bp.route("/overview")
def overview():
    from backend.fund import arb
    try:
        return ok(arb.overview())
    except Exception as e:  # noqa: BLE001
        return err(500, "arb_error", str(e))


@bp.route("/list")
def listing():
    from backend.fund import arb
    direction = (request.args.get("direction") or "").strip() or None
    if direction not in (None, "premium", "discount"):
        return err(400, "bad_direction", "direction 只能是 premium / discount")
    try:
        min_space = float(request.args.get("min_space") or 0)
    except ValueError:
        min_space = 0.0
    only_open = request.args.get("only_open") in ("1", "true", "yes")
    limit = int_arg(request.args.get("limit"), 300, 1, 2000)
    try:
        res = arb.opportunities(_cfg_from_args(request.args), direction=direction,
                                min_space=min_space, only_open=only_open, limit=limit)
        return ok(res)
    except Exception as e:  # noqa: BLE001
        return err(500, "arb_error", str(e))


@bp.route("/fund/<code>")
def fund_detail(code: str):
    from backend.fund import arb
    hist_days = int_arg(request.args.get("hist_days"), 250, 20, 2000)
    try:
        d = arb.fund_detail(code.strip(), _cfg_from_args(request.args), hist_days=hist_days)
        if not d:
            return err(404, "not_found", f"没有这只 LOF 的数据：{code}")
        return ok(d)
    except Exception as e:  # noqa: BLE001
        return err(500, "arb_error", str(e))


@bp.route("/stats")
def stats():
    from backend.fund import store
    try:
        return ok(store.stats())
    except Exception as e:  # noqa: BLE001
        return err(500, "arb_error", str(e))


def _sync_runner(payload, on_progress):
    from backend.fund import sync as FS
    mode = (payload or {}).get("mode", "daily")
    on_progress({"stage": f"sync:{mode}"})
    if mode == "backfill":
        return FS.backfill(workers=int((payload or {}).get("workers", 4)))
    if mode == "fees":
        return FS.refresh_fees(workers=int((payload or {}).get("workers", 3)))
    if mode == "list":
        return FS.sync_list()
    return FS.run_daily(workers=int((payload or {}).get("workers", 4)))


@bp.route("/sync", methods=["POST", "GET"])
def sync():
    body = request.get_json(force=True, silent=True) or {}
    mode = str(body.get("mode") or request.args.get("mode") or "daily")
    if mode not in ("daily", "fees", "backfill", "list"):
        return err(400, "bad_mode", "mode 只能是 daily / fees / backfill / list")
    job = jobman.submit("fund_arb", _sync_runner, {"mode": mode, "workers": int(body.get("workers") or 4)})
    return ok({"job": job, "mode": mode})
