# -*- coding: utf-8 -*-
"""Market data: indices, sectors, north flow, news, realtime quotes."""
import os
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("market", __name__, url_prefix="/api/market")

_MAIN_INDEX = {"sh000001", "sz399001", "sz399006"}


@bp.route("/indices")
def indices():
    """主要指数 — 优先本地快照(fetch_index_prices 快速可靠), 避免 akshare 实时反爬阻塞."""
    try:
        from data_manager import fetch_index_prices
        main = fetch_index_prices()
        if main:
            return ok(main, source=(main[0].get("source", "local") if main else "local"))
    except Exception:
        pass
    try:
        import socket
        socket.setdefaulttimeout(5)
        from akshare_source import ak_get_index_spot
        data = ak_get_index_spot()
        main = [d for d in data if d.get("code") in _MAIN_INDEX]
        if main:
            from data_manager import fetch_index_prices
            main = fetch_index_prices() or main
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
    """行业板块涨跌 — 优先真实(akshare 非空), 否则回退本地 sector_board, 不空."""
    sector_type = request.args.get("type", "industry")
    # ① 先试实时(akshare), 需非空才采用(被反爬返回 [] 时跳过)
    try:
        from akshare_source import ak_get_sectors
        data = ak_get_sectors(sector_type)
        if data:
            return ok(data, type=sector_type, source="live")
    except Exception:
        pass
    # ② 回退本地 sector_board(991行, 稳定, 避免被反爬拉空)
    try:
        import sqlite3
        from ..paths import KLINE_DB
        if not os.path.exists(KLINE_DB):
            return ok([], type=sector_type, source="none")
        conn = sqlite3.connect(KLINE_DB)
        rows = conn.execute(
            "SELECT name, change_pct, up_count, dn_count, leader, leader_chg, updated_at "
            "FROM sector_board WHERE type=? ORDER BY rank ASC", (sector_type,)).fetchall()
        conn.close()
        out = [{"name": r[0], "change_pct": r[1], "up_count": r[2], "dn_count": r[3],
                "leader": r[4], "leader_chg": r[5], "updated_at": r[6]} for r in rows]
        return ok(out, type=sector_type, source="cache")
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/north-flow")
def north_flow():
    """北向资金 — 优先真实(akshare 有非0净流入), 否则回退本地 north_flow, 不空."""
    days = int_arg(request.args.get("days"), 30, 1, 365)
    try:
        from akshare_source import ak_get_north_flow
        data = ak_get_north_flow(days)
        # 需有真实值(任一 net_flow != 0)才采用, 被反爬返回全0假数据时跳过
        if data and any(abs(d.get("net_flow") or 0) > 0.01 for d in data):
            return ok(data, source="live")
    except Exception:
        pass
    # ② 回退本地 north_flow(真实; 北向日度数据2024-08后已停更, 过滤null行)
    try:
        import sqlite3
        from ..paths import KLINE_DB
        if not os.path.exists(KLINE_DB):
            return ok([], source="none")
        conn = sqlite3.connect(KLINE_DB)
        rows = conn.execute(
            "SELECT date, net_flow, cum_flow FROM north_flow "
            "WHERE net_flow IS NOT NULL ORDER BY date DESC LIMIT ?", (days,)).fetchall()
        conn.close()
        out = [{"date": r[0], "net_flow": r[1], "cum_flow": r[2]} for r in rows]
        return ok(out, source="cache")
    except Exception as e:
        return err(502, "market_error", str(e), retriable=True)


@bp.route("/news")
def news():
    code = request.args.get("code", "000001")
    limit = int_arg(request.args.get("limit"), 20, 1, 100)
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
