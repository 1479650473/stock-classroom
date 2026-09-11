# -*- coding: utf-8 -*-
"""可观测性指标 —— 任务/数据新鲜度/通知/系统，供 Prometheus 抓取或前端查看。

借鉴 QuantDinger 的 observability（prometheus + grafana + alertmanager）思路，
但按桌面单机版收敛为：**一个 /metrics 文本端点 + 一个 JSON 端点**，零额外依赖。

指标口径：
  sc_jobs_total{kind,status}          任务计数（进程内 jobman 注册表）
  sc_jobs_running                     当前运行中任务数
  sc_job_duration_seconds{kind}       最近任务耗时（成功/失败都算）
  sc_data_latest_date_seconds         行情库最新日期对应的时间戳（越旧越危险）
  sc_data_coverage{date}              最近若干个交易日的股票覆盖数
  sc_notifications_unread             未读通知数
  sc_trader_last_decision_days        距最近一次 AI 操盘手决策的天数
  sc_http_requests_total              本进程处理的请求数（由 server 中间件累加）
  sc_uptime_seconds                   进程运行时长
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import time
from typing import Any, Dict, List

T0 = time.time()


def _age_days(date_str: str) -> float:
    try:
        d = _dt.datetime.strptime(str(date_str)[:8], "%Y%m%d").date()
        return (_dt.date.today() - d).days
    except Exception:
        return -1.0


def _date_ts(date_str: str) -> float:
    try:
        d = _dt.datetime.strptime(str(date_str)[:8], "%Y%m%d")
        return d.timestamp()
    except Exception:
        return 0.0


def collect() -> Dict[str, Any]:
    """采集一遍全部指标（容错：任何子项失败都不影响其它项）。"""
    out: Dict[str, Any] = {"uptime_seconds": round(time.time() - T0, 1),
                           "python": sys.version.split()[0],
                           "ts": _dt.datetime.now().isoformat(timespec="seconds")}
    # 任务
    try:
        from .api import jobman
        jobs = list(getattr(jobman, "_JOBS", {}).values())
        by: Dict[str, Dict[str, int]] = {}
        dur: Dict[str, float] = {}
        for j in jobs:
            k = str(j.get("kind") or "unknown")
            st = str(j.get("status") or "unknown")
            by.setdefault(k, {})[st] = by.setdefault(k, {}).get(st, 0) + 1
            if j.get("started_at") and j.get("finished_at"):
                dur[k] = round(float(j["finished_at"]) - float(j["started_at"]), 2)
        out["jobs"] = {"by_kind_status": by, "running": sum(1 for j in jobs if j.get("status") == "running"),
                       "total": len(jobs), "last_duration_seconds": dur}
    except Exception as e:
        out["jobs"] = {"error": str(e)[:120]}
    # 数据新鲜度
    try:
        import sqlite3
        from .api.paths import KLINE_DB
        con = sqlite3.connect(KLINE_DB)
        latest = con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
        recent = con.execute("SELECT date, COUNT(DISTINCT code) FROM kline_daily "
                             "GROUP BY date ORDER BY date DESC LIMIT 5").fetchall()
        active = con.execute("SELECT COUNT(*) FROM stock_list WHERE status='active'").fetchone()[0]
        con.close()
        out["data"] = {"latest_date": str(latest or ""), "age_days": _age_days(str(latest or "")),
                       "latest_ts": _date_ts(str(latest or "")), "active_stocks": int(active or 0),
                       "recent_coverage": [{"date": str(d), "codes": int(c or 0)} for d, c in recent]}
    except Exception as e:
        out["data"] = {"error": str(e)[:120]}
    # 通知 / 操盘手
    try:
        from . import notify
        out["notifications_unread"] = notify.unread_count()
    except Exception:
        out["notifications_unread"] = -1
    try:
        from .trader import store as tstore
        rows = tstore.list_decisions(1, limit=1) if hasattr(tstore, "list_decisions") else []
        last = str(rows[0].get("trade_date") or "") if rows else ""
        out["trader"] = {"last_decision": last, "age_days": _age_days(last.replace("-", "")) if last else -1}
    except Exception:
        out["trader"] = {"last_decision": "", "age_days": -1}
    # 磁盘
    try:
        from .api.paths import DATA_DIR
        total = 0
        for root, _dirs, files in os.walk(str(DATA_DIR)):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        out["data_dir_bytes"] = total
    except Exception:
        out["data_dir_bytes"] = -1
    return out


def render_prometheus(m: Dict[str, Any]) -> str:
    """输出 Prometheus 文本格式（0.0.4）。"""
    lines: List[str] = []

    def g(name: str, value: Any, labels: str = "", typ: str = "gauge", help_: str = "") -> None:
        if typ == "gauge" and not any(x.startswith(f"# TYPE {name} ") for x in lines):
            lines.append(f"# HELP {name} {help_ or name}")
            lines.append(f"# TYPE {name} {typ}")
        try:
            v = float(value)
        except Exception:
            return
        lines.append(f"{name}{labels} {v}")

    g("sc_uptime_seconds", m.get("uptime_seconds"), help_="API 进程运行时长")
    jobs = m.get("jobs") or {}
    for kind, stats in (jobs.get("by_kind_status") or {}).items():
        for st, n in stats.items():
            lbl = '{kind="%s",status="%s"}' % (kind, st)
            g("sc_jobs_total", n, lbl, typ="counter", help_="任务计数")
    g("sc_jobs_running", jobs.get("running"), help_="运行中任务数")
    for kind, d in (jobs.get("last_duration_seconds") or {}).items():
        g("sc_job_duration_seconds", d, '{kind="%s"}' % kind, help_="最近一次任务耗时")
    data = m.get("data") or {}
    if data.get("latest_ts"):
        g("sc_data_latest_date_seconds", data["latest_ts"], help_="行情库最新日期（时间戳）")
        g("sc_data_staleness_days", data.get("age_days", -1), help_="行情库距今天数")
    g("sc_stocks_active", data.get("active_stocks", -1), help_="股票池 active 数量")
    for row in (data.get("recent_coverage") or []):
        lbl = '{date="%s"}' % (row.get("date") or "")
        g("sc_data_coverage", row.get("codes"), lbl, help_="最近若干交易日的股票覆盖数")
    g("sc_notifications_unread", m.get("notifications_unread", -1), help_="未读通知数")
    tr = m.get("trader") or {}
    if tr.get("age_days", -1) >= 0:
        g("sc_trader_last_decision_days", tr.get("age_days"), help_="距最近一次操盘手决策天数")
    g("sc_data_dir_bytes", m.get("data_dir_bytes", -1), help_="data/ 目录占用字节")
    return "\n".join(lines) + "\n"
