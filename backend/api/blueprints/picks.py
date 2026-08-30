# -*- coding: utf-8 -*-
"""多因子选股 — compute_factor_picks 全市场扫描较慢, 走 Job + 内存缓存。"""
import threading
import time

from flask import Blueprint, request

from ..envelope import ok, err
from .. import jobman

bp = Blueprint("picks", __name__, url_prefix="/api/picks")

_cache = {"data": None, "ts": 0.0, "running": False}
_lock = threading.Lock()
_TTL = 300  # 5 分钟内重复请求直接返回缓存


def _run(payload, on_progress):
    from data_manager import compute_factor_picks
    days = int((payload or {}).get("kline_days", 60))
    on_progress({"msg": "扫描候选池...", "pct": 5})
    results = compute_factor_picks(kline_days=days)
    on_progress({"msg": f"完成 {len(results)} 只", "pct": 100})
    return {"total": len(results), "items": results}


@bp.route("", methods=["GET"])
def latest():
    with _lock:
        data, ts = _cache["data"], _cache["ts"]
    top = int(request.args.get("top", 20))
    if data is None:
        return ok({"items": [], "total": 0, "stale": True, "ts": 0})
    return ok({"items": data["items"][:top], "total": data["total"],
               "stale": (time.time() - ts) > _TTL, "ts": ts})


@bp.route("/run", methods=["POST"])
def run():
    force = (request.get_json(silent=True) or {}).get("force", True)
    with _lock:
        cached = _cache["data"]
        fresh = cached is not None and (time.time() - _cache["ts"]) < _TTL
        if _cache["running"]:
            return ok({"status": "already_running"}, message="扫描进行中")
        if fresh and not force and cached is not None:
            return ok({"status": "cached", "total": cached["total"]})
        _cache["running"] = True

    def wrapped(payload, on_progress):
        try:
            res = _run(payload, on_progress)
            with _lock:
                _cache["data"] = res
                _cache["ts"] = time.time()
            return res
        finally:
            with _lock:
                _cache["running"] = False

    job = jobman.submit("picks", wrapped, request.get_json(silent=True) or {})
    return ok(job, message="picks queued")
