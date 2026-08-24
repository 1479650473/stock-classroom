# -*- coding: utf-8 -*-
"""全球宏观数据提供者 — 用 akshare 拉取目录里各宏观序列，规整为统一的 (date, value) 升序。

每个取数函数返回 (key, series, ok, msg)：
  series: [(yyyymmdd, float), ...] 升序；失败时为空列表
所有取数均带 try/except + 归一化，单个源挂了不影响其它。
"""
import math

import akshare as ak


def _to_series(df, date_col, val_col):
    """把 akshare 返回的 DataFrame 规整成升序 (date, value) 列表。"""
    out = []
    for _, r in df.iterrows():
        try:
            ds = str(r.get(date_col))[:10].replace("-", "")
            v = float(r.get(val_col))
            if v != v or math.isnan(v):        # NaN 跳过
                continue
            if len(ds) == 8:
                out.append((ds, v))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out


def fetch_equity(symbol):
    """全球股指日线，如 .INX(标普) / .IXIC(纳指)。"""
    df = ak.index_us_stock_sina(symbol=symbol)
    return _to_series(df, "date", "close")


def fetch_hsi():
    """恒生指数日线。"""
    df = ak.stock_hk_index_daily_sina(symbol="HSI")
    return _to_series(df, "date", "close")


def fetch_bonds():
    """中美国债收益率(一次拿全部)。返回 {key: series}。"""
    df = ak.bond_zh_us_rate()
    return {
        "us10y": _to_series(df, "日期", "美国国债收益率10年"),
        "cn10y": _to_series(df, "日期", "中国国债收益率10年"),
        "us10y_2y": _to_series(df, "日期", "美国国债收益率10年-2年"),
    }


def fetch_futures(symbol):
    """国内期货主力连续，如 AU0(沪金)/SC0(原油)/CU0(沪铜)。"""
    df = ak.futures_main_sina(symbol=symbol)
    return _to_series(df, "日期", "收盘价")


def fetch_usdcny():
    """美元/人民币实时水平。源：fx_spot_quote(新浪/境内, 实测可达)。仅当前值，无长历史。"""
    from datetime import datetime
    try:
        df = ak.fx_spot_quote()
        for r in df.itertuples(index=False):
            pair = str(r[0])
            if "USD/CNY" in pair.upper() or "美元" in pair:
                v = float(r[1])
                return [(datetime.now().strftime("%Y%m%d"), round(v, 4))]
        return []
    except Exception:
        return []


def fetch_all() -> dict:
    """拉取目录里所有指标，返回 {key: {"series": [...], "ok": bool, "msg": str}}。"""
    from .catalog import INDICATORS

    results = {}
    for ind in INDICATORS:
        key = ind["key"]
        src = ind["source"]
        try:
            if src == "index_us_stock_sina":
                s = fetch_equity(ind["params"]["symbol"])
            elif src == "stock_hk_index_daily_sina":
                s = fetch_hsi()
            elif src == "bond_zh_us_rate":
                bonds = fetch_bonds()
                s = bonds.get(key, [])
            elif src == "futures_main_sina":
                s = fetch_futures(ind["params"]["symbol"])
            elif src == "fx_spot_quote":
                s = fetch_usdcny()
            elif src == "computed":
                # 由其它序列派生(在 features 里算)；这里先占位
                s = []
            else:
                s = []
            results[key] = {"series": s, "ok": bool(s), "msg": "" if s else "无数据/源不可用"}
        except Exception as e:
            results[key] = {"series": [], "ok": False, "msg": str(e)[:80]}
    return results
