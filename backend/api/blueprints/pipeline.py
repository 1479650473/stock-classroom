# -*- coding: utf-8 -*-
"""DataPipeline blueprint — trigger data updates with SSE progress."""
from flask import Blueprint, request

from ..envelope import ok, err

bp = Blueprint("pipeline", __name__, url_prefix="/api/pipeline")


def _run_daily_update(payload, on_progress):
    """Runner for daily_update job."""
    from backend.data_manager import daily_update, update_pool
    pool_only = payload.get("pool_only", False)
    on_progress({"step": "init", "message": "开始数据更新…"})
    try:
        if pool_only:
            on_progress({"step": "pool", "message": "更新量化池…"})
            result = update_pool(progress=lambda p: on_progress({"step": "pool", "progress": p}))
        else:
            on_progress({"step": "daily", "message": "全量日更新…"})
            ok = daily_update()
            result = {"ok": ok}
        on_progress({"step": "done", "message": "更新完成"})
        return result
    except Exception as e:
        on_progress({"step": "error", "message": str(e)})
        raise


@bp.route("/update", methods=["POST"])
def trigger_update():
    """Trigger daily data update as a background job."""
    body = request.get_json(force=True, silent=True) or {}
    from backend.api.jobman import submit
    job = submit("pipeline_update", _run_daily_update, {"pool_only": body.get("pool_only", False)})
    return ok(job)


@bp.route("/status", methods=["GET"])
def pipeline_status():
    """Get latest update_marker.json status."""
    import json, os
    marker_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "update_marker.json"))
    if not os.path.exists(marker_path):
        return ok({"last_update": None, "status": "未更新"})
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ok(data)
    except Exception:
        return ok({"last_update": None, "status": "读取失败"})


_stats_cache = {"t": 0, "data": None}

@bp.route("/stats", methods=["GET"])
def pipeline_stats():
    """Database statistics (含各业务库分层统计). 加60s缓存避免全表COUNT每次都慢."""
    import time as _t
    now = _t.time()
    if _stats_cache["data"] is not None and now - _stats_cache["t"] < 60:
        return ok(_stats_cache["data"])
    import sqlite3, os
    from backend.data_manager import KLINE_DB
    try:
        data = {"stock_count": 0, "kline_rows": 0, "latest_date": None, "db_size": "—",
                "active_stocks": 0, "tables": {}}
        if os.path.exists(KLINE_DB):
            data["db_size"] = f"{os.path.getsize(KLINE_DB) / 1024 / 1024:.0f} MB"
            conn = sqlite3.connect(KLINE_DB, timeout=3)
            try:
                data["kline_rows"] = conn.execute("SELECT COUNT(*) FROM kline_daily").fetchone()[0]
                data["stock_count"] = conn.execute("SELECT COUNT(DISTINCT code) FROM kline_daily").fetchone()[0]
                row = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()
                data["latest_date"] = row[0] if row else None
                data["active_stocks"] = conn.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
                # 各业务库统计(供数据中心分层展示; 日期列名不一: date/trade_date/updated_at, 无则只给行数)
                tbl_stats = {}
                for t in ("sector_board", "north_flow", "limit_up", "stock_sector", "fund_flow",
                          "high_low", "lhb_daily", "chip_distribution", "stock_list"):
                    try:
                        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        # 找可用的日期列
                        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                        datecol = next((c for c in ("date", "trade_date", "updated_at", "last_date") if c in cols), None)
                        mx = None
                        if datecol:
                            mx = conn.execute(f"SELECT MAX({datecol}) FROM {t}").fetchone()[0]
                        tbl_stats[t] = {"rows": n, "latest": mx}
                    except Exception:
                        tbl_stats[t] = {"rows": None, "latest": None}
                data["tables"] = tbl_stats
            finally:
                conn.close()
        _stats_cache["t"] = now
        _stats_cache["data"] = data
        return ok(data)
    except Exception as e:
        return err(500, "pipeline_stats_failed", str(e), retriable=False)
