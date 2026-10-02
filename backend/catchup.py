# -*- coding: utf-8 -*-
"""catchup.py — 数据补全审计与自愈 (update_daily 因关机/待机错过时的补数).

场景: 17:00 任务因电脑关机/待机未运行 → 下次启动时:
  1) audit(): 以最近 N 个交易日为窗口, 检查各日频表完整性:
     - K线: 某天只有部分股票的"残缺日"(覆盖率 < 80% 中位数) + 整日缺失
     - limit_up/lhb_daily/margin_daily/industry_pe/market_daily/board_daily: 缺失交易日
     - 自愈类(north_flow/high_low/fund_flow/etf): 仅报告落后情况
  2) run_catchup(): 按缺口补拉 (K线窗口 / 缺失日期逐日 / 派生子进程 / 纸面盘逐日回放)

设计原则:
  - 窗口 = max(LOOKBACK, 距上次运行交易日数 + 5), 堵住"停机多久就漏多久"
  - T+1 发布的表(lhb/margin)给 1 个交易日宽限, 避免把"还没发布"当缺失天天重拉
  - 单表单次最多补 MAX_FILL_DATES 天(防反爬风暴), 剩余下次继续
"""
from __future__ import annotations

import os
import sqlite3
import statistics
import time
from datetime import datetime, timedelta

from data_manager import KLINE_DB, get_kline_db, update_codes

LOOKBACK = 20          # 至少回看 20 个交易日
MAX_FILL_DATES = 40    # 单表单次最多补的日期数
SKIP_RATIO = 0.80      # 残缺日判定: 覆盖率 < 中位数 × 0.8

# 应按交易日逐日有数据的表: (表名, 日期列, T+1宽限交易日数)
DAILY_TABLES = [
    ("limit_up", "date", 0),
    ("lhb_daily", "trade_date", 1),
    ("margin_daily", "date", 1),
    ("industry_pe", "date", 0),
    ("market_daily", "date", 0),
    ("board_daily", "date", 0),
]
# 自愈/快照类(仅报告, 不需专门补): 表名 → 与 kline 比 max(date)
SOFT_TABLES = ["north_flow", "high_low", "fund_flow_daily", "etf_daily"]


def _d8(d: str) -> str:
    return str(d).replace("-", "")[:8]


def _dash(d: str) -> str:
    d = _d8(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def load_marker(path: str) -> dict:
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def last_run_info(marker_path: str):
    """上次运行信息: (last_run_iso or None, days_ago or None)."""
    m = load_marker(marker_path)
    iso = m.get("finished") or m.get("started")
    if not iso:
        return None, None
    try:
        t = datetime.fromisoformat(str(iso)[:19])
        return iso, max(0, (datetime.now() - t).days)
    except Exception:
        return iso, None


def trading_days_between(cal, start: str, end: str):
    """(start, end] 区间内交易日列表(升序, YYYY-MM-DD)."""
    if not cal:
        return []
    return sorted(d for d in cal if start < d <= end)


def _cal_window(cal, today: str, lookback: int, gap_days: int | None):
    """审计窗口: 最近 max(lookback, gap+5) 个(≤today 的)交易日."""
    upto = sorted(d for d in (cal or set()) if d <= today)
    n = lookback if gap_days is None else max(lookback, gap_days + 5)
    n = min(n, 250)
    return upto[-n:] if upto else []


def _table_dates(conn, table: str, col: str, start: str) -> set:
    """表内 >= start 的已有日期集合(兼容 YYYYMMDD 与 YYYY-MM-DD 两种格式)."""
    dash = _dash(start)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM {table} WHERE {col} >= ? OR {col} >= ?",
            (start, dash)).fetchall()
        return {_d8(r[0]) for r in rows if r[0]}
    except Exception:
        return set()


def _kline_coverage(dates: list) -> dict:
    """K线窗口内逐日覆盖率: {date8: n_stocks}. 只扫涉及的年度分表."""
    if not dates:
        return {}
    start = _d8(dates[0])
    conn = get_kline_db()
    try:
        years = sorted({d[:4] for d in dates})
        counts = {}
        for y in years:
            t = f"kline_{y}"
            try:
                for r in conn.execute(
                        f"SELECT date, COUNT(DISTINCT code) FROM {t} WHERE date >= ? GROUP BY date",
                        (start,)):
                    counts[_d8(r[0])] = int(r[1])
            except Exception:
                continue
        return counts
    finally:
        conn.close()


def audit(cal, today: str, marker_path: str, lookback: int = LOOKBACK) -> dict:
    """完整性审计. 返回 {ref, window, gap_days, kline:{...}, tables:{...}, soft:{...}, missing_total}."""
    iso, gap_days = last_run_info(marker_path)
    window = _cal_window(cal, today, lookback, gap_days)
    ref = window[-1] if window else today
    out = {"last_run": iso, "gap_days": gap_days, "ref": ref,
           "window": [window[0], window[-1]] if window else [], "n_window": len(window),
           "kline": {}, "tables": {}, "soft": {}, "missing_total": 0}

    # ---- K线: 残缺日 + 整日缺失 ----
    cov = _kline_coverage(window)
    if cov:
        med = statistics.median(cov.values())
        partial = sorted(d for d, c in cov.items() if c < med * SKIP_RATIO)
        missing = sorted(_d8(d) for d in window if _d8(d) not in cov)
    else:
        partial, missing = [], sorted(_d8(d) for d in window)
    out["kline"] = {"partial": partial, "missing": missing,
                    "coverage_tail": dict(list(sorted(cov.items()))[-5:])}
    out["missing_total"] += len(partial) + len(missing)

    # ---- 日频表 ----
    conn = get_kline_db()
    try:
        start = _d8(window[0]) if window else _d8(today)
        # T+1 宽限: 参考日回退 n 个交易日
        for table, col, grace in DAILY_TABLES:
            ref_idx = len(window) - 1 - int(grace)
            refd = _d8(window[ref_idx]) if ref_idx >= 0 else None
            have = _table_dates(conn, table, col, start)
            if refd is None:
                out["tables"][table] = {"missing": [], "grace": grace, "note": "窗口过小"}
                continue
            miss = sorted(_d8(d) for d in window if _d8(d) <= refd and _d8(d) not in have)
            out["tables"][table] = {"missing": miss, "grace": grace}
            out["missing_total"] += len(miss)
        # ---- 自愈/快照类: 报告落后 ----
        kmax = max(cov) if cov else (_d8(ref) if ref else "")
        for table in SOFT_TABLES:
            try:
                r = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()
                tmax = _d8(r[0]) if r and r[0] else ""
                lag = None
                if kmax and tmax and tmax < kmax:
                    lag = f"{tmax} → {kmax}"
            except Exception:
                tmax, lag = "", None
            out["soft"][table] = {"max": tmax, "kline_max": kmax, "lag": lag}
    finally:
        conn.close()
    return out


def audit_text(a: dict) -> str:
    """审计摘要(单行文本, 供日志/通知)."""
    k = a.get("kline", {})
    parts = []
    if k.get("missing"):
        parts.append(f"K线缺 {len(k['missing'])} 日:{','.join(k['missing'][:3])}…")
    if k.get("partial"):
        parts.append(f"K线残缺 {len(k['partial'])} 日:{','.join(k['partial'][:3])}…")
    for t, v in (a.get("tables") or {}).items():
        if v.get("missing"):
            parts.append(f"{t} 缺 {len(v['missing'])} 日")
    if not parts:
        return "无缺口"
    return "; ".join(parts)


# ══════════════════════════════════════════════════════
#  执行补全
# ══════════════════════════════════════════════════════
def kline_window_days(a: dict, cal, today: str) -> int:
    """K线补全窗口(bar数): 按最早缺口日→今天的交易日数 + 5. 无缺口返回 0."""
    k = a.get("kline", {})
    gaps = list(k.get("missing") or []) + list(k.get("partial") or [])
    if not gaps:
        return 0
    earliest = min(gaps)
    n_td = len(trading_days_between(cal, _dash(earliest), today)) if cal else 30
    return max(10, n_td + 5)


def run_catchup(a: dict, cal, today: str, lg=None, kline=True) -> dict:
    """执行补全. lg: logger. kline=False 时跳过 K 线(调用方已处理)."""
    def _log(msg):
        if lg:
            lg.info("  [补全] %s", msg)

    res = {}
    # ① K线(全市场, 动态窗口)
    if kline:
        w = kline_window_days(a, cal, today)
        if w:
            try:
                conn = get_kline_db()
                codes = [str(r[0]) for r in conn.execute(
                    "SELECT code FROM stock_list WHERE status='active' OR status IS NULL")]
                conn.close()
                t0 = time.time()
                rk = update_codes(codes, catch_up_days=w, workers=12)
                res["kline"] = {"window": w, "updated": rk.get("updated"),
                                "errors": rk.get("errors"), "rows": rk.get("rows_added"),
                                "elapsed": round(time.time() - t0, 1)}
                _log(f"K线窗口{w}: 更新{rk.get('updated')} 失败{rk.get('errors')} +{rk.get('rows_added')}行")
            except Exception as e:
                res["kline"] = {"error": str(e)[:100]}
                _log(f"K线补全失败: {str(e)[:80]}")

    # ② 日频表逐日补
    for table, v in (a.get("tables") or {}).items():
        miss = (v.get("missing") or [])[:MAX_FILL_DATES]
        if not miss:
            continue
        try:
            if table == "limit_up":
                from data_manager import cache_limit_up_from_akshare
                n = sum(cache_limit_up_from_akshare(d) or 0 for d in miss)
                res[table] = {"dates": len(miss), "rows": n}
            elif table == "lhb_daily":
                from data_manager import update_lhb_range
                n = sum(update_lhb_range(d, d) or 0 for d in miss)
                res[table] = {"dates": len(miss), "rows": n}
            elif table == "margin_daily":
                from data_manager import init_lhb_margin_tables, update_margin_dates
                init_lhb_margin_tables()
                r = update_margin_dates([_d8(d) for d in miss])
                res[table] = {"dates": len(miss), "rows": r.get("rows"), "ok": r.get("ok")}
            elif table == "industry_pe":
                from data_manager import cache_industry_pe
                n = sum(cache_industry_pe(d) or 0 for d in miss)
                res[table] = {"dates": len(miss), "rows": n}
            elif table == "market_daily":
                import subprocess, sys
                span = max(5, (datetime.now() - datetime.strptime(miss[0], "%Y%m%d")).days + 2)
                script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "scripts", "rebuild_market_daily.py")
                logdir = os.path.join(os.path.dirname(KLINE_DB), "logs")
                os.makedirs(logdir, exist_ok=True)
                with open(os.path.join(logdir, "step_market_daily.log"), "w",
                          encoding="utf-8", errors="replace") as lf:
                    r = subprocess.run([sys.executable, script, "--days", str(span)],
                                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       stdout=lf, stderr=subprocess.STDOUT, timeout=900)
                res[table] = {"dates": len(miss), "days": span, "rc": r.returncode}
            elif table == "board_daily":
                from data_manager import init_board_tables, update_board_daily
                init_board_tables()
                span = max(10, (datetime.now() - datetime.strptime(miss[0], "%Y%m%d")).days + 2)
                rb = update_board_daily(recent_days=span, workers=6)
                res[table] = {"dates": len(miss), "days": span,
                              "updated": rb.get("updated"), "rows": rb.get("rows_added")}
            _log(f"{table}: 补 {res.get(table, {}).get('dates')} 日 → {res.get(table, {})}")
        except Exception as e:
            res[table] = {"error": str(e)[:100]}
            _log(f"{table} 补全失败: {str(e)[:80]}")

    # ③ 周K/月K: 动态窗口重建
    try:
        from data_manager import rebuild_period_kline
        gaps = list((a.get("kline") or {}).get("missing") or []) + list((a.get("kline") or {}).get("partial") or [])
        span = 60
        if gaps:
            span = max(60, (datetime.now() - datetime.strptime(min(gaps), "%Y%m%d")).days + 2)
        rp = rebuild_period_kline(recent_days=min(span, 400))
        res["period_kline"] = {"days": min(span, 400), "weekly": rp.get("weekly"), "monthly": rp.get("monthly")}
    except Exception as e:
        res["period_kline"] = {"error": str(e)[:100]}

    # ④ 组合纸面盘: 逐日回放补齐
    try:
        res["paper_portfolio"] = heal_paper_portfolio(lg=lg)
    except Exception as e:
        res["paper_portfolio"] = {"error": str(e)[:100]}
    return res


def heal_paper_portfolio(tag: str = "", lg=None) -> dict:
    """组合纸面盘: 从 state.last_date 起逐交易日 run_once, 补齐停机期间分仓/净值."""
    from backend.alpha import paper_portfolio as pp
    st = pp._load_state(tag) or {}
    last = st.get("last_date")
    conn = sqlite3.connect(str(KLINE_DB))
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM kline_daily WHERE date > ? ORDER BY date",
            (str(last or "0"),)).fetchall()
    finally:
        conn.close()
    days = [_d8(r[0]) for r in rows]
    n = 0
    for d in days:
        try:
            pp.run_once(as_of=d, verbose=False, tag=tag)
            n += 1
        except Exception:
            break
    if n and lg:
        lg.info("  [补全] 纸面盘[%s]: 回放 %d 个交易日 (至 %s)", tag or "v1", n, days[-1] if days else "-")
    return {"tag": tag or "v1", "replayed": n, "last": days[-1] if days else last}