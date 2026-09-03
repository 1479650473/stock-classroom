# -*- coding: utf-8 -*-
"""Scheduler blueprint — AI 定时自主交易 (每日收盘后自动: 数据更新→策略进化→守护真卖).

配置存 settings.json: { "auto_agent": { enabled, at:"15:30", use_llm, hp, idempotent_day } }

后台 daemon 线程每分钟检查: 交易日 且 到达 at 时刻 且 当日未跑过 → 提交 job 跑 run()。
run() = ① update_daily.run() → ② run_optimize_loop(写入AI账户) → ③ run_day_guard(dry_run=False 真卖)
       → ④ 报告追加 data/agent_day_log.md; 结果写 data/agent_scheduler.json。
也可 /run-now 手动触发一次(测试/补跑)。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from flask import Blueprint, request

from ..envelope import ok, err
from ..paths import DATA_DIR
from .. import jobman
from .. import settings_store

bp = Blueprint("scheduler", __name__, url_prefix="/api/scheduler")

_DEFAULTS = {"enabled": False, "at": "15:30", "use_llm": True, "hp": 20,
             "last_run": None, "last_status": None, "last_finish": None}

_thread = None
_thread_flag = threading.Event()


def _cfg() -> dict:
    s = settings_store.load_settings()
    aa = s.get("auto_agent") or {}
    cfg = dict(_DEFAULTS)
    cfg.update({k: v for k, v in aa.items() if v is not None})
    return cfg


def _save_cfg(cfg: dict) -> None:
    s = settings_store.load_settings()
    s["auto_agent"] = cfg
    settings_store.save_settings(s)


def _marker() -> dict:
    try:
        with open(os.path.join(DATA_DIR, "agent_scheduler.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_marker(data: dict) -> None:
    try:
        with open(os.path.join(DATA_DIR, "agent_scheduler.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _append_log(text: str) -> None:
    try:
        path = os.path.join(DATA_DIR, "agent_day_log.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
    except Exception:
        pass


def _is_trading_day() -> bool:
    """简单交易日判断: 周一~周五(日历缓存可用则用之)."""
    try:
        from update_daily import _is_trading_day as _chk   # noqa: PLC0415
        return bool(_chk())
    except Exception:
        return datetime.now().weekday() < 5


# ──────────────────────── 核心运行(供线程 + run-now 复用; 内部提交job) ────────────────────────
def _build_runner(cfg: dict):
    """构造带进度上报的 job runner. 在 job 线程内执行(不阻塞 HTTP)."""
    def _work(payload, on_progress):
        use_llm = bool(cfg.get("use_llm", True))
        hp = int(cfg.get("hp", 20))
        report = {"started": datetime.now().isoformat(timespec="seconds"), "steps": {}}

        # ① 数据更新(pool 优先, paper 重结算慢 → skip to keep 收盘窗口)
        on_progress({"msg": "① 数据更新(量化池)...", "pct": 8})
        try:
            from backend.update_daily import run as _upd  # noqa: PLC0415
            r = _upd(pool_only=False, skip_paper=True)
            report["steps"]["update_daily"] = {"ok": r.get("ok", False),
                                               "elapsed": r.get("elapsed"),
                                               "skipped": r.get("skipped", False)}
        except Exception as e:
            report["steps"]["update_daily"] = {"error": str(e)[:150]}
            on_progress({"msg": "⚠ 数据更新失败, 继续进化", "pct": 20})

        # ② 策略进化(写入 AI 账户)
        on_progress({"msg": "② 策略进化(LLM提案→回测→裁决→写入)...", "pct": 30})
        try:
            from backend.strategy.optimize_loop import run_optimize_loop  # noqa: PLC0415
            r = run_optimize_loop(use_llm=use_llm, hp=hp, persist=True,
                                  progress=lambda m: on_progress({"msg": "   " + str(m), "pct": _progress_from_msg(m)}))
            report["steps"]["optimize"] = {"verdict": r.get("verdict"), "best": r.get("best"),
                                           "proposal": ((r.get("proposal") or {}).get("name") if r.get("proposal") else None)}
            if r.get("error"):
                report["steps"]["optimize"]["error"] = r["error"]
        except Exception as e:
            report["steps"]["optimize"] = {"error": str(e)[:150]}
            on_progress({"msg": "⚠ 策略进化失败", "pct": 80})

        # ③ 持仓守护(真卖)
        on_progress({"msg": "③ 持仓守护(真卖)...", "pct": 88})
        try:
            from backend.strategy.day_guard import run_day_guard  # noqa: PLC0415
            dg = run_day_guard(dry_run=False)
            report["steps"]["day_guard"] = {"n_checked": dg.get("n_checked"),
                                            "n_sold": dg.get("n_sold")}
        except Exception as e:
            report["steps"]["day_guard"] = {"error": str(e)[:150]}

        # ④ 净值快照 + 日志
        on_progress({"msg": "④ 记账+复盘日志...", "pct": 96})
        try:
            from trade_engine.engine import TradeEngine  # noqa: PLC0415
            eng = TradeEngine()
            snaps = []
            for a in eng.list_accounts():
                s = eng.snapshot_nav(a["id"])
                if s:
                    snaps.append((a["name"], s.get("nav")))
            report["steps"]["nav_snapshot"] = snaps
        except Exception as e:
            report["steps"]["nav_snapshot"] = {"error": str(e)[:150]}

        report["finished"] = datetime.now().isoformat(timespec="seconds")
        report["ok"] = True
        _write_marker(report)
        line = (
            f"\n\n## {report['started'][:16]} 定时自主交易\n"
            f"update_daily: {json.dumps(report['steps'].get('update_daily', {}), ensure_ascii=False)[:120]}\n"
            f"optimize: {json.dumps(report['steps'].get('optimize', {}), ensure_ascii=False)[:160]}\n"
            f"day_guard: {json.dumps(report['steps'].get('day_guard', {}), ensure_ascii=False)[:120]}\n"
        )
        _append_log(line)
        on_progress({"msg": "✓ 定时自主交易完成", "pct": 100})
        return report

    return _work


def _progress_from_msg(m: str) -> int:
    """把 optimize_loop 的阶段消息转个粗略进度. 简单估计: 阶段序号→百分比."""
    s = str(m)
    if s.startswith("①"):
        return 45
    if s.startswith("②"):
        return 55
    if s.startswith("③"):
        return 62
    if s.startswith("④"):
        return 72
    if s.startswith("⑤"):
        return 84
    return 88 if s.startswith("写入") else 30


def _try_trigger_manual(time_slot: bool = False) -> dict:
    """手动/到点触发, 提交 job.

    time_slot=True(后台自动到点): 带当日幂等(同一自然日只自动跑一次);
    time_slot=False(run-now): 每次都能重跑, 方便测试/补跑.
    """
    cfg = _cfg()
    if time_slot:
        today = datetime.now().strftime("%Y%m%d")
        marker = _marker()
        if marker.get("last_run", "").startswith(today) and not marker.get("run_manual"):
            return {"queued": False, "reason": "今日已自动跑过"}
    job = jobman.submit("scheduler_run", _build_runner(cfg), {})
    _marker_update(job["job_id"])
    return {"queued": True, "job_id": job["job_id"]}


def _marker_update(job_id: str) -> None:
    m = _marker()
    m["last_run"] = datetime.now().isoformat(timespec="seconds")
    m["job_id"] = job_id
    m["run_manual"] = True
    _write_marker(m)


def _loop():
    while not _thread_flag.wait(60 * 20):  # 每20分钟检查一次(轻负载)
        try:
            cfg = _cfg()
            if not cfg.get("enabled"):
                continue
            now = datetime.now()
            at = str(cfg.get("at", "15:30")).strip()
            hh, mm = 15, 30
            try:
                hh, mm = map(int, at.split(":"))
            except Exception:
                pass
            if now.hour != hh or now.minute < mm or now.minute >= mm + 30:
                continue
            if now.weekday() >= 5:
                continue
            today = now.strftime("%Y%m%d")
            marker = _marker()
            if str(marker.get("last_run", "")).startswith(today):
                continue
            if not _is_trading_day():
                continue
            _try_trigger_manual(time_slot=True)  # 自动触发(带当日幂等)
        except Exception as e:
            _append_log("[scheduler] loop error: %s" % str(e)[:100])

def _ensure_thread():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="agent-scheduler", daemon=True)
        _thread.start()


# ──────────────────────── 路由 ────────────────────────
@bp.route("", methods=["GET"])
def get_config():
    _ensure_thread()
    cfg = _cfg()
    marker = _marker()
    return ok({**cfg, "last_finish": marker.get("finished"),
               "last_job": marker.get("job_id"), "log": _tail_log(30)})


@bp.route("", methods=["POST"])
def save_config():
    _ensure_thread()
    body = request.get_json(force=True, silent=True) or {}
    cfg = _cfg()
    for k in ("enabled", "at", "use_llm", "hp"):
        if k in body:
            cfg[k] = body[k]
    _save_cfg(cfg)
    return ok(cfg, message="saved")


@bp.route("/run-now", methods=["POST"])
def run_now():
    _ensure_thread()
    r = _try_trigger_manual(time_slot=False)
    if r.get("queued"):
        return ok({"queued": True, "job_id": r["job_id"]}, message="定时自主交易已排队")
    return ok({"queued": False, "reason": r.get("reason")}, message="今日已跑过")


@bp.route("/log", methods=["GET"])
def get_log():
    return ok({"log": _tail_log(200)})


def _tail_log(n: int) -> str:
    try:
        path = os.path.join(DATA_DIR, "agent_day_log.md")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return "".join(lines)
    except Exception:
        return ""
