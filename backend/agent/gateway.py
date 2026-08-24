# -*- coding: utf-8 -*-
"""Agent Gateway 核心 — 鉴权/能力分级/审计/幂等/限流/token 管理。

设计对齐 QuantDinger 的 Agent Gateway，但按本项目(单用户桌面 + SQLite)裁剪：
- 能力分级 R/W/B/T(去掉 N 通知、C 凭据——本应用无凭据流转)
- token 前缀 sc_agent_，只存 sha256 哈希，前缀可见
- 限流：进程内滑动窗口(无需 Redis)，per-token + per-agent(tenant)
- 所有调用(成功/拒绝)写入 agent_audit
- 变更类(W/B/T)用 Idempotency-Key 原子保留，重放已完成响应
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from . import store


# ── 能力分级 ─────────────────────────────────────────────────────────
SCOPE_R = "R"   # Read: 行情/K线/宏观看板/目录/策略列表/账户读数
SCOPE_W = "W"   # Workspace write: 建/改声明式策略、存watchlist
SCOPE_B = "B"   # Backtest: 提交回测
SCOPE_T = "T"   # Trading: paper 下单(默认 paper_only)
ALL_SCOPES = (SCOPE_R, SCOPE_W, SCOPE_B, SCOPE_T)

TOKEN_PREFIX = "sc_agent_"
DEFAULT_RATE_LIMIT_PER_MIN = 60


# ── 进程内限流(滑动窗口) ────────────────────────────────────────────
_rate_state: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _memory_rate_limit(key: str, limit_per_min: int) -> dict:
    now = time.time()
    window_start = now - 60.0
    with _rate_lock:
        bucket = [t for t in _rate_state.get(key, []) if t >= window_start]
        if len(bucket) >= limit_per_min:
            _rate_state[key] = bucket
            return {"allowed": False, "retry_after": int(window_start + 60 - now) + 1,
                    "limit": limit_per_min, "remaining": 0}
        bucket.append(now)
        _rate_state[key] = bucket
        return {"allowed": True, "limit": limit_per_min, "remaining": max(0, limit_per_min - len(bucket))}


def rate_limit_check(agent_token_id: int, agent_id: str, limit_per_min: int) -> dict:
    """per-token + per-agent(tenant) 双重限流，任一超限即拒绝。"""
    token_hit = _memory_rate_limit(f"token:{int(agent_token_id)}", limit_per_min)
    if not token_hit["allowed"]:
        return token_hit
    tenant_hit = _memory_rate_limit(f"tenant:{agent_id}", max(limit_per_min * 5, 300))
    return tenant_hit


# ── token 生成/校验 ─────────────────────────────────────────────────
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """返回 (full_token, prefix, token_hash)。仅存哈希。"""
    body = secrets.token_hex(24)
    full = f"{TOKEN_PREFIX}{body}"
    prefix = full[: len(TOKEN_PREFIX) + 8]
    return full, prefix, _hash_token(full)


def parse_scopes(raw: Optional[str | Iterable[str]]) -> set[str]:
    if not raw:
        return {SCOPE_R}
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.replace(",", " ").split() if p.strip()]
    else:
        parts = [str(p).strip().upper() for p in raw if str(p).strip()]
    scopes = {p for p in parts if p in ALL_SCOPES}
    if not scopes:
        scopes = {SCOPE_R}
    return scopes


class AgentTokenError(Exception):
    def __init__(self, code: str, message: str, http: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http = http


def issue_token(agent_id: str = "default", scopes: str | Iterable[str] = "R",
                paper_only: bool = True, rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
                markets: str = "", instruments: str = "", expires_at: Optional[str] = None,
                ) -> dict:
    """签发 token，返回含 full_token(仅此一次)的记录。"""
    store.ensure_schema()
    scopes_set = parse_scopes(scopes)
    full, prefix, token_hash = generate_token()
    con = store.get_conn()
    try:
        cur = con.execute(
            "INSERT INTO agent_tokens(token_hash,prefix,agent_id,scopes,paper_only,"
            "rate_limit_per_min,markets,instruments,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (token_hash, prefix, agent_id, ",".join(sorted(scopes_set)),
             int(paper_only), rate_limit_per_min, markets, instruments, expires_at))
        con.commit()
        tok_id = cur.lastrowid
    finally:
        con.close()
    return {"id": tok_id, "agent_id": agent_id, "scopes": sorted(scopes_set),
            "paper_only": bool(paper_only), "rate_limit_per_min": rate_limit_per_min,
            "markets": markets, "instruments": instruments, "expires_at": expires_at,
            "prefix": prefix, "full_token": full}


def _token_row(token_hash: str):
    con = store.get_conn()
    try:
        return store.to_dict(con.execute(
            "SELECT * FROM agent_tokens WHERE token_hash=?", (token_hash,)).fetchone())
    finally:
        con.close()


def verify_token(token: str) -> dict:
    """校验 token → 记录；无效/过期/被吊销抛 AgentTokenError。"""
    if not token:
        raise AgentTokenError("missing_token", "缺少 agent token")
    row = _token_row(_hash_token(token))
    if not row:
        raise AgentTokenError("invalid_token", "token 无效")
    if row.get("revoked"):
        raise AgentTokenError("revoked_token", "token 已吊销")
    exp = row.get("expires_at")
    if exp:
        try:
            if time.time() > time.mktime(time.strptime(str(exp)[:19], "%Y-%m-%d %H:%M:%S")):
                raise AgentTokenError("expired_token", "token 已过期")
        except (ValueError, TypeError):
            pass
    row["scopes_list"] = sorted(parse_scopes(row.get("scopes")))
    row["paper_only"] = bool(row.get("paper_only"))
    return row


def has_scope(tok: dict, scope: str) -> bool:
    return scope in tok.get("scopes_list", [])


def revoke_token_record(token_id: int, agent_id: Optional[str] = None) -> bool:
    con = store.get_conn()
    try:
        if agent_id is not None:
            cur = con.execute("UPDATE agent_tokens SET revoked=1 WHERE id=? AND agent_id=?",
                              (token_id, agent_id))
        else:
            cur = con.execute("UPDATE agent_tokens SET revoked=1 WHERE id=?", (token_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_tokens(agent_id: Optional[str] = None) -> list[dict]:
    con = store.get_conn()
    try:
        if agent_id is not None:
            rows = con.execute(
                "SELECT id,prefix,agent_id,scopes,paper_only,rate_limit_per_min,expires_at,"
                "revoked,created_at FROM agent_tokens WHERE agent_id=? ORDER BY id DESC",
                (agent_id,)).fetchall()
        else:
            rows = con.execute(
                "SELECT id,prefix,agent_id,scopes,paper_only,rate_limit_per_min,expires_at,"
                "revoked,created_at FROM agent_tokens ORDER BY id DESC").fetchall()
        return store.rows_to_list(rows)
    finally:
        con.close()


# ── 审计 ────────────────────────────────────────────────────────────
def audit(agent_token_id: int, agent_id: str, route: str, scope_class: str,
          status: str, idempotency_key: Optional[str], request_summary: str,
          response_code: int) -> None:
    con = store.get_conn()
    try:
        con.execute(
            "INSERT INTO agent_audit(agent_token_id,agent_id,route,scope_class,status,"
            "idempotency_key,request_summary,response_code) VALUES(?,?,?,?,?,?,?,?)",
            (agent_token_id, agent_id, route, scope_class, status, idempotency_key,
             request_summary[:500], response_code))
        con.commit()
    finally:
        con.close()


# ── 幂等 ────────────────────────────────────────────────────────────
def idempotency_reserve(agent_token_id: int, method: str, route: str,
                        idem_key: str, request_hash: str) -> dict:
    """原子保留幂等键。返回 {'action':'reserved'} 或 {'action':'replay','job_id':..}。"""
    con = store.get_conn()
    try:
        row = con.execute(
            "SELECT * FROM agent_idempotency WHERE agent_token_id=? AND method=? AND route=? AND idem_key=?",
            (agent_token_id, method, route, idem_key)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO agent_idempotency(agent_token_id,method,route,idem_key,request_hash,status)"
                " VALUES(?,?,?,?,?,'pending')",
                (agent_token_id, method, route, idem_key, request_hash))
            con.commit()
            return {"action": "reserved"}
        if row["status"] == "succeeded" and row["job_id"]:
            return {"action": "replay", "job_id": row["job_id"]}
        return {"action": "in_progress"}
    finally:
        con.close()


def idempotency_complete(agent_token_id: int, method: str, route: str,
                         idem_key: str, job_id: str, status: str = "succeeded") -> None:
    con = store.get_conn()
    try:
        con.execute(
            "UPDATE agent_idempotency SET status=?, job_id=? WHERE agent_token_id=? AND method=? AND route=? AND idem_key=?",
            (status, job_id, agent_token_id, method, route, idem_key))
        con.commit()
    finally:
        con.close()


# ── Flask 装饰器：request 鉴权 + 能力级校验 + 限流 + 审计 ────────────────
def require_agent(*required_scopes: str):
    """要求请求具备至少一个指定 scope。注入 request.agent_token / request.agent_scope。"""
    from flask import request, jsonify

    def decorator(fn):
        def wrapper(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
            else:
                token = request.headers.get("X-Agent-Token", "").strip()
            route = request.path
            idem_key = request.headers.get("Idempotency-Key", "").strip()

            try:
                tok = verify_token(token)
            except AgentTokenError as e:
                audit(0, "-", route, "-", "denied", idem_key, token[:8], e.http)
                return jsonify({"code": e.http, "error": {"code": e.code, "message": e.message,
                                                          "retriable": False}}), e.http

            # 能力级
            token_scopes = tok.get("scopes_list", [])
            ok = any(s in token_scopes for s in required_scopes) if required_scopes else True
            if not ok:
                audit(tok["id"], tok["agent_id"], route, ",".join(required_scopes),
                      "denied", idem_key, token[:8], 403)
                return jsonify({"code": 403, "error": {
                    "code": "insufficient_scope",
                    "message": f"需要 scope {'/'.join(required_scopes)}，当前 {token_scopes}",
                    "retriable": False}}), 403

            # 限流
            rl = rate_limit_check(tok["id"], tok["agent_id"], tok.get("rate_limit_per_min", 60))
            if not rl["allowed"]:
                audit(tok["id"], tok["agent_id"], route, ",".join(required_scopes),
                      "denied", idem_key, token[:8], 429)
                resp = jsonify({"code": 429, "error": {"code": "rate_limited",
                                "message": "请求超限，请稍后再试", "retriable": True}})
                resp.headers["Retry-After"] = str(rl["retry_after"])
                return resp, 429

            request.agent_token = tok
            request.agent_token_id = tok["id"]
            request.agent_id = tok["agent_id"]
            request.agent_scope = required_scopes
            request.agent_paper_only = tok.get("paper_only", True)
            request.agent_idempotency_key = idem_key
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator
