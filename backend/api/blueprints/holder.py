# -*- coding: utf-8 -*-
"""holder blueprint — 股东户数 / 基金持仓(季度)."""
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("holder", __name__, url_prefix="/api")


@bp.route("/holder")
def holder():
    """股东户数历史(季度). ?code=600036&limit=40"""
    code = request.args.get("code", "").strip()
    limit = int_arg(request.args.get("limit"), 40, 4, 100)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_holder_count
        rows = get_holder_count(code, limit)
        if not rows:
            return err(404, "no_data", f"{code} 无股东户数数据", retriable=False)
        return ok(rows, stock_code=code)
    except Exception as e:
        return err(502, "holder_error", str(e), retriable=True)


@bp.route("/fund-hold")
def fund_hold():
    """基金持仓历史(季度). ?code=600036&limit=40"""
    code = request.args.get("code", "").strip()
    limit = int_arg(request.args.get("limit"), 40, 4, 100)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_fund_hold
        rows = get_fund_hold(code, limit)
        if not rows:
            return err(404, "no_data", f"{code} 无基金持仓数据", retriable=False)
        return ok(rows, stock_code=code)
    except Exception as e:
        return err(502, "fund_hold_error", str(e), retriable=True)