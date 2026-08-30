# -*- coding: utf-8 -*-
"""K线 / 筹码 / 股票检索。"""
import sqlite3

from flask import Blueprint, request

from ..envelope import ok, err
from ..paths import KLINE_DB

bp = Blueprint("kline", __name__, url_prefix="/api")


@bp.route("/kline")
def kline():
    code = request.args.get("code", "").strip()
    days = int(request.args.get("days", 180))
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_kline_data
        from indicators import enrich_kline
        kd = get_kline_data(code, days)
        return ok(enrich_kline(kd))
    except Exception as e:
        return err(500, "kline_error", str(e))


@bp.route("/kline/cyq")
def cyq():
    code = request.args.get("code", "").strip()
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        conn = sqlite3.connect(KLINE_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code, date, [获利比例], [平均成本], [90成本_低], [90成本_高], [90集中度],"
            " [70成本_低], [70成本_高], [70集中度] FROM chip_distribution WHERE code=? ORDER BY date DESC",
            (code,)).fetchall()
        conn.close()
        if not rows:
            return err(404, "no_cyq", "暂无筹码分布数据")
        out = [{
            "code": r[0], "date": r[1], "profit_ratio": r[2], "avg_cost": r[3],
            "cost90_low": r[4], "cost90_high": r[5], "conc90": r[6],
            "cost70_low": r[7], "cost70_high": r[8], "conc70": r[9],
        } for r in rows]
        return ok(out)
    except Exception as e:
        return err(500, "cyq_error", str(e))


@bp.route("/stock/search")
def stock_search():
    q = request.args.get("q", "").strip()
    if not q:
        return err(400, "missing_q", "请输入搜索关键词")
    try:
        conn = sqlite3.connect(KLINE_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code, name, status FROM stock_list WHERE code LIKE ? OR name LIKE ? ORDER BY code LIMIT 50",
            (f"%{q}%", f"%{q}%")).fetchall()
        conn.close()
        return ok([dict(r) for r in rows])
    except Exception as e:
        return err(500, "search_error", str(e))


@bp.route("/stock/list")
def stock_list():
    status = request.args.get("status", "all")
    try:
        from data_manager import get_stock_list
        return ok(get_stock_list(status))
    except Exception as e:
        return err(500, "list_error", str(e))
