# -*- coding: utf-8 -*-
"""宏观快照 — 一键抓取全球宏观 → 合成 regime → 落库 → 打印仪表。

运行:  python -m backend.macro.snapshot        (项目根下)
结果落库 data/macro.db (series + regime 两表)，并打印当前宏观状态。
"""
import os, sqlite3, json
from datetime import datetime

from .catalog import INDICATORS, CATEGORY_CN, by_key
from .provider import fetch_all
from .features import compute_regime

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_macro_db_path():
    return os.path.join(_ROOT, "data", "macro.db")


def store(db_path, series_map, feats, snap_date):
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS series(key TEXT, date TEXT, value REAL, PRIMARY KEY(key,date))")
    con.execute("CREATE TABLE IF NOT EXISTS regime(date TEXT, key TEXT, feat TEXT, value TEXT, PRIMARY KEY(date,key))")
    for key, series in series_map.items():
        for d, v in series:
            con.execute("INSERT OR REPLACE INTO series(key,date,value) VALUES(?,?,?)", (key, d, v))
    for key, feat in feats.items():
        if key == "_category":
            continue
        con.execute("INSERT OR REPLACE INTO regime(date,key,feat,value) VALUES(?,?,?,?)",
                    (snap_date, key, "features", json.dumps(feat, ensure_ascii=False, default=str)))
    cat = feats.get("_category", {})
    con.execute("INSERT OR REPLACE INTO regime(date,key,feat,value) VALUES(?,?,?,?)",
                (snap_date, "__overall__", "label", cat.get("overall", "")))
    con.commit()
    con.close()


def _fmt(v, nd=2):
    if v is None:
        return "--"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return str(v)


def _pct(v):
    return "--" if v is None else f"{v * 100:+.2f}%"


def run(verbose=True):
    raw = fetch_all()
    series_map = {k: v["series"] for k, v in raw.items()}
    feats = compute_regime(series_map)

    snap_date = max((f["latest_date"] for f in feats.values()
                     if isinstance(f, dict) and f.get("latest_date")),
                    default=datetime.now().strftime("%Y%m%d"))
    db = get_macro_db_path()
    store(db, series_map, feats, snap_date)

    if not verbose:
        return feats, raw, db

    cat = feats.get("_category", {})
    print("=" * 68)
    print(f"🌐 全球宏观快照  {snap_date}   (落库: {db})")
    print(f"   {cat.get('overall', '')}")
    print("=" * 68)
    for ind in INDICATORS:
        key = ind["key"]
        info = raw.get(key, {})
        f = feats.get(key, {})
        has_value = f.get("latest") is not None
        status = "OK " if has_value else "FAIL"
        latest = _fmt(f.get("latest"))
        unit = ind.get("unit", "")
        line = f"  [{status}] {ind['name']:<18} 最新={latest}{unit}  20日={_pct(f.get('chg20d'))}  60日={_pct(f.get('chg60d'))}"
        if f.get("latest_date"):
            line += f"  (止于{f['latest_date']})"
        if not has_value:
            line += f"   ({info.get('msg','')})"
        print(line)
    print("")
    # 类别汇总
    for ckey, cname in CATEGORY_CN.items():
        c = cat.get(ckey, {})
        print(f"  {cname}: {c.get('label','')}")
    print("=" * 68)
    return feats, raw, db


if __name__ == "__main__":
    run()
