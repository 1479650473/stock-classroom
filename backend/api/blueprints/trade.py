# -*- coding: utf-8 -*-
"""Simulated trading — accounts / orders / positions / trades / nav.

Wraps backend.trade_engine.engine.TradeEngine. All endpoints are paper-only.
"""
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("trade", __name__, url_prefix="/api/trade")


def _engine():
    from backend.trade_engine.engine import TradeEngine
    return TradeEngine()


# ── 账户 ─────────────────────────────────────────────────────────
@bp.route("/accounts", methods=["GET"])
def list_accounts():
    try:
        return ok(_engine().list_account_summaries())
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts", methods=["POST"])
def create_account():
    import math
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    try:
        cap = float(body.get("initial_capital", 100000))
    except (TypeError, ValueError):
        return err(400, "bad_capital", "initial_capital 必须是数字")
    if not name:
        return err(400, "missing_name", "需要账户名称")
    if not math.isfinite(cap) or cap <= 0:
        return err(400, "bad_capital", "initial_capital 必须是正数")
    try:
        acc = _engine().create_account(name, int(cap))
        return ok(acc, message="created")
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>", methods=["GET"])
def get_account(aid):
    acc = _engine().get_account(aid)
    if not acc:
        return err(404, "not_found", "账户不存在")
    return ok(acc)


@bp.route("/accounts/<int:aid>/rename", methods=["POST"])
def rename_account(aid):
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return err(400, "missing_name", "需要新名称")
    eng = _engine()
    if not eng.get_account(aid):
        return err(404, "not_found", "账户不存在")
    eng.rename_account(aid, name)
    return ok({"id": aid, "name": name}, message="renamed")


@bp.route("/accounts/<int:aid>/reset", methods=["POST"])
def reset_account(aid):
    eng = _engine()
    if not eng.get_account(aid):
        return err(404, "not_found", "账户不存在")
    eng.reset_account(aid)
    return ok({"id": aid}, message="reset")


@bp.route("/accounts/<int:aid>", methods=["DELETE"])
def delete_account(aid):
    eng = _engine()
    if not eng.get_account(aid):
        return err(404, "not_found", "账户不存在")
    eng.delete_account(aid)
    return ok({"id": aid}, message="deleted")


# ── 摘要 / 持仓 / 委托 / 成交 / 净值 ──────────────────────────────
@bp.route("/accounts/<int:aid>/summary")
def summary(aid):
    try:
        return ok(_engine().get_summary(aid))
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>/positions")
def positions(aid):
    try:
        return ok(_engine().get_positions(aid))
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>/orders")
def orders(aid):
    status = request.args.get("status")
    limit = int_arg(request.args.get("limit"), 100, 1, 500)
    try:
        return ok(_engine().get_orders(aid, status=status, limit=limit))
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>/trades")
def trades(aid):
    limit = int_arg(request.args.get("limit"), 100, 1, 500)
    try:
        return ok(_engine().get_trades(aid, limit=limit))
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>/nav")
def nav(aid):
    try:
        return ok(_engine().get_nav_history(aid))
    except Exception as e:
        return err(500, "trade_error", str(e))


# ── 下单 / 撤单 / 刷新价格 ─────────────────────────────────────────
@bp.route("/orders", methods=["POST"])
def place_order():
    body = request.get_json(silent=True) or {}
    aid_raw = body.get("account_id")
    if aid_raw is None:
        return err(400, "invalid_body", "需要 account_id")
    try:
        aid = int(aid_raw)
        code = str(body.get("code", "")).strip()
        side = str(body.get("side", "")).strip().lower()
        qty = int(body.get("qty", 0))
    except (TypeError, ValueError):
        return err(400, "invalid_body", "参数不完整")
    if not code or side not in ("buy", "sell") or qty <= 0:
        return err(400, "invalid_body", "需要 code / side(buy|sell) / qty>0")
    order_type = str(body.get("order_type", "market")).lower()
    price = float(body.get("price") or 0)
    name = str(body.get("name", ""))

    # 市价单需要 current_price 才能立即撮合 -> 拉实时价
    current_price = None
    if order_type == "market":
        try:
            from data_manager import fetch_realtime_prices
            quotes = fetch_realtime_prices([code])
            if quotes and quotes[0].get("price"):
                current_price = float(quotes[0]["price"])
        except Exception as e:
            return err(502, "quote_error", f"实时价获取失败: {e}", retriable=True)
        if not current_price:
            return err(502, "quote_error", "实时价获取失败", retriable=True)

    try:
        res = _engine().place_order(aid, code, name, side, order_type, price, qty,
                                    current_price=current_price)
    except Exception as e:
        return err(500, "trade_error", str(e))
    order, info = res if isinstance(res, tuple) else (res, None)
    if order is None:
        return err(400, "order_rejected", str(info or "下单被拒绝"))
    return ok({"order": order, "trade": info}, message="order accepted")


@bp.route("/orders/<int:oid>/cancel", methods=["POST"])
def cancel_order(oid):
    try:
        res = _engine().cancel_order(oid)
        return ok(res, message="cancelled")
    except Exception as e:
        return err(500, "trade_error", str(e))


@bp.route("/accounts/<int:aid>/refresh-prices", methods=["POST"])
def refresh_prices(aid):
    """Pull realtime quotes for current positions and update market values."""
    try:
        eng = _engine()
        poss = eng.get_positions(aid)
        codes = [p["code"] for p in poss]
        if not codes:
            return ok({"updated": 0})
        from data_manager import fetch_realtime_prices
        quotes = fetch_realtime_prices(codes)
        price_map = {q["code"]: q["price"] for q in quotes if q.get("price")}
        eng.update_all_prices(aid, price_map)
        return ok({"updated": len(price_map)})
    except Exception as e:
        return err(502, "quote_error", str(e), retriable=True)
