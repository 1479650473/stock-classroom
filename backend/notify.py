# -*- coding: utf-8 -*-
"""通知/告警 —— 任务失败、每日自动化异常、操盘手出错时留痕并可选外发。

设计取舍（参考 QuantDinger 的 notifications 服务，但只保留对桌面单机版有意义的部分）：
  - **本地事件流为主**：所有通知落 `data/notifications.json`（带未读标记），
    前端任务中心展示；不依赖任何外部服务即可用。
  - **Webhook 可选**：settings.json 里配 `notify.webhook`（企业微信/钉钉/飞书/Slack 的
    通用 JSON POST），配了才外发；外发失败只记本地，不影响主流程。
  - **去重节流**：同一 (kind, key) 在 throttle_seconds 内只记一条，避免刷屏。

用法：
    from backend import notify
    notify.push("daily", "每日自动化有步骤失败", level="error", detail="kline: timeout")
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

from .api.paths import DATA_DIR

PATH = os.path.join(str(DATA_DIR), "notifications.json")
MAX_KEEP = 500
DEFAULT_THROTTLE_S = 300

_lock = threading.Lock()
_last: Dict[str, float] = {}


def _load() -> List[Dict[str, Any]]:
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(items[-MAX_KEEP:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _webhook() -> Dict[str, str]:
    """从 settings.json 读 webhook 配置（不存在则视为未开启）。"""
    try:
        from .api.settings_store import load_settings
        s = load_settings() or {}
        n = s.get("notify") or {}
        return {"url": str(n.get("webhook") or ""), "enabled": bool(n.get("enabled"))}
    except Exception:
        return {"url": "", "enabled": False}


def _post_webhook(url: str, payload: Dict[str, Any], timeout: float = 6.0) -> bool:
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def push(kind: str, title: str, level: str = "info", detail: str = "",
         key: str = "", throttle_seconds: int = DEFAULT_THROTTLE_S,
         extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """记一条通知。返回该通知记录（被节流时返回上一条的占位）。"""
    k = f"{kind}:{key or title}"
    now = time.time()
    with _lock:
        if throttle_seconds and now - _last.get(k, 0) < throttle_seconds:
            return {"throttled": True, "kind": kind, "title": title}
        _last[k] = now
        item = {"id": int(now * 1000), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": kind, "level": level, "title": title, "detail": (detail or "")[:2000],
                "read": False, "extra": extra or {}}
        items = _load()
        items.append(item)
        _save(items)
    wh = _webhook()
    if wh.get("enabled") and wh.get("url"):
        icon = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(level, "•")
        payload = {"msgtype": "text",
                   "text": {"content": f"{icon} [{kind}] {title}\n{detail}"[:1800]}}
        item["webhook_ok"] = _post_webhook(wh["url"], payload)
    return item


def list_items(limit: int = 50, unread_only: bool = False) -> List[Dict[str, Any]]:
    items = _load()
    if unread_only:
        items = [x for x in items if not x.get("read")]
    return list(reversed(items))[: max(1, int(limit))]


def unread_count() -> int:
    return sum(1 for x in _load() if not x.get("read"))


def mark_read(ids: Optional[List[int]] = None) -> int:
    """标记已读；ids 为空表示全部已读。返回变更条数。"""
    with _lock:
        items = _load()
        n = 0
        for x in items:
            if ids and x.get("id") not in ids:
                continue
            if not x.get("read"):
                x["read"] = True
                n += 1
        _save(items)
        return n


def clear() -> int:
    with _lock:
        n = len(_load())
        _save([])
        return n
