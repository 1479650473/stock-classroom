# -*- coding: utf-8 -*-
"""ETF blueprint — ETF 列表 / 单只历史 K线 / 多只归一化对比."""
from flask import Blueprint, request

from ..envelope import ok, err, int_arg

bp = Blueprint("etf", __name__, url_prefix="/api/etf")


@bp.route("/list")
def etf_list():
    """ETF 列表(含搜索/类型过滤). ?search=&type="""
    search = request.args.get("search", "").strip()
    etype = request.args.get("type", "").strip()
    try:
        from data_manager import get_etf_list
        return ok(get_etf_list(search=search, etype=etype))
    except Exception as e:
        return err(502, "etf_error", str(e), retriable=True)


@bp.route("/kline")
def etf_kline():
    """单只 ETF 历史 K线(KlineBar 格式, 前端 KlineChart 直接消费). ?code=510300&days=250"""
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 250, 10, 6000)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from data_manager import get_etf_kline
        bars = get_etf_kline(code, days)
        if not bars:
            return err(404, "no_data", f"{code} 无 K线数据", retriable=False)
        name_row = None
        try:
            from data_manager import get_etf_list
            for r in get_etf_list(search=code):
                if r["code"] == code:
                    name_row = r["name"]
                    break
        except Exception:
            pass
        return ok(bars, code=code, name=name_row or code)
    except Exception as e:
        return err(502, "etf_error", str(e), retriable=True)


@bp.route("/compare")
def etf_compare():
    """多只 ETF 归一化对比(各自首日 close=1). ?codes=510300,159919&days=250"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    days = int_arg(request.args.get("days"), 250, 10, 6000)
    if not codes:
        return err(400, "missing_codes", "需要 codes 参数(逗号分隔)")
    if len(codes) > 10:
        return err(400, "too_many", "最多 10 只")
    try:
        from data_manager import get_etf_compare
        return ok(get_etf_compare(codes, days))
    except Exception as e:
        return err(502, "etf_error", str(e), retriable=True)