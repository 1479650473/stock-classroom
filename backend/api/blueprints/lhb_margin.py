# -*- coding: utf-8 -*-
"""lhb_margin blueprint — 龙虎榜明细 / 融资融券历史."""
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("lhb_margin", __name__, url_prefix="/api")


@bp.route("/lhb")
def lhb():
    """龙虎榜. ?code=600036&days=100 (单股) 或 ?days=50 (最近明细)."""
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 100, 5, 2000)
    try:
        from data_manager import get_lhb
        rows = get_lhb(code, days)
        return ok(rows, stock_code=code or None)
    except Exception as e:
        return err(502, "lhb_error", str(e), retriable=True)


@bp.route("/margin")
def margin():
    """单只股票融资融券历史. ?code=600036&days=250"""
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 250, 5, 5000)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_margin
        rows = get_margin(code, days)
        if not rows:
            return err(404, "no_data", f"{code} 无融资融券数据", retriable=False)
        return ok(rows, stock_code=code)
    except Exception as e:
        return err(502, "margin_error", str(e), retriable=True)