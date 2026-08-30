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
_SIGS: dict = {}          # job_id -> threading.Event
_KEEP = 400


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
            del q[: len(q) - _KEEP]
        sig = _SIGS.setdefault(job_id, threading.Event())
    sig.set()
    if terminal:
        sig.set()


def submit(kind: str, runner: Callable, payload: Any = None) -> dict:
    job_id = _new_id()
    now = time.time()
    _JOBS[job_id] = {
        "job_id": job_id, "kind": kind, "status": "queued",
        "created_at": now, "started_at": None, "finished_at": None,
        "result": None, "error": None,
    }
    _QUEUES[job_id] = []
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
        replay = list(_QUEUES.get(job_id, []))[since:]
        idx = since + len(replay)
    for line in replay:
        yield "data: %s\n\n" % line
    while True:
        sig.wait(timeout=15.0)
        with _LOCK:
            pending = list(_QUEUES.get(job_id, [])[idx:])
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
        if not pending:
            yield _sse({"type": "ping", "ts": time.time()})


def _sse(obj: dict) -> str:
    return "data: %s\n\n" % json.dumps(obj, ensure_ascii=False, default=str)
