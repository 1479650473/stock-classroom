# -*- coding: utf-8 -*-
"""策略数据加载 & 数据质量护栏。

集中从 data/kline.db 读单标的符号历史 K 线，并返回数据质量警告，
避免策略在"历史被覆盖/代码撞码/疑似指数"等脏数据上静默回测出假结果。
"""
import os, sqlite3

from ..api.paths import KLINE_DB

DB_PATH = KLINE_DB

# 一根股票历史少于该值，基本可断定数据不完整(撞码覆盖/新上市/缺数)
MIN_MEANINGFUL_BARS = 120


def _connect():
    return sqlite3.connect(DB_PATH)


def get_kline_db_path():
    return DB_PATH


def stock_name(code: str) -> str:
    try:
        con = _connect()
        r = con.execute("SELECT name FROM stock_list WHERE code=?", (code,)).fetchone()
        con.close()
        return r[0] if r else code
    except Exception:
        return code


def load_klines(code: str, limit: int = 1200, warn_short: bool = True):
    """读取单标的最近 `limit` 根日 K(升序)。

    Returns:
        (klines, warnings)
        klines: [{date,open,high,low,close,volume,amount}, ...]
        warnings: list[str] 数据质量提示(空表示数据健康)
    """
    con = _connect()
    rows = con.execute(
        "SELECT date,open,high,low,close,volume,amount FROM kline_daily "
        "WHERE code=? ORDER BY date DESC LIMIT ?", (code, limit)).fetchall()
    meta = con.execute("SELECT name,board FROM stock_list WHERE code=?", (code,)).fetchone()
    con.close()
    rows = list(reversed(rows))

    klines = [{"date": r[0], "open": r[1], "high": r[2], "low": r[3],
               "close": r[4], "volume": r[5], "amount": r[6]} for r in rows]

    warns = []
    name = meta[0] if meta else code
    board = meta[1] if meta else ""
    if not meta:
        warns.append(f"代码 {code} 不在股票列表(stock_list)，可能是指数/非股票代码")
    # 指数通常 amount=0(成交量以指数口径)；股票 amount>0。给出提示但不强拦。
    if klines:
        idx_like = sum(1 for k in klines if k["amount"] == 0)
        if idx_like > len(klines) * 0.9:
            warns.append(f"该代码 {idx_like}/{len(klines)} 根K线 amount=0，疑似指数数据(需确认是否想回测指数)")
    if warn_short and klines and len(klines) < MIN_MEANINGFUL_BARS:
        warns.append(f"历史仅 {len(klines)} 根K线(<{MIN_MEANINGFUL_BARS})，数据可能不完整"
                     f"(撞码覆盖/新上市/缺数)，回测结论不可靠")
    return klines, warns
