# -*- coding: utf-8 -*-
"""Notify blueprint — 通知/告警（任务失败、每日自动化异常、测试外发）。

GET  /api/notify/list?limit=&unread_only=   通知列表（新→旧）
GET  /api/notify/summary                    未读数
POST /api/notify/read                       {ids?: number[]} 标记已读（空=全部）
POST /api/notify/clear                      清空
GET  /api/notify/settings                   读取 webhook 配置（不回显完整 URL 之外的信息）
POST /api/notify/settings                   {enabled, webhook} 保存
POST /api/notify/test                       发一条测试通知（验证 webhook 是否通）
"""
from __future__ import annotations

from flask import Blueprint, request

from ..envelope import ok, int_arg
from .. import settings_store

bp = Blueprint("notify", __name__, url_prefix="/api/notify")


@bp.route("/list", methods=["GET"])
def list_items():
    from backend import notify
    limit = int_arg(request.args.get("limit"), 50, 1, 300)
    unread = str(request.args.get("unread_only") or "") in ("1", "true", "yes")
    return ok({"items": notify.list_items(limit=limit, unread_only=unread),
               "unread": notify.unread_count()})


@bp.route("/summary", methods=["GET"])
def summary():
    from backend import notify
    return ok({"unread": notify.unread_count()})


@bp.route("/read", methods=["POST"])
def mark_read():
    from backend import notify
    body = request.get_json(force=True, silent=True) or {}
    ids = body.get("ids")
    n = notify.mark_read([int(x) for x in ids] if isinstance(ids, list) and ids else None)
    return ok({"marked": n, "unread": notify.unread_count()})


@bp.route("/clear", methods=["POST"])
def clear():
    from backend import notify
    n = notify.clear()
    return ok({"cleared": n})


@bp.route("/settings", methods=["GET"])
def get_settings():
    s = settings_store.load_settings() or {}
    n = s.get("notify") or {}
    return ok({"enabled": bool(n.get("enabled")), "webhook": str(n.get("webhook") or "")})


@bp.route("/settings", methods=["POST"])
def save_settings():
    body = request.get_json(force=True, silent=True) or {}
    s = settings_store.load_settings() or {}
    cur = s.get("notify") or {}
    if "enabled" in body:
        cur["enabled"] = bool(body["enabled"])
    if "webhook" in body:
        cur["webhook"] = str(body.get("webhook") or "")[:500]
    s["notify"] = cur
    settings_store.save_settings(s)
    return ok({"enabled": bool(cur.get("enabled")), "webhook": cur.get("webhook") or ""},
              message="saved")


@bp.route("/test", methods=["POST"])
def test_push():
    from backend import notify
    item = notify.push("test", "测试通知：链路正常", level="info",
                       detail="来自 /api/notify/test；若配置了 webhook 也会外发一条。",
                       key="", throttle_seconds=0)
    return ok(item)
