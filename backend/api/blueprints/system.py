# -*- coding: utf-8 -*-
"""System blueprint: health, first-run bootstrap, settings, LLM test."""
import os

from flask import Blueprint, request

from ..envelope import ok, err
from .. import settings_store
from ..paths import KLINE_DB, CACHE_DB, FUND_DB, SIM_DB

bp = Blueprint("system", __name__, url_prefix="/api/system")


@bp.route("/health")
def health():
    return ok({"status": "ok", "service": "stock-classroom-web", "version": "5.1"})


@bp.route("/bootstrap")
def bootstrap():
    """First-run gate: report data freshness so the SPA can show the
    welcome/download screen instead of a wall of 'plugin failed' errors."""
    import sqlite3
    from datetime import datetime

    def _fresh(path, table, date_col="date", count=True):
        if not os.path.exists(path):
            return {"exists": False, "max": None, "rows": 0}
        try:
            conn = sqlite3.connect(path, timeout=5)
            conn.row_factory = sqlite3.Row
            if count:
                try:
                    rows = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                except Exception:
                    rows = None
            else:
                # 大表 COUNT(*) 会拖慢应用启动；新鲜度只需要 MAX(date)。
                rows = None
            try:
                if table == "kline_daily":
                    # kline_daily 是年度分表 UNION ALL 视图，直接 MAX 会扫整张视图。
                    year_table = f"kline_{datetime.now().year}"
                    mx = conn.execute(
                        f"SELECT MAX({date_col}) m FROM {year_table}").fetchone()["m"]
                    if not mx:
                        mx = conn.execute(
                            f"SELECT MAX({date_col}) m FROM {table}").fetchone()["m"]
                else:
                    mx = conn.execute(
                        f"SELECT MAX({date_col}) m FROM {table}").fetchone()["m"]
            except Exception:
                mx = None
            conn.close()
            return {"exists": True, "max": mx, "rows": rows}
        except Exception:
            return {"exists": True, "max": None, "rows": 0}

    stock_rows = 0
    try:
        conn = sqlite3.connect(KLINE_DB, timeout=5)
        stock_rows = conn.execute("SELECT COUNT(*) FROM stock_list").fetchone()[0]
        conn.close()
    except Exception:
        stock_rows = 0

    data = {
        "kline": _fresh(KLINE_DB, "kline_daily", count=False),
        "stock_list_rows": stock_rows,
        "cache": _fresh(CACHE_DB, "stock_spot", "updated_at"),
        "fundamental": _fresh(FUND_DB, "fundamental", count=False) if os.path.exists(FUND_DB) else {"exists": False, "max": None, "rows": None},
    }
    data["needs_init"] = (not data["kline"]["exists"]) or stock_rows == 0
    settings = settings_store.load_settings()
    data["settings"] = {
        "theme": settings.get("theme"),
        "font_size": settings.get("font_size"),
        # 外观维度（2026-10-15）：随 bootstrap 一起下发，前端首帧就能用对的外观渲染，
        # 避免"先按默认主题画一帧、拿到 /settings 后再跳变"。
        "density": settings.get("density"),
        "radius": settings.get("radius"),
        "motion": settings.get("motion"),
        "backdrop": settings.get("backdrop"),
    }
    data["ai_configured"] = bool((settings.get("agent") or {}).get("api_key"))
    return ok(data)


@bp.route("/settings", methods=["GET"])
def get_settings():
    s = settings_store.load_settings()
    # 脱敏 api_key: 只回最后4位 + 布尔标记, 不在网络上泄露完整 key
    agent = s.get("agent") or {}
    raw = agent.get("api_key") or ""
    if raw:
        agent = dict(agent)
        agent["api_key"] = "****" + raw[-4:] if len(raw) > 4 else "****"
    s["agent"] = agent
    s["api_key_set"] = bool(raw)
    return ok(s)


@bp.route("/settings", methods=["POST"])
def save_settings():
    body = request.get_json(silent=True) or {}
    current = settings_store.load_settings()
    # 外观维度白名单（2026-10-15 扩充：新增 density/radius/motion/backdrop，
    # 与 theme/font_size 同为「外观」维度，由前端 stores/app.ts 的 applyTheme 消费）。
    # 注意：这里是**白名单**——新增外观项必须同时加到这里，否则前端会静默丢设置。
    for key in ("theme", "font_size", "window_size",
                "density", "radius", "motion", "backdrop"):
        if key in body:
            current[key] = body[key]
    if "agent" in body and isinstance(body["agent"], dict):
        current.setdefault("agent", {})
        new_agent = body["agent"]
        for k, v in new_agent.items():
            if k == "api_key" and (v is None or str(v).startswith("****")):
                continue  # 掩码值不变更
            if v is not None:
                current["agent"][k] = v
    settings_store.save_settings(current)
    return ok(current, message="saved")


@bp.route("/settings/test-llm", methods=["POST"])
def test_llm():
    body = request.get_json(silent=True) or {}
    agent = dict((settings_store.load_settings().get("agent") or {}))
    agent.update({k: v for k, v in body.items() if v is not None})
    if not agent.get("api_key"):
        return err(400, "no_api_key", "请先填写 API Key")
    try:
        from backend.agent.llm_client import LLMClient
        client = LLMClient(api_base=agent.get("api_base"),
                           api_key=agent.get("api_key"),
                           model=agent.get("model"))
        reply = client.complete("你是连通性测试助手", "ping，回复 pong", max_tokens=20)
        return ok({"reply": (reply or "")[:120]}, message="连接成功")
    except Exception as e:
        return err(502, "llm_error", str(e), retriable=True)
