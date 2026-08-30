# -*- coding: utf-8 -*-
"""Market data: indices, sectors, north flow, news, realtime quotes."""
from flask import Blueprint, request

from ..envelope import ok, err

bp = Blueprint("market", __name__, url_prefix="/api/market")

_MAIN_INDEX = {"sh000001", "sz399001", "sz399006"}


@bp.route("/indices")
def indices():
    try:
        from akshare_source import ak_get_index_spot
        data = ak_get_index_spot()
        main = [d for d in data if d.get("code") in _MAIN_INDEX]
        if not main:
            from data_manager import fetch_index_prices
            main = fetch_index_prices()
        return ok(main, source=(main[0].get("source", "sina") if main else "none"))
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/all-index")
def all_index():
    try:
        from akshare_source import ak_get_index_spot
        return ok(ak_get_index_spot())
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/sectors")
def sectors():
    sector_type = request.args.get("type", "industry")
    try:
        from akshare_source import ak_get_sectors
        return ok(ak_get_sectors(sector_type), type=sector_type)
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/north-flow")
def north_flow():
    days = int(request.args.get("days", 30))
    try:
        from akshare_source import ak_get_north_flow
        return ok(ak_get_north_flow(days))
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/news")
def news():
    code = request.args.get("code", "000001")
    limit = int(request.args.get("limit", 20))
    try:
        from akshare_source import ak_get_stock_news
        return ok(ak_get_stock_news(code, limit))
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/quote")
def quote():
    """Realtime quotes for a list of codes: ?codes=sh000001,600519 或纯数字码。"""
    codes = request.args.get("codes", "")
    items = [c.strip() for c in codes.split(",") if c.strip()]
    if not items:
        return err(400, "missing_codes", "需要 codes 参数")
    try:
        from data_manager import fetch_realtime_prices
        return ok(fetch_realtime_prices(items))
    except Exception as e:
        return err(502, "quote_error", str(e), retriable=True)
