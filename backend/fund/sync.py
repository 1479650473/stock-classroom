# -*- coding: utf-8 -*-
"""基金套利数据同步：首次回填 + 每日增量（可独立 CLI 跑）。

CLI:
  python -m backend.fund.sync --backfill            # 首次全量（日线 2018+、净值全量、费率、申购表）
  python -m backend.fund.sync --daily               # 每日增量（名单 + 日线 + 净值 + 申购表）
  python -m backend.fund.sync --fees                # 只刷新费率
  python -m backend.fund.sync --stats               # 看数据状态
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Optional

from . import sources as S
from . import store

BACKFILL_START = "2018-01-01"


def log(*a):
    print(*a, flush=True)


# ---------------- 单标的同步（进程池 worker） ----------------

def _job_daily(code: str, start: str, exchange: Optional[str] = None) -> dict:
    """拉一只的日线增量并落库。"""
    try:
        rows = S.fetch_daily_tx(code, start, exchange=exchange)
        n = store.upsert_daily(rows)
        return {"code": code, "ok": True, "rows": n, "last": rows[-1]["date"] if rows else None}
    except Exception as e:  # noqa: BLE001
        return {"code": code, "ok": False, "err": f"{type(e).__name__}: {e}"}


def _job_nav(code: str, since: Optional[str]) -> dict:
    try:
        rows = S.fetch_nav(code, since=since)
        n = store.upsert_nav(rows)
        return {"code": code, "ok": True, "rows": n, "last": rows[-1]["nav_date"] if rows else None}
    except Exception as e:  # noqa: BLE001
        return {"code": code, "ok": False, "err": f"{type(e).__name__}: {e}"}


def _job_fee(code: str) -> dict:
    try:
        fee = S.fetch_fee(code)
        store.upsert_fee(code, fee["buy_tiers"], fee["redeem_tiers"])
        return {"code": code, "ok": True, "redeem": len(fee["redeem_tiers"]), "buy": len(fee["buy_tiers"])}
    except Exception as e:  # noqa: BLE001
        return {"code": code, "ok": False, "err": f"{type(e).__name__}: {e}"}


def _run_pool(fn, args_list: List[tuple], workers: int, tag: str) -> dict:
    ok = fail = rows = 0
    errs = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, *a): a[0] for a in args_list}
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            if r.get("ok"):
                ok += 1
                rows += r.get("rows") or 0
            else:
                fail += 1
                errs.append(f"{r.get('code')}: {r.get('err')}")
            if i % 50 == 0 or i == len(args_list):
                log(f"  [{tag}] {i}/{len(args_list)} ok={ok} fail={fail} rows={rows} {time.time()-t0:.0f}s")
    return {"ok": ok, "fail": fail, "rows": rows, "errors": errs[:20]}


# ---------------- 名单 / 申购表 ----------------

def sync_list() -> dict:
    rows = S.fetch_lof_list()
    n = store.upsert_list(rows)
    store.set_meta("lof_list_updated", _dt.datetime.now().isoformat(timespec="seconds"))
    return {"lof_count": len(rows), "written": n}


def sync_purchase() -> dict:
    rows = S.fetch_purchase_all()
    n = store.upsert_purchase(rows)
    store.set_meta("purchase_updated", _dt.datetime.now().isoformat(timespec="seconds"))
    return {"funds": len(rows), "written": n}


def _norm_date(d) -> Optional[str]:
    """kline.db 里日期有 YYYYMMDD / YYYY-MM-DD 两种写法，统一成后者（否则字符串比较永远不等）。"""
    if not d:
        return None
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def market_last_date() -> Optional[str]:
    """本库已知的最近交易日（market_daily 为主，etf_daily 兜底；格式统一 YYYY-MM-DD）。"""
    try:
        from ..api.paths import KLINE_DB
        con = sqlite3.connect(KLINE_DB, timeout=10)
        for tbl in ("market_daily", "etf_daily"):
            try:
                row = con.execute(f"SELECT MAX(date) FROM {tbl}").fetchone()
                d = _norm_date(row[0] if row else None)
                if d:
                    return d
            except Exception:
                continue
        return None
    except Exception:
        return None


# ---------------- 对外主流程 ----------------

def ensure_list() -> List[dict]:
    lofs = store.list_lofs()
    if not lofs:
        sync_list()
        lofs = store.list_lofs()
    return lofs


def backfill(start: str = BACKFILL_START, workers: int = 4, with_fees: bool = True) -> dict:
    log(f"[backfill] 名单 …")
    r_list = sync_list()
    lofs = store.list_lofs()
    log(f"[backfill] LOF {len(lofs)} 只；日线 {start} 起（{workers} 进程）")
    jobs = [(l["code"], start, l.get("exchange")) for l in lofs]
    r_daily = _run_pool(_job_daily, jobs, workers, "daily")
    log("[backfill] 净值（全历史）…")
    jobs = [(l["code"], "2015-01-01") for l in lofs]
    r_nav = _run_pool(_job_nav, jobs, workers, "nav")
    if with_fees:
        log("[backfill] 费率 …")
        jobs = [(l["code"],) for l in lofs]
        r_fee = _run_pool(_job_fee, jobs, max(2, workers // 2), "fee")
    else:
        r_fee = {}
    log("[backfill] 申购状态全表 …")
    r_pur = sync_purchase()
    store.set_meta("backfilled_at", _dt.datetime.now().isoformat(timespec="seconds"))
    out = {"list": r_list, "daily": r_daily, "nav": r_nav, "fee": r_fee, "purchase": r_pur, "stats": store.stats()}
    log("[backfill] 完成:", json.dumps(out["stats"], ensure_ascii=False))
    return out


def run_daily(workers: int = 4) -> dict:
    """每日增量：名单 → 日线（用到最近交易日）→ 净值（只补有新净值的）→ 申购表。"""
    t0 = time.time()
    out: dict = {}
    # 1) 名单（新浪实时快照，顺带发现新 LOF）
    try:
        out["list"] = sync_list()
    except Exception as e:  # noqa: BLE001
        out["list"] = {"error": f"{type(e).__name__}: {e}"}
    lofs = store.list_lofs()
    if not lofs:
        return {"error": "no_lof_list"}

    # 2) 申购表（一次请求，同时给出各基金最新净值日期 → 决定谁需要拉净值）
    try:
        out["purchase"] = sync_purchase()
    except Exception as e:  # noqa: BLE001
        out["purchase"] = {"error": f"{type(e).__name__}: {e}"}

    # 3) 日线增量：从各自最新日期回看 7 天（覆盖修复）；缺失的从 BACKFILL_START 起
    mkt_last = market_last_date()
    jobs = []
    for l in lofs:
        last = store.last_daily_date(l["code"])
        if mkt_last and last and last >= mkt_last:
            continue  # 已到最近交易日
        if last:
            start = (_dt.date.fromisoformat(last) - _dt.timedelta(days=7)).isoformat()
        else:
            start = BACKFILL_START
        jobs.append((l["code"], start, l.get("exchange")))
    log(f"[daily] 日线增量 {len(jobs)} 只（最近交易日 {mkt_last}）")
    out["daily"] = _run_pool(_job_daily, jobs, workers, "daily") if jobs else {"ok": 0, "fail": 0, "rows": 0, "skipped": True}

    # 4) 净值增量：只拉「申购表净值日期 > 本地最新净值日期」的
    from .store import conn
    c = conn()
    pur = {r[0]: r[1] for r in c.execute("SELECT code, nav_date FROM fund_purchase").fetchall()}
    jobs = []
    for l in lofs:
        code = l["code"]
        local = store.last_nav_date(code)
        remote = pur.get(code)
        if local is None:
            jobs.append((code, "2015-01-01"))
        elif remote and remote > local:
            jobs.append((code, local))   # 从本地最新日开始补
    log(f"[daily] 净值增量 {len(jobs)} 只")
    out["nav"] = _run_pool(_job_nav, jobs, workers, "nav") if jobs else {"ok": 0, "fail": 0, "rows": 0, "skipped": True}

    out["elapsed"] = round(time.time() - t0, 1)
    out["stats"] = store.stats()
    store.set_meta("last_daily_sync", _dt.datetime.now().isoformat(timespec="seconds"))
    log("[daily] 完成:", json.dumps(out["stats"], ensure_ascii=False), f"{out['elapsed']}s")
    return out


def refresh_fees(workers: int = 3, stale_days: int = 30) -> dict:
    from .store import conn
    c = conn()
    have = {r[0]: r[1] for r in c.execute("SELECT code, updated_at FROM fund_fee").fetchall()}
    lofs = store.list_lofs()
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=stale_days)).strftime("%Y-%m-%d")
    jobs = [(l["code"],) for l in lofs if (l["code"] not in have) or (have.get(l["code"]) or "") < cutoff]
    log(f"[fees] 需刷新 {len(jobs)}/{len(lofs)} 只")
    return _run_pool(_job_fee, jobs, workers, "fee") if jobs else {"ok": 0, "fail": 0, "rows": 0, "skipped": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="基金套利数据同步")
    ap.add_argument("--backfill", action="store_true", help="首次全量回填")
    ap.add_argument("--daily", action="store_true", help="每日增量")
    ap.add_argument("--fees", action="store_true", help="刷新费率")
    ap.add_argument("--list", action="store_true", help="只刷新 LOF 名单")
    ap.add_argument("--stats", action="store_true", help="数据状态")
    ap.add_argument("--start", default=BACKFILL_START)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.stats:
        log(json.dumps(store.stats(), ensure_ascii=False, indent=1))
        return
    if a.list:
        log(json.dumps(sync_list(), ensure_ascii=False)); return
    if a.backfill:
        backfill(start=a.start, workers=a.workers); return
    if a.fees:
        log(json.dumps(refresh_fees(workers=min(3, a.workers)), ensure_ascii=False)); return
    if a.daily:
        log(json.dumps(run_daily(workers=a.workers)["stats"], ensure_ascii=False)); return
    ap.print_help()


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))))
    main()
