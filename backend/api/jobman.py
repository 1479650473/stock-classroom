# -*- coding: utf-8 -*-
"""Generic in-process JobManager for the web API.

Mirrors the submit -> poll -> SSE pattern of backend/agent/jobs.py but is
self-contained (in-memory, no sqlite coupling) so the single-user desktop web
app can run long tasks (data pipeline, factor picks, backtests, LLM runs)
without blocking the HTTP request.

Usage:
    from ..jobman import submit, stream
    job = submit("picks", runner)          # runner(payload) or runner(payload, on_progress)
    # GET  /api/jobs/<id>          -> status + result
    # GET  /api/jobs/<id>/stream   -> SSE progress/result frames
"""
from __future__ import annotations

import inspect
import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-job")
_LOCK = threading.Lock()
_JOBS: dict = {}          # job_id -> record dict
_QUEUES: dict = {}        # job_id -> buffered SSE lines (ring)
_BASE: dict = {}          # job_id -> 已被环缓冲丢弃的行数（绝对下标基准）
_SIGS: dict = {}          # job_id -> threading.Event
_KEEP = 20000             # 每个 job 保留的 SSE 帧上限（LLM 逐日回放会推很多增量帧）
_JOB_TTL = 6 * 3600      # 完成后的 job 记录保留 6 小时
_last_prune = 0.0


def _prune():
    """惰性回收超过 TTL 的已完成 job(防长期运行内存泄漏)."""
    global _last_prune
    now = time.time()
    if now - _last_prune < 3600:
        return
    _last_prune = now
    stale = [jid for jid, j in _JOBS.items()
             if (j.get("finished_at") or 0) and now - j["finished_at"] > _JOB_TTL]
    with _LOCK:
        for jid in stale:
            _JOBS.pop(jid, None)
            _QUEUES.pop(jid, None)
            _SIGS.pop(jid, None)
            _BASE.pop(jid, None)


def _new_id() -> str:
    return "job_" + uuid.uuid4().hex[:16]


def _rec(job_id: str):
    return _JOBS.get(job_id)


def _push(job_id: str, frame: dict, terminal: bool = False):
    line = json.dumps(frame, ensure_ascii=False, default=str)
    with _LOCK:
        q = _QUEUES.setdefault(job_id, [])
        q.append(line)
        if len(q) > _KEEP:
            drop = len(q) - _KEEP
            del q[:drop]
            _BASE[job_id] = _BASE.get(job_id, 0) + drop
        sig = _SIGS.setdefault(job_id, threading.Event())
    sig.set()
    if terminal:
        sig.set()


def submit(kind: str, runner: Callable, payload: Any = None) -> dict:
    _prune()
    job_id = _new_id()
    now = time.time()
    _JOBS[job_id] = {
        "job_id": job_id, "kind": kind, "status": "queued",
        "created_at": now, "started_at": None, "finished_at": None,
        "result": None, "error": None,
    }
    _QUEUES[job_id] = []
    _BASE[job_id] = 0
    _SIGS[job_id] = threading.Event()

    try:
        accepts_progress = len(inspect.signature(runner).parameters) >= 2
    except (TypeError, ValueError):
        accepts_progress = False

    def on_progress(snap):
        if not isinstance(snap, dict):
            snap = {"value": snap}
        _push(job_id, {"type": "progress", "ts": time.time(), **snap})

    def _run():
        rec = _rec(job_id)
        if rec is None:
            return
        rec["status"] = "running"
        rec["started_at"] = time.time()
        _push(job_id, {"type": "progress", "phase": "running", "ts": time.time()})
        try:
            result = runner(payload, on_progress) if accepts_progress else runner(payload)
            if rec["status"] == "cancelled":
                _push(job_id, {"type": "progress", "phase": "cancelled", "ts": time.time()}, terminal=True)
                return
            rec["status"] = "succeeded"
            rec["result"] = result
            rec["finished_at"] = time.time()
            _push(job_id, {"type": "result", "ts": time.time(), "result": result}, terminal=True)
        except Exception as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)
            rec["traceback"] = traceback.format_exc()[-2000:]
            rec["finished_at"] = time.time()
            _push(job_id, {"type": "error", "ts": time.time(), "message": str(exc)}, terminal=True)
            try:                                  # 任务失败 → 通知（节流：同类任务 5 分钟内只发一次）
                from backend import notify
                notify.push("job", f"任务失败：{kind}",
                            level="error", detail=f"{str(exc)[:300]}（job {job_id}）",
                            key=f"{kind}", extra={"job_id": job_id, "kind": kind})
            except Exception:
                pass

    _POOL.submit(_run)
    return {"job_id": job_id, "status": "queued", "kind": kind}


def get(job_id: str):
    return _rec(job_id)


def list_jobs(kind: str | None = None, limit: int = 50):
    out = list(_JOBS.values())
    if kind:
        out = [j for j in out if j["kind"] == kind]
    out.sort(key=lambda j: j["created_at"], reverse=True)
    return out[:limit]


def cancel(job_id: str) -> bool:
    rec = _rec(job_id)
    if rec and rec["status"] in ("queued", "running"):
        rec["status"] = "cancelled"
        rec["finished_at"] = time.time()
        _push(job_id, {"type": "progress", "phase": "cancelled", "ts": time.time()}, terminal=True)
        return True
    return False


def stream(job_id: str, since: int = 0):
    rec = _rec(job_id)
    if not rec:
        yield _sse({"type": "error", "message": "job not found"})
        return
    sig = _SIGS[job_id]
    with _LOCK:
        # 环缓冲会丢弃最旧的帧：用 base 把绝对下标对齐到当前窗口，
        # 否则 idx 会永远落在窗口之外、再也读不到新帧（长任务会「卡在第一天」）。
        base = _BASE.get(job_id, 0)
        if since < base:
            since = base
        replay = list(_QUEUES.get(job_id, []))[since - base:]
        idx = since + len(replay)
    for line in replay:
        yield "data: %s\n\n" % line
    while True:
        # 先清信号再取快照：期间新推的帧要么被本次读取到，要么让 wait 立即返回，
        # 不会丢帧也不会自旋（Event 不清会永远处于 set 状态，导致空转狂发 ping）。
        sig.clear()
        with _LOCK:
            base = _BASE.get(job_id, 0)
            if idx < base:
                idx = base
            pending = list(_QUEUES.get(job_id, []))[idx - base:]
            idx += len(pending)
        for line in pending:
            yield "data: %s\n\n" % line
        cur = _rec(job_id)
        if cur and cur["status"] in ("succeeded", "failed", "cancelled"):
            yield _sse({
                "type": "done", "status": cur["status"],
                "result": cur.get("result"), "error": cur.get("error"),
            })
            break
        if pending:
            continue
        if not sig.wait(timeout=15.0):
            yield _sse({"type": "ping", "ts": time.time()})


def _sse(obj: dict) -> str:
    return "data: %s\n\n" % json.dumps(obj, ensure_ascii=False, default=str)
