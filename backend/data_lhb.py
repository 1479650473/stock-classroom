# -*- coding: utf-8 -*-
"""
龙虎榜数据导入模块 — 从 akshare 获取东方财富龙虎榜详情并写入数据库
"""
import os, sys
import sqlite3


TABLE_DDL = """
CREATE TABLE IF NOT EXISTS lhb_daily (
    code TEXT NOT NULL, name TEXT, trade_date TEXT NOT NULL,
    close_price REAL, change_rate REAL,
    net_amount REAL, buy_amount REAL, sell_amount REAL,
    deal_amount REAL, market_amount REAL,
    net_ratio REAL, deal_ratio REAL,
    turnover REAL, market_cap REAL,
    reason TEXT,
    d1_chg REAL, d2_chg REAL, d5_chg REAL, d10_chg REAL,
    PRIMARY KEY (code, trade_date)
);
"""

def _fetch_lhb(start_date, end_date):
    import akshare as ak
    import requests as _req
    _orig = _req.get
    _session = _req.Session()
    _session.trust_env = False
    def _noproxy(url, **kw):
        kw.pop('proxies', None)
        return _session.get(url, **kw, proxies={'http': None, 'https': None})
    _req.get = _noproxy
    try:
        df = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
    finally:
        _req.get = _orig
    if df.empty:
        return []
    col_map = {"代码":"code","名称":"name","上榜日":"trade_date","收盘价":"close_price",
        "涨跌幅":"change_rate","龙虎榜净买额":"net_amount","龙虎榜买入额":"buy_amount",
        "龙虎榜卖出额":"sell_amount","龙虎榜成交额":"deal_amount","市场总成交额":"market_amount",
        "净买额占总成交比":"net_ratio","成交额占总成交比":"deal_ratio","换手率":"turnover",
        "流通市值":"market_cap","上榜原因":"reason",
        "上榜后1日":"d1_chg","上榜后2日":"d2_chg","上榜后5日":"d5_chg","上榜后10日":"d10_chg"}
    import pandas as pd
    df2 = df.rename(columns=col_map)
    df2 = df2.drop(columns=[c for c in df2.columns if c not in col_map.values()], errors="ignore")
    df2 = df2.where(pd.notna(df2), None)
    return df2.to_dict(orient="records")

def update_lhb_daily(db_path, days_back=7):
    from datetime import datetime, timedelta
    today = datetime.now()
    end = today.strftime("%Y%m%d")
    start = (today - timedelta(days=days_back)).strftime("%Y%m%d")

    conn = sqlite3.connect(db_path)
    conn.execute(TABLE_DDL)
    try:
        records = _fetch_lhb(start, end)
    except Exception as e:
        conn.close()
        return {"status":"error","error":str(e)}

    if not records:
        conn.close()
        return {"status":"ok","inserted":0,"message":"empty range"}

    cols = ["code","name","trade_date","close_price","change_rate",
            "net_amount","buy_amount","sell_amount","deal_amount","market_amount",
            "net_ratio","deal_ratio","turnover","market_cap","reason",
            "d1_chg","d2_chg","d5_chg","d10_chg"]
    phs = ",".join("?" for _ in cols)
    sql = "INSERT OR REPLACE INTO lhb_daily (%s) VALUES (%s)" % (",".join(cols), phs)
    rows = [[r.get(c) for c in cols] for r in records]
    conn.executemany(sql, rows)
    conn.commit()
    n = len(rows)
    conn.close()
    return {"status":"ok","inserted":n,"total":len(records),"range":(start,end)}