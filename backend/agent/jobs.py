# -*- coding: utf-8 -*-
"""异步 Job 运行器 — 对齐 QuantDinger 的 agent_jobs。

"提交 + 轮询"语义(LLM 代理友好)：
- submit_job(kind, payload, runner) -> {job_id, status:"queued"}，立即返回
- runner(payload)  或  runner(payload, on_progress)
- 状态机：queued -> running -> succeeded / failed / cancelled
- on_progress(snapshot) 发布进度快照(持久化 latest)，SSE 客户端可重放
- stream_job: SSE 生成器，发 snapshot/progress/ping/result 帧
- 单进程桌面应用：用 ThreadPoolExecutor(无需 Celery/Redis)
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import store

_POOL = None
_pool_lock = threading.Lock()

# per-job progress 缓冲(SSE 重放)
_job_buffers: dict[str, list[str]] = {}
_job_locks: dict[str, threading.Lock] = {}
_job_signals: dict[str, threading.Event] = {}
_job_global_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        with _pool_lock:
            if _POOL is None:
                _POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-job")
    return _POOL


def _new_job_id() -> str:
    return "jb_" + uuid.uuid4().hex[:16]


def _buffer(job_id: str):
    with _job_global_lock:
        if job_id not in _job_buffers:
            _job_buffers[job_id] = []
            _job_locks[job_id] = threading.Lock()
            _job_signals[job_id] = threading.Event()
        return _job_buffers[job_id], _job_locks[job_id], _job_signals[job_id]


def _publish(job_id: str, frame: dict, terminal: bool = False):
    line = json.dumps(frame, ensure_ascii=False, default=str)
    buf, lock, sig = _buffer(job_id)
    with lock:
        buf.append(line)
        if len(buf) > 400:
            del buf[: len(buf) - 400]
    sig.set()
    # 持久化 progress(供轮询/重放)
    if "progress" in str(frame.get("type", "")) or frame.get("type") in ("progress", "snapshot"):
        try:
            con = store.get_conn()
            con.execute("UPDATE agent_jobs SET progress=? WHERE job_id=?", (line, job_id))
            con.commit()
            con.close()
        except Exception:
            pass


def _set_status(job_id: str, status: str, **extra):
    con = store.get_conn()
    try:
        keys = ", ".join(k + "=?" for k in extra)
        if keys:
            con.execute(f"UPDATE agent_jobs SET status=?, {keys} WHERE job_id=?",
                        (status, *extra.values(), job_id))
        else:
            con.execute("UPDATE agent_jobs SET status=? WHERE job_id=?", (status, job_id))
        con.commit()
    finally:
        con.close()


def _set_result(job_id: str, result: Any) -> bool:
    con = store.get_conn()
    try:
        cur = con.execute(
            "UPDATE agent_jobs SET result=?, status='succeeded', finished_at=datetime('now','localtime') "
            "WHERE job_id=? AND status IN ('running','queued')",
            (json.dumps(result, ensure_ascii=False, default=str), job_id))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def _set_failure(job_id: str, err: str) -> bool:
    con = store.get_conn()
    try:
        cur = con.execute(
            "UPDATE agent_jobs SET error=?, status='failed', finished_at=datetime('now','localtime') "
            "WHERE job_id=? AND status IN ('running','queued')",
            (err, job_id))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def _runner_accepts_progress(runner: Callable) -> bool:
    try:
        import inspect
        return len(inspect.signature(runner).parameters) >= 2
    except (TypeError, ValueError):
        return False


def submit_job(kind: str, payload: Any, runner: Callable,
               agent_token_id: int, agent_id: str,
               idempotency_key: Optional[str] = None,
               request_hash: str = "") -> dict:
    store.ensure_schema()
    job_id = _new_job_id()
    con = store.get_conn()
    try:
        con.execute(
            "INSERT INTO agent_jobs(job_id,agent_token_id,agent_id,kind,status,request,idempotency_key)"
            " VALUES(?,?,?,?,?,?,?)",
            (job_id, agent_token_id, agent_id, kind, "queued",
             json.dumps(payload, ensure_ascii=False, default=str),
             idempotency_key or ""))
        con.commit()
    finally:
        con.close()

    accepts_progress = _runner_accepts_progress(runner)

    def _run():
        _set_status(job_id, "running", started_at="datetime('now','localtime')")
        _publish(job_id, {"type": "progress", "phase": "running", "ts": time.time()})
        result = None
        try:
            if accepts_progress:
                def on_progress(snap: Any):
                    if not isinstance(snap, dict):
                        snap = {"value": snap}
                    _publish(job_id, {"type": "progress", "ts": time.time(), **snap})
                result = runner(payload, on_progress)
            else:
                result = runner(payload)
            if _set_result(job_id, result):
                _publish(job_id, {"type": "result", "ts": time.time(), **result}, terminal=True)
            else:
                _publish(job_id, {"type": "progress", "phase": "cancelled", "ts": time.time()}, terminal=True)
        except Exception as exc:
            tb = traceback.format_exc()
            _set_failure(job_id, f"{exc}\n{tb[-2000:]}")
            _publish(job_id, {"type": "error", "ts": time.time(), "message": str(exc)}, terminal=True)

    _get_pool().submit(_run)
    return {"job_id": job_id, "status": "queued", "kind": kind}


def get_job(job_id: str, agent_id: Optional[str] = None):
    con = store.get_conn()
    try:
        if agent_id is not None:
            row = con.execute("SELECT * FROM agent_jobs WHERE job_id=? AND agent_id=?",
                              (job_id, agent_id)).fetchone()
        else:
            row = con.execute("SELECT * FROM agent_jobs WHERE job_id=?", (job_id,)).fetchone()
        d = store.to_dict(row)
        if d:
            d["decoded_result"] = _try_json(d.get("result"))
            d["decoded_progress"] = _try_json(d.get("progress"))
        return d
    finally:
        con.close()


def _try_json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def list_jobs(agent_id: str, kind: Optional[str] = None, limit: int = 50, cursor: int = 0):
    con = store.get_conn()
    try:
        if kind:
            rows = con.execute(
                "SELECT job_id,kind,status,agent_id,result,error,created_at,finished_at "
                "FROM agent_jobs WHERE agent_id=? AND kind=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (agent_id, kind, limit, cursor)).fetchall()
        else:
            rows = con.execute(
                "SELECT job_id,kind,status,agent_id,result,error,created_at,finished_at "
                "FROM agent_jobs WHERE agent_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (agent_id, limit, cursor)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["decoded_result"] = _try_json(d.get("result"))
            out.append(d)
        return out
    finally:
        con.close()


def cancel_job(job_id: str, agent_id: str) -> bool:
    con = store.get_conn()
    try:
        cur = con.execute(
            "UPDATE agent_jobs SET status='cancelled', finished_at=datetime('now','localtime') "
            "WHERE job_id=? AND agent_id=? AND status IN ('queued','running')",
            (job_id, agent_id))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def stream_job(job_id: str, agent_id: str, since: int = 0):
    """SSE 生成器：发 snapshot/progress/ping/result 帧；断线可 ?since= 续传。"""
    job = get_job(job_id, agent_id)
    if not job:
        yield _sse({"type": "error", "message": "job not found"})
        return

    _, lock, sig = _buffer(job_id)
    buf, _, _ = _job_buffers[job_id]
    # 先补发已有的 snapshot/progress
    with lock:
        replay = list(buf)[since:]
        idx = since + len(replay)
    for line in replay:
        yield _sse_raw(line)
    # 若已完成，补发 result(snapshot 里可能已有)
    yield _sse({"type": "ping", "ts": time.time(), "status": job.get("status")})

    # 等待后续事件(限时 15s 一次 ping)
    while True:
        sig.wait(timeout=15.0)
        with lock:
            pending = list(_job_buffers[job_id][idx:])
            idx += len(pending)
        if pending:
            for line in pending:
                yield _sse_raw(line)
        else:
            yield _sse({"type": "ping", "ts": time.time()})
        cur = get_job(job_id, agent_id)
        if cur and cur.get("status") in ("succeeded", "failed", "cancelled"):
            yield _sse({"type": "result" if cur["status"] == "succeeded" else "error",
                        "status": cur["status"],
                        "result": cur.get("decoded_result"),
                        "error": cur.get("error")})
            break
    return


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"


def _sse_raw(line: str) -> str:
    return f"data: {line}\n\n"
