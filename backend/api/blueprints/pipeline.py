# -*- coding: utf-8 -*-
"""DataPipeline blueprint — trigger data updates with SSE progress."""
from flask import Blueprint, jsonify, request

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
    return jsonify({"code": 0, "data": job, "message": "ok"})


@bp.route("/status", methods=["GET"])
def pipeline_status():
    """Get latest update_marker.json status."""
    import json, os
    marker_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "update_marker.json")
    marker_path = os.path.normpath(marker_path)
    if not os.path.exists(marker_path):
        return jsonify({"code": 0, "data": {"last_update": None, "status": "未更新"}, "message": "ok"})
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"code": 0, "data": data, "message": "ok"})
    except Exception:
        return jsonify({"code": 0, "data": {"last_update": None, "status": "读取失败"}, "message": "ok"})


@bp.route("/stats", methods=["GET"])
def pipeline_stats():
    """Database statistics for the pipeline overview."""
    import sqlite3, os
    from backend.data_manager import KLINE_DB
    try:
        data = {"stock_count": 0, "kline_rows": 0, "latest_date": None, "db_size": "—", "active_stocks": 0}
        if os.path.exists(KLINE_DB):
            data["db_size"] = f"{os.path.getsize(KLINE_DB) / 1024 / 1024:.0f} MB"
            conn = sqlite3.connect(KLINE_DB, timeout=3)
            try:
                data["kline_rows"] = conn.execute("SELECT COUNT(*) FROM kline_daily").fetchone()[0]
                data["stock_count"] = conn.execute("SELECT COUNT(DISTINCT code) FROM kline_daily").fetchone()[0]
                row = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()
                data["latest_date"] = row[0] if row else None
                data["active_stocks"] = conn.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
            finally:
                conn.close()
        return jsonify({"code": 0, "data": data, "message": "ok"})
    except Exception as e:
        return jsonify({"code": 500, "data": None, "error": {"code": 500, "message": str(e), "retriable": False}}), 500
