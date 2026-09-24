# -*- coding: utf-8 -*-
"""K线 / 筹码 / 股票检索。"""
import sqlite3

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from ..paths import KLINE_DB

bp = Blueprint("kline", __name__, url_prefix="/api")


@bp.route("/kline")
def kline():
    code = request.args.get("code", "").strip()
    days = int_arg(request.args.get("days"), 180, 5, 5000)
    period = request.args.get("period", "daily").strip()   # daily|weekly|monthly
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    try:
        from indicators import enrich_kline
        if period in ("weekly", "monthly"):
            from data_manager import get_period_kline
            kd = get_period_kline(code, period, days)
            return ok(enrich_kline(kd), period=period)
        from data_manager import get_kline_data
        kd = get_kline_data(code, days)
        return ok(enrich_kline(kd), period="daily")
    except Exception as e:
        return err(500, "kline_error", str(e))


# ---- 分钟级实时数据（新浪源，内存缓存 45s） ----
_MIN_CACHE: dict = {}
_MIN_TTL = 45.0


@bp.route("/kline/minute")
def kline_minute():
    """分钟级 K 线 / 分时用 1 分钟线。

    period: 1|5|15|30|60（分钟）；days: 只保留最近 N 个交易日（0=全部，新浪给多少拿多少）
    返回 bars: [{time("YYYY-MM-DD HH:MM:SS"), open, high, low, close, volume(股), amount(元)}]
    另附 prev_close（前一交易日收盘，分时基准线用）。
    """
    import time as _t
    code = request.args.get("code", "").strip()
    period = request.args.get("period", "1").strip()
    days = int_arg(request.args.get("days"), 0, 0, 60)
    if not code:
        return err(400, "missing_code", "需要 code 参数")
    if period not in ("1", "5", "15", "30", "60"):
        return err(400, "bad_period", "period 只能是 1/5/15/30/60")
    key = (code, period)
    hit = _MIN_CACHE.get(key)
    if hit and _t.time() - hit[0] < _MIN_TTL:
        payload = hit[1]
    else:
        try:
            import akshare as ak
            from codec import ak_symbol
            df = ak.stock_zh_a_minute(symbol=ak_symbol(code), period=period, adjust="qfq")
            rows = []
            for r in df.itertuples(index=False):
                try:
                    rows.append({
                        "time": str(r.day), "open": float(r.open), "high": float(r.high),
                        "low": float(r.low), "close": float(r.close),
                        "volume": float(r.volume or 0), "amount": float(r.amount or 0),
                    })
                except (TypeError, ValueError):
                    continue
            payload = rows
            _MIN_CACHE[key] = (_t.time(), rows)
        except Exception as e:                                    # noqa: BLE001
            return err(502, "minute_error", f"分钟数据获取失败：{e}")
    bars = payload
    if days > 0 and bars:
        dates = sorted({b["time"][:10] for b in bars})[-days:]
        keep = set(dates)
        bars = [b for b in bars if b["time"][:10] in keep]
    # 前一交易日收盘（分时基准）
    prev_close = None
    try:
        # 以「最后一根 bar 所在交易日」为基准日：分时图展示的是最近一天，昨收要取它的前一日
        conn = sqlite3.connect(KLINE_DB, timeout=10)
        row = conn.execute(
            "SELECT close FROM kline_daily WHERE code=? AND date < ? ORDER BY date DESC LIMIT 1",
            (code, (bars[-1]["time"][:10].replace("-", "") if bars else "99999999"))).fetchone()
        conn.close()
        prev_close = float(row[0]) if row and row[0] else None
    except Exception:                                             # noqa: BLE001
        prev_close = None
    return ok({"bars": bars, "prev_close": prev_close, "period": period, "source": "sina"})


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
