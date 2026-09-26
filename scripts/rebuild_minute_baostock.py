# -*- coding: utf-8 -*-
"""rebuild_minute_baostock.py — 分钟线全量首拉 (baostock, 2020-01 至今).

数据源调研结论 (2026-09-26):
  免费源分钟历史深度: 新浪~8日 / 腾讯~320根 / 东财反爬且浅 / 通达信公共服务器无数据 /
  雪球需登录; baostock = 唯一稳定获得长历史(2020-01 起)的免费源, 5/15/30/60 分钟(无 1min).

存储:
  data/minute.db kline_min{freq}: 不复权原始价(永久有效, 复权换算留查询层) + volume=股/amount=元.

用法:
  python scripts/rebuild_minute_baostock.py --freq 5 --source mid --limit 20   # 冒烟
  python scripts/rebuild_minute_baostock.py --freq 5 --source all              # 全市场(沪深)
  python scripts/rebuild_minute_baostock.py --freq 5 --codes 600036,000001
  python scripts/rebuild_minute_baostock.py --freq 5 --source all --procs 4
  python scripts/rebuild_minute_baostock.py --freq 5 --source all --check-only # 只看完成度
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

START_DEFAULT = "2020-01-01"
CHUNK = 4           # 每个任务分到的股票数(细粒度, 多进程满载)
INSERT_BATCH = 20000


def bs_symbol(code: str):
    """项目代码 → baostock 代码. 北交所(43/83/87/88/920)不支持 → None."""
    c = str(code).strip()
    if "." in c:
        return c
    if len(c) > 6:
        c = c[-6:]
    if not c.isdigit():
        return None
    if c[0] == "6" or c.startswith("900"):
        return f"sh.{c}"
    if c[0] in "023":
        return f"sz.{c}"
    return None


def load_universe(source: str, only_codes: list | None, limit: int | None) -> list:
    """来源: all=全市场active(沪深) / mid=成交额排名 601~1800(近似项目中盘域)."""
    from data_manager import get_kline_db

    if only_codes:
        codes = [c.strip() for c in only_codes if c.strip()]
    else:
        conn = get_kline_db()
        try:
            if source == "mid":
                last_dates = [r[0] for r in conn.execute(
                    "SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT 20")]
                ph = ",".join("?" * len(last_dates))
                rows = conn.execute(
                    f"SELECT code, AVG(amount) a FROM kline_daily WHERE date IN ({ph}) "
                    "GROUP BY code HAVING COUNT(*)>=10 ORDER BY a DESC LIMIT 600, 1400",
                    last_dates).fetchall()
                codes = [r[0] for r in rows][:1200]
            else:
                rows = conn.execute(
                    "SELECT code FROM stock_list WHERE status='active' ORDER BY code").fetchall()
                codes = [r[0] for r in rows]
        finally:
            conn.close()
    # 过滤北交所 (baostock 不支持)
    codes = [c for c in codes if bs_symbol(c) is not None]
    if limit:
        codes = codes[:limit]
    return codes


def target_date() -> str:
    """全库最新交易日 YYYYMMDD (作为完成判定目标)."""
    from data_manager import get_kline_db
    conn = get_kline_db()
    try:
        r = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()
        return r[0] if r else ""
    finally:
        conn.close()


def load_done(freq: int, codes: list, target: str) -> set:
    """已有数据到 target 的 code 集合 (跳过)."""
    from data_manager import get_minute_db
    done = set()
    conn = get_minute_db()
    try:
        for i in range(0, len(codes), 500):
            chunk = codes[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT code, MAX(dt) m FROM kline_min{freq} WHERE code IN ({ph}) GROUP BY code",
                    chunk):
                if r["m"] and r["m"][:8] >= target:
                    done.add(r["code"])
    finally:
        conn.close()
    return done


_SESSION_READY = False


def _init_worker():
    """进程级初始化: 每个 worker 进程只登录一次 baostock (避免会话风暴)."""
    global _SESSION_READY
    import baostock as bs
    try:
        lg = bs.login()
        _SESSION_READY = (lg.error_code == "0")
    except Exception:
        _SESSION_READY = False


def _reconnect(bs) -> bool:
    """断线重建会话 (logout+login). 返回是否成功. 被限流(10001011)时放缓节奏."""
    global _SESSION_READY
    _SESSION_READY = False
    try:
        bs.logout()
    except Exception:
        pass
    for wait in (3.0, 15.0, 40.0):
        time.sleep(wait)
        try:
            lg = bs.login()
            if lg.error_code == "0":
                _SESSION_READY = True
                return True
        except Exception:
            pass
    return False


def _worker(args) -> dict:
    """一个任务: 拉一批股票. 返回 {ok, fail, rows, skipped, failed:[...]}"""
    global _SESSION_READY
    codes, freq, start_date, end_date = args
    import baostock as bs
    from data_manager import get_minute_db, insert_minute_rows, ensure_minute_tables

    ensure_minute_tables((freq,))
    if not _SESSION_READY:
        _reconnect(bs)
    pid = os.getpid()
    ok = fail = rows = skipped = 0
    failed = []
    conn = get_minute_db()
    year_list = list(range(int(start_date[:4]), int(end_date[:4]) + 1))
    consec_fail = 0
    try:
        for i, code in enumerate(codes):
            sym = bs_symbol(code)
            n_code = 0
            code_fail = False
            for y in year_list:
                ys = start_date if y == year_list[0] else f"{y}-01-01"
                ye = end_date if y == year_list[-1] else f"{y}-12-31"
                year_done = False
                for attempt in range(4):
                    try:
                        if not _SESSION_READY:
                            if not _reconnect(bs):
                                raise RuntimeError("reconnect failed")
                        rs = bs.query_history_k_data_plus(
                            sym, "date,time,open,high,low,close,volume,amount",
                            start_date=ys, end_date=ye,
                            frequency=str(freq), adjustflag="3")
                        if rs is None or rs.error_code != "0":
                            raise RuntimeError(rs.error_msg if rs is not None else "no-resp")
                        batch = []
                        while rs.next():
                            row = rs.get_row_data()
                            try:
                                if not row[2] or float(row[2]) <= 0:
                                    continue
                                batch.append((code, row[1][:12], float(row[2]), float(row[3]),
                                              float(row[4]), float(row[5]),
                                              float(row[6] or 0), float(row[7] or 0)))
                                n_code += 1
                                if len(batch) >= INSERT_BATCH:
                                    rows += insert_minute_rows(conn, freq, batch)
                                    conn.commit()
                                    batch = []
                            except (ValueError, TypeError):
                                continue
                        if batch:
                            rows += insert_minute_rows(conn, freq, batch)
                            conn.commit()
                        year_done = True
                        break
                    except Exception:
                        _SESSION_READY = False
                        time.sleep(1.5 * (attempt + 1))
                if not year_done:
                    code_fail = True
                    break
                time.sleep(0.12)
            if code_fail:
                failed.append(code)
                fail += 1
                consec_fail += 1
                print(f"    [{pid}] FAIL {code} (连败{consec_fail})", flush=True)
                if consec_fail >= 2:
                    print(f"    [{pid}] 连续失败, 疑似被限流, 等待 120s ...", flush=True)
                    time.sleep(120)
                    _reconnect(bs)
            else:
                consec_fail = 0
                if n_code == 0:
                    skipped += 1
                else:
                    ok += 1
            time.sleep(0.05)
            if (i + 1) % 4 == 0 or i + 1 == len(codes):
                print(f"    [{pid}] {i+1}/{len(codes)} ok={ok} fail={fail} rows={rows}", flush=True)
    finally:
        conn.close()
    return {"ok": ok, "fail": fail, "rows": rows, "skipped": skipped, "failed": failed}


def _probe_login(max_min: float) -> bool:
    """登录门: 轮询直到 baostock 可登录(限流解除)才开跑. 返回是否可用."""
    import baostock as bs
    t0 = time.time()
    while True:
        ok = False
        try:
            lg = bs.login()
            ok = lg.error_code == "0"
            if not ok:
                msg = getattr(lg, "error_msg", "")
        except Exception as e:
            msg = str(e)[:40]
        try:
            bs.logout()
        except Exception:
            pass
        if ok:
            print(f"  baostock 可登录 (等待 {int(time.time()-t0)}s)", flush=True)
            return True
        waited = (time.time() - t0) / 60
        print(f"  baostock 暂不可用(限流中), 5min 后重试 (已等 {waited:.0f}min)", flush=True)
        if time.time() - t0 > max_min * 60:
            print("  等待超时, 退出 (稍后重跑即可续拉)", flush=True)
            return False
        time.sleep(300)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", type=int, default=5, choices=[5, 15, 30, 60])
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--source", default="all", choices=["all", "mid"])
    ap.add_argument("--codes", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--wait-max-min", type=float, default=360)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    only = [c for c in args.codes.split(",") if c.strip()] if args.codes else None
    codes = load_universe(args.source, only, args.limit or None)
    tgt = target_date()
    end_date = f"{tgt[:4]}-{tgt[4:6]}-{tgt[6:]}" if tgt else time.strftime("%Y-%m-%d")

    print(f"[分钟线首拉] freq={args.freq}min source={args.source} 股票数={len(codes)} "
          f"start={args.start} end={end_date} procs={args.procs}", flush=True)

    from data_manager import ensure_minute_tables
    ensure_minute_tables((args.freq,))

    done = load_done(args.freq, codes, tgt[:8] if tgt else "")
    todo = [c for c in codes if c not in done]
    print(f"  已完成(到 {tgt})={len(done)}, 待拉={len(todo)}", flush=True)
    if args.check_only or not todo:
        return

    t_start = time.time()
    grand = {"ok": 0, "fail": 0, "rows": 0, "skipped": 0}
    failed_all = []
    rnd = 0
    while todo and rnd < args.rounds:
        rnd += 1
        tasks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
        print(f"[round {rnd}] 待拉 {len(todo)} 只 ({len(tasks)} 任务); 检查 baostock 可用性 ...", flush=True)
        if not _probe_login(args.wait_max_min):
            break
        t0 = time.time()
        agg = {"ok": 0, "fail": 0, "rows": 0, "skipped": 0}
        failed_round = []
        with ProcessPoolExecutor(max_workers=args.procs, initializer=_init_worker) as ex:
            futs = {ex.submit(_worker, (t, args.freq, args.start, end_date)): t for t in tasks}
            for k, fut in enumerate(as_completed(futs), 1):
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"ok": 0, "fail": len(futs[fut]), "rows": 0, "skipped": 0,
                         "failed": futs[fut]}
                    print(f"  TASK EXC: {str(e)[:100]}", flush=True)
                for kk in agg:
                    agg[kk] += r.get(kk, 0)
                failed_round += r.get("failed", [])
                mins = (time.time() - t0) / 60
                print(f"[r{rnd} {k}/{len(tasks)}] {mins:.1f}min 累计: ok={agg['ok']} fail={agg['fail']} "
                      f"rows={agg['rows']:,} 空={agg['skipped']}", flush=True)
        for kk in grand:
            grand[kk] += agg[kk]
        failed_all = failed_round
        todo = failed_round
        if todo:
            print(f"[round {rnd}] 失败 {len(todo)} 只, 10min 后重试 ...", flush=True)
            time.sleep(600)

    os.makedirs(os.path.join(ROOT, "data", "logs"), exist_ok=True)
    fail_file = os.path.join(ROOT, "data", "logs", f"min_rebuild_failed_{args.freq}.txt")
    with open(fail_file, "w", encoding="utf-8") as f:
        f.write("\n".join(failed_all))
    print(f"完成: ok={grand['ok']} fail={grand['fail']} rows={grand['rows']:,} 空={grand['skipped']} "
          f"耗时{(time.time()-t_start)/60:.1f}min; 剩余失败 {len(failed_all)} 只 → {fail_file}", flush=True)


if __name__ == "__main__":
    main()