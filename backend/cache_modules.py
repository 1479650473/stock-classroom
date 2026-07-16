"""
cache_modules.py — 新增数据接入模块（资金流向、涨停板等）
被 data_manager.py 引用，可按阶段独立扩展
"""

import logging
from datetime import datetime
log = logging.getLogger("cache_mod")


def cache_fund_flow_from_akshare():
    """Cache individual stock fund flow data (top 100)"""
    import akshare as ak
    from data_manager import _get_cache_db
    conn = _get_cache_db()
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        if df is None or df.empty:
            log.warning("Fund flow empty")
            return 0
        col_map = {
            "股票代码": "code", "股票名称": "name",
            "最新价": "price", "涨跌幅": "change_pct",
            "主力净流入-净额": "main_net",
            "超大单净流入-净额": "super_large_net",
            "大单净流入-净额": "large_net",
            "中单净流入-净额": "medium_net",
            "小单净流入-净额": "small_net",
        }
        df = df.rename(columns=col_map)
        for _, row in df.iterrows():
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO fund_flow VALUES (?,?,?,?,?,?,?)",
                    (str(row.get("code", "")), today,
                     float(row.get("main_net", 0) or 0),
                     float(row.get("super_large_net", 0) or 0),
                     float(row.get("large_net", 0) or 0),
                     float(row.get("medium_net", 0) or 0),
                     float(row.get("small_net", 0) or 0)),
                )
                count += 1
            except (ValueError, TypeError):
                continue
        conn.commit()
        log.info("cached %d fund flow rows", count)
    except Exception as e:
        log.warning("cache fund flow failed: %s", str(e)[:80])
    conn.close()
    return count


def cache_limit_up_from_akshare():
    """Cache limit-up data for today"""
    import akshare as ak
    from data_manager import _get_cache_db
    conn = _get_cache_db()
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        df = ak.stock_zt_pool_em(date=today)
        if df is None or df.empty:
            log.warning("Limit-up empty")
            return 0
        col_map = {
            "代码": "code", "名称": "name",
            "最新价": "price", "涨跌幅": "change_pct",
            "成交量": "volume", "成交额": "amount",
            "换手率": "turnover",
        }
        df = df.rename(columns=col_map)
        for _, row in df.iterrows():
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO limit_up VALUES (?,?,?,?,?,?,?,?,?)",
                    (today, str(row.get("code", "")), str(row.get("name", "")),
                     float(row.get("price", 0) or 0),
                     float(row.get("change_pct", 0) or 0),
                     int(float(row.get("volume", 0) or 0)),
                     float(row.get("amount", 0) or 0),
                     float(row.get("turnover", 0) or 0), "up"),
                )
                count += 1
            except (ValueError, TypeError):
                continue
        conn.commit()
        log.info("cached %d limit-up rows", count)
    except Exception as e:
        log.warning("cache limit-up failed: %s", str(e)[:80])
    conn.close()
    return count


# CLI support
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fund-flow":
        print(f"fund flow: {cache_fund_flow_from_akshare()} rows")
    elif cmd == "limit-up":
        print(f"limit-up: {cache_limit_up_from_akshare()} rows")
    else:
        print("Usage: python cache_modules.py [fund-flow|limit-up]")

