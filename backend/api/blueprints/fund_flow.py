# -*- coding: utf-8 -*-
"""fund_flow blueprint — 个股资金流(日频)历史查询."""
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("fund_flow", __name__, url_prefix="/api/fund-flow")


@bp.route("/kline")
def fund_flow_kline():
    """单只个股资金流历史(升序, 与 K线对齐). ?code=600036&days=250"""
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 250, 10, 6000)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_fund_flow
        rows = get_fund_flow(code, days)
        if not rows:
            return err(404, "no_data", f"{code} 无资金流数据", retriable=False)
        return ok(rows, code=code)
    except Exception as e:
        return err(502, "fund_flow_error", str(e), retriable=True)