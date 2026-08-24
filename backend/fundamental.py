# -*- coding: utf-8 -*-
"""基本面数据层 — akshare 东财每日估值 → 价值/质量因子(EP/BP/ROE)。

选用 stock_value_em(东财, 各股每日 PE(TTM)/市净率/PB):
- 覆盖全市场(比 Sina 季报源稀疏可靠), 每日一条(数据日期=交易日, 到当日)。
- **点时间无前视**: 某交易日的 PE(TTM)/PB 即该日成交对应的估值(EastMoney 按当时已披露财报算 TTM),
  据此 EP=1/PE_TTM, BP=1/PB, ROE=PB/PE_TTM(隐含, 因 ROE=EPS/BVPS=(P/PE)/(P/PB))。
- 直接按日期对齐 kline 帧, 无需披露滞后。

数据: data/fundamental.db 表 fundamental(code, date, pe_ttm, pb, updated_at)。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "fundamental.db"


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""CREATE TABLE IF NOT EXISTS fundamental (
        code TEXT, date TEXT, pe_ttm REAL, pb REAL, updated_at TEXT,
        PRIMARY KEY (code, date))""")
    return con


def init_db():
    con = _db(); con.commit(); con.close()


def parse_raw(df: pd.DataFrame) -> List[dict]:
    """东财估值行 → [{date, pe_ttm, pb}]。剔除无效(pe<=0)。"""
    out = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        d = row.get("数据日期")
        date = str(d)[:10] if d is not None else ""
        if len(date) < 10:
            continue
        def _f(col):
            try:
                v = float(row.get(col))
                return v if v == v else None
            except (TypeError, ValueError):
                return None
        pe = _f("PE(TTM)")
        pb = _f("市净率")
        if pe is not None and pb is not None and pe > 0 and pb > 0:
            out.append({"date": date, "pe_ttm": round(pe, 4), "pb": round(pb, 4)})
    return out


def store(code: str, rows: List[dict]):
    con = _db()
    now = datetime.now().isoformat()
    for r in rows:
        con.execute(
            "INSERT OR REPLACE INTO fundamental (code, date, pe_ttm, pb, updated_at) VALUES (?,?,?,?,?)",
            (code, r["date"], r["pe_ttm"], r["pb"], now))
    con.commit(); con.close()


def load_vals(code: str) -> List[dict]:
    con = _db(); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT date, pe_ttm, pb FROM fundamental WHERE code=? ORDER BY date", (code,)).fetchall()]
    con.close()
    return rows


def has_vals(code: str) -> bool:
    con = _db()
    n = con.execute("SELECT COUNT(*) FROM fundamental WHERE code=?", (code,)).fetchone()[0]
    con.close()
    return n > 0


def fetch_fundamental(code: str) -> List[dict]:
    """akshare 东财每日估值拉取并缓存。失败返回 []，加 retry+退避。"""
    import akshare as ak
    import time
    for attempt in range(3):
        try:
            df = ak.stock_value_em(symbol=code)
            rows = parse_raw(df)
            if rows:
                store(code, rows)
                return rows
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return []


def ensure_fundamental(code: str) -> bool:
    if has_vals(code):
        return True
    return bool(fetch_fundamental(code))


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def attach_fundamentals(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """给每个 {code: DataFrame(daily)} 帧按日期对齐附加 EP/BP/ROE 列(点时间无前视)。

    EP=1/PE_TTM, BP=1/PB, ROE=PB/PE_TTM。缺估值(新股/停牌)的行 → NaN(研究引擎忽略)。
    """
    prepared = {}
    for code, frame in frames.items():
        frame = frame.copy()
        frame["EP"] = pd.NA
        frame["BP"] = pd.NA
        frame["ROE"] = pd.NA
        vals = load_vals(code)
        if not vals or frame.empty:
            prepared[code] = frame
            continue
        vmap = {}
        for v in vals:
            if v["pe_ttm"] and v["pe_ttm"] > 0 and v["pb"] and v["pb"] > 0:
                vmap[v["date"]] = v
        ep_s, bp_s, roe_s = [], [], []
        for dt in frame.index:
            d = str(pd.Timestamp(dt).date())
            v = vmap.get(d)
            if v is None:
                ep_s.append(pd.NA); bp_s.append(pd.NA); roe_s.append(pd.NA)
                continue
            pe, pb = v["pe_ttm"], v["pb"]
            close = _f(frame.at[dt, "close"]) if "close" in frame.columns else None
            if close and close > 0:
                ep_s.append(round(1.0 / pe, 6) if pe else pd.NA)
                bp_s.append(round(1.0 / pb, 6) if pb else pd.NA)
                roe_s.append(round(pb / pe, 4))
            else:
                ep_s.append(pd.NA); bp_s.append(pd.NA); roe_s.append(pd.NA)
        frame["EP"] = ep_s
        frame["BP"] = bp_s
        frame["ROE"] = roe_s
        prepared[code] = frame
    return prepared
