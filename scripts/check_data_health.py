# -*- coding: utf-8 -*-
"""check_data_health.py — 数据健康校验报告(格式/覆盖/单位/连续性)."""
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "data", "kline.db")
FUND = os.path.join(ROOT, "data", "fundamental.db")
MACRO = os.path.join(ROOT, "data", "macro.db")


def main():
    con = sqlite3.connect(DB)
    print("=" * 60)
    print("K线库健康检查")
    print("=" * 60)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'kline_%' ORDER BY name")]
    for t in tables:
        try:
            n, codes, mn, mx = con.execute(
                "SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date) FROM %s" % t).fetchone()
            dash = con.execute("SELECT COUNT(*) FROM %s WHERE date LIKE '%%-%%'" % t).fetchone()[0]
            print(f"  {t}: {n:>9,} 行 | {codes:>5} 只 | {mn} ~ {mx} | 连字符格式={dash}")
        except Exception as e:
            print(f"  {t}: ERR {e}")

    print("\n-- 最近 10 个交易日覆盖 --")
    for r in con.execute(
            "SELECT date, COUNT(DISTINCT code) FROM kline_daily WHERE date>='20260825' "
            "GROUP BY date ORDER BY date DESC LIMIT 12"):
        print(f"  {r[0]}: {r[1]} 只")

    print("\n-- 重复检查(同code同日多行) --")
    dup = con.execute("""
        SELECT COUNT(*) FROM (
          SELECT code, date, COUNT(*) c FROM kline_daily GROUP BY code, date HAVING c > 1)""").fetchone()[0]
    print(f"  重复对: {dup}")

    print("\n-- 指数覆盖 --")
    for code in ("sh000001", "sh000300", "sz399001", "sz399006", "sh000016", "sh000688"):
        r = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM kline_daily WHERE code=?", (code,)).fetchone()
        print(f"  {code}: {r[0]} 行 {r[1]} ~ {r[2]}")

    print("\n-- 单位抽样(600036 近3日 volume/amount) --")
    for r in con.execute(
            "SELECT date, close, volume, amount FROM kline_daily WHERE code='600036' "
            "ORDER BY date DESC LIMIT 3"):
        print(f"  {r[0]}: close={r[1]} vol={r[2]:,}股 amt={r[3]:,.0f}元")

    print("\n-- 新股覆盖(40只次新股 2026 数据) --")
    n1 = con.execute("SELECT COUNT(*) FROM kline_2026 WHERE code IN "
                     "(SELECT DISTINCT code FROM kline_2026 WHERE date LIKE '%%-%%')").fetchone()[0]
    print(f"  (连字符已清除, 该查询应=0 或仅数字行) {n1}")
    con.close()

    print("\n" + "=" * 60)
    print("基本面 / 宏观")
    print("=" * 60)
    con = sqlite3.connect(FUND)
    r = con.execute("SELECT MAX(date), COUNT(DISTINCT code) FROM fundamental").fetchone()
    print(f"  fundamental: 最新 {r[0]}, {r[1]} 只")
    for row in con.execute(
            "SELECT substr(md,1,7) ym, COUNT(*) c FROM (SELECT MAX(date) md FROM fundamental "
            "GROUP BY code) GROUP BY ym ORDER BY ym DESC LIMIT 5"):
        print(f"    {row[0]}: {row[1]} 只")
    con.close()
    con = sqlite3.connect(MACRO)
    r = con.execute("SELECT key, MAX(date) FROM series GROUP BY key ORDER BY key").fetchall()
    print(f"  macro series 最新: {dict(r)}")
    con.close()

    print("\n" + "=" * 60)
    print("hs300.json / regime.json")
    print("=" * 60)
    for f in ("hs300.json", "regime.json"):
        p = os.path.join(ROOT, "data", f)
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            if f == "hs300.json":
                print(f"  {f}: {len(d.get('dates', []))} 天 {d['dates'][0] if d.get('dates') else '-'} ~ {d['dates'][-1] if d.get('dates') else '-'}")
            else:
                print(f"  {f}: as_of={d.get('as_of')} regime={d.get('regime_cn')}")
        else:
            print(f"  {f}: 缺失!")


if __name__ == "__main__":
    main()