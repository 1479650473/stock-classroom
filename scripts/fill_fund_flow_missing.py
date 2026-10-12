# -*- coding: utf-8 -*-
"""fill_fund_flow_missing.py — 直连补漏(绕过 akshare_source 包装, 手动验证过的请求方式).

用法: python scripts/fill_fund_flow_missing.py [--interval 1.5]
"""
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "kline.db")
URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
       "MoneyFlow.ssl_qsfx_zjlrqs")


def main():
    import requests
    interval = 1.5
    thin = False
    stale = False
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = float(args[i + 1])
        if a == "--thin":
            thin = True
        if a == "--stale":
            stale = True

    con = sqlite3.connect(DB)
    if thin:
        # 重拉"数据不全"的股票(早期东财源残留 120 行 / 拉取不全)
        codes = [str(r[0]) for r in con.execute(
            "SELECT code FROM fund_flow_daily GROUP BY code HAVING COUNT(*) < 500 ORDER BY code").fetchall()]
    elif stale:
        # 落后于日K最新交易日的股票(含当日行需重拉)
        latest = con.execute("SELECT MAX(date) FROM kline_2026").fetchone()[0] or ""
        codes = [str(r[0]) for r in con.execute(
            "SELECT s.code FROM stock_list s WHERE s.status='active' "
            "AND substr(s.code,1,2) IN ('00','30','60','68') "
            "AND COALESCE((SELECT MAX(date) FROM fund_flow_daily f WHERE f.code=s.code),'') < ? "
            "ORDER BY s.code", (latest,)).fetchall()]
    else:
        codes = [str(r[0]) for r in con.execute(
            "SELECT code FROM stock_list WHERE status='active' AND substr(code,1,2) IN ('00','30','60','68') "
            "AND code NOT IN (SELECT DISTINCT code FROM fund_flow_daily) ORDER BY code").fetchall()]
    con.close()
    print(f"补漏 {len(codes)} 只 @ {interval}s (thin={thin} stale={stale})", flush=True)

    ok = fail = rows_n = 0
    failed = []
    for c in codes:
        sym = ("sh" if c[0] in "69" else "sz") + c
        data = None
        for attempt in range(3):
            try:
                r = requests.get(URL, params={"page": 1, "num": 5000, "sort": "opendate",
                                              "asc": 1, "daima": sym},
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                          "Referer": "https://vip.stock.finance.sina.com.cn/"},
                                 timeout=15)
                data = json.loads(r.text)
                if data:
                    break
            except Exception:
                data = None
            time.sleep(30)   # 限流窗口等待
        if not data:
            failed.append(c)
            fail += 1
            print(f"  FAIL {c}", flush=True)
            continue
        batch = []
        for d in data:
            try:
                batch.append((c, str(d["opendate"]).replace("-", ""),
                              float(d["trade"]), float(d["changeratio"]) * 100,
                              float(d["netamount"]), float(d["ratioamount"]) * 100,
                              float(d.get("r0_net") or 0), float(d.get("r0_ratio") or 0) * 100,
                              0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
            except (ValueError, KeyError, TypeError):
                continue
        con = sqlite3.connect(DB, timeout=60)
        con.executemany(
            "INSERT OR REPLACE INTO fund_flow_daily "
            "(code,date,close,change_pct,main_net,main_ratio,super_net,super_ratio,"
            "large_net,large_ratio,medium_net,medium_ratio,small_net,small_ratio) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        con.commit()
        con.close()
        ok += 1
        rows_n += len(batch)
        print(f"  OK {c}: {len(batch)} 行", flush=True)
        time.sleep(interval)

    print(f"=== 补漏完成: ok={ok} fail={fail} rows={rows_n} ===", flush=True)
    if failed:
        print("仍失败:", ",".join(failed), flush=True)


if __name__ == "__main__":
    main()