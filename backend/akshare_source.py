"""
akshare_source.py — AKShare 主数据源 + 数据字典
独立模块，被 data_manager.py 和 app.py 引用。
主用 AKShare 本地 Python 库直连，失败时 fallback 到新浪直连。

AKShare 安装位置：C:/Python314/Lib/site-packages/akshare/
完整接口文档：https://akshare.akfamily.xyz/data/stock/stock.html
"""

import logging
from typing import List, Dict, Optional
import pandas as pd
import akshare as ak

log = logging.getLogger("ak_source")


# ══════════════════════════════════════════════════════════════
#  AKShare 接口字典（v1.18.64, 测试于 2026-07-06）
# ══════════════════════════════════════════════════════════════

AKSHARE_API_DICT = {
    "stock_zh_a_spot_em": {
        "func": "stock_zh_a_spot_em",
        "desc": "沪深A股实时行情（东方财富）",
        "params": {},
        "returns": "DataFrame[代码,名称,最新价,涨跌幅,涨跌额,成交量,成交额,振幅,最高,最低,今开,昨收,量比,换手率,市盈率,市净率,总市值,流通市值]",
        "status": "ok",
        "note": "5456只股票，无需参数"
    },
    "stock_zh_index_spot_em": {
        "func": "stock_zh_index_spot_em",
        "desc": "指数实时行情（东方财富）",
        "params": {},
        "returns": "DataFrame[代码,名称,最新价,涨跌幅,涨跌额,成交量,成交额,昨收,今开,最高,最低]",
        "status": "ok",
        "note": "含上证/深证/创业板/科创50等所有指数"
    },
    "stock_board_industry_name_em": {
        "func": "stock_board_industry_name_em",
        "desc": "行业板块列表",
        "params": {},
        "status": "ok",
        "note": "约90个行业板块"
    },
    "stock_board_concept_name_em": {
        "func": "stock_board_concept_name_em",
        "desc": "概念板块列表",
        "params": {},
        "status": "ok",
        "note": "约400+概念板块"
    },
    "fund_etf_spot_em": {
        "func": "fund_etf_spot_em",
        "desc": "ETF实时行情",
        "params": {},
        "status": "ok",
    },
    "stock_hsgt_hist_em": {
        "func": "stock_hsgt_north_net_flow_in_em",
        "desc": "北向资金净流入",
        "params": {"symbol": "北上"},
        "status": "ok",
    },
    "stock_zh_a_hist": {
        "func": "stock_zh_a_hist",
        "desc": "个股历史日K线（前复权）",
        "params": {"symbol": "000001", "period": "daily", "adjust": "qfq"},
        "status": "ok",
        "note": "东方财富源，qfq=前复权"
    },
    "stock_news_em": {
        "func": "stock_news_em",
        "desc": "个股新闻",
        "params": {"symbol": "000001"},
        "status": "ok",
    },
    "stock_zh_a_gdhs": {
        "func": "stock_zh_a_gdhs",
        "desc": "股东人数变化",
        "params": {"symbol": "000001"},
        "status": "ok",
    },
    "stock_dividents_cninfo": {
        "func": "stock_dividents_cninfo",
        "desc": "A股分红记录（巨潮资讯）",
        "params": {},
        "status": "ok",
        "note": "全量历史分红"
    },
    "stock_yjbb_em": {
        "func": "stock_yjbb_em",
        "desc": "业绩预告",
        "params": {"date": "20260630"},
        "status": "ok",
        "note": "date 为报告期截止日"
    },
    # 以下接口当前不可用
    "stock_zt_pool_em": {
        "func": "stock_zt_pool_em",
        "desc": "涨停股池",
        "params": {"date": "20260708"},
        "status": "ok",
        "note": "2026-07-08 修复：去掉代理后OK，参数名 date"
    },
    "stock_lhb_stock_statistic_em": {
        "func": "stock_lhb_stock_statistic_em",
        "desc": "龙虎榜个股统计",
        "params": {"symbol": "近一月"},
        "status": "ok",
        "note": "symbol=近一月/近三月/近六月/近一年"
    },
    "stock_a_high_low_statistics": {
        "func": "stock_a_high_low_statistics",
        "desc": "创新高新低统计",
        "params": {"symbol": "all"},
        "status": "ok",
        "note": "返回 date/close/high20/low20/high60/low60/high120/low120"
    },
    "stock_hot_rank_em": {
        "func": "stock_hot_rank_em",
        "desc": "东财人气榜",
        "params": {},
        "status": "broken",
        "note": "2026-07-08: Connection aborted, 东财反爬"
    },
    "stock_individual_fund_flow_rank": {
        "func": "stock_individual_fund_flow_rank",
        "desc": "个股资金流向排名",
        "params": {"indicator": "今日"},
        "status": "broken",
        "note": "2026-07-08: Connection aborted, 东财反爬"
    },
}


# ══════════════════════════════════════════════════════════════
#  核心数据获取函数（AKShare 主 + 新浪 fallback）
# ══════════════════════════════════════════════════════════════

def ak_fetch_kline(code: str, days: int = 10):
    """获取个股日K线（前复权），返回统一格式的 tuple 列表
    Returns: [(code, date_yyyymmdd, open, high, low, close, volume, amount)]
    """
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    try:
        df = ak.stock_zh_a_daily(symbol=prefix + code, adjust="qfq")
        if df is None or df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        df = df.tail(days)
        rows = []
        for _, bar in df.iterrows():
            amount_val = float(bar.get("amount", 0)) if "amount" in df.columns else round(float(bar["close"]) * float(bar["volume"]), 2)
            hsl = float(bar.get("turnover", 0)) * 100
            rows.append((
                code,
                bar["date"],
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
                int(float(bar["volume"])),
                amount_val,
                hsl,
            ))
        return rows
    except Exception:
        return []


def ak_fetch_index_kline(code: str, days: int = 500):
    """获取指数日K线
    Returns: [(code, date_yyyymmdd, open, high, low, close, volume, amount)]
    """
    try:
        df = ak.stock_zh_index_daily(symbol=code)
        if df is None or df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        df = df.tail(days)
        rows = []
        for _, bar in df.iterrows():
            rows.append((
                code,
                bar["date"],
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
                int(float(bar["volume"])),
                0.0,
            ))
        return rows
    except Exception:
        return []


def ak_get_all_stocks():
    """用新浪原生 API 获取全部 A 股列表"""
    import http.client, json as _json
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    codes = []
    for board in ("sh_a", "sz_a"):
        for page in range(1, 60):
            try:
                conn = http.client.HTTPConnection("vip.stock.finance.sina.com.cn", timeout=15)
                path = f"/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={board}"
                conn.request("GET", path, headers={"User-Agent": UA})
                data = _json.loads(conn.getresponse().read().decode("gbk"))
                conn.close()
                if not data:
                    break
                for item in data:
                    code = item.get("symbol", "").replace("sh", "").replace("sz", "")
                    codes.append({"code": code, "name": item.get("name", ""), "board": board[:2]})
                if len(data) < 100:
                    break
            except Exception:
                break
    return codes


# ══════════════════════════════════════════════════════════════
#  实时行情 / 板块 / 资金 等 API 函数
# ══════════════════════════════════════════════════════════════

def ak_get_spot_all() -> List[Dict]:
    """沪深A股实时行情，失败则 fallback 到新浪"""
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            raise ValueError("empty")
        results = []
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            if not code:
                continue
            results.append({
                "code": code,
                "name": str(row.get("名称", "")),
                "price": float(row.get("最新价", 0) or 0),
                "open": float(row.get("今开", 0) or 0),
                "high": float(row.get("最高", 0) or 0),
                "low": float(row.get("最低", 0) or 0),
                "volume": int(float(row.get("成交量", 0) or 0)),
                "amount": float(row.get("成交额", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "change_val": float(row.get("涨跌额", 0) or 0),
                "turnover": float(row.get("换手率", 0) or 0),
                "pe": float(row.get("市盈率-动态", 0) or 0),
                "pb": float(row.get("市净率", 0) or 0),
                "total_mv": float(row.get("总市值", 0) or 0),
                "circ_mv": float(row.get("流通市值", 0) or 0),
                "source": "akshare",
            })
        log.info("AKShare spot: %d stocks", len(results))
        return results
    except Exception as e:
        log.warning("AKShare spot failed, try Sina fallback: %s", str(e)[:60])
        return _sina_spot_fallback()


def _sina_spot_fallback() -> List[Dict]:
    """新浪直连兜底"""
    from data_manager import ak_get_all_stocks, fetch_realtime_prices
    stocks = ak_get_all_stocks()
    if not stocks:
        return []
    codes = [s["code"] for s in stocks]
    quotes = fetch_realtime_prices(codes)
    for q in quotes:
        q["source"] = "sina"
    return quotes


def ak_get_index_spot() -> List[Dict]:
    """指数实时行情"""
    try:
        df = ak.stock_zh_index_spot_em()
        if df is None or df.empty:
            raise ValueError("empty")
        results = []
        name_map = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指",
                     "sh000300": "沪深300", "sh000016": "上证50", "sh000688": "科创50"}
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            results.append({
                "code": code,
                "name": name_map.get(code, str(row.get("名称", code))),
                "price": float(row.get("最新价", 0) or 0),
                "open": float(row.get("今开", 0) or 0),
                "high": float(row.get("最高", 0) or 0),
                "low": float(row.get("最低", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "change_val": float(row.get("涨跌额", 0) or 0),
                "volume": int(float(row.get("成交量", 0) or 0)),
                "amount": float(row.get("成交额", 0) or 0),
                "source": "akshare",
            })
        return results
    except Exception as e:
        log.warning("AKShare index failed, Sina fallback: %s", str(e)[:60])
        from data_manager import fetch_index_prices
        return fetch_index_prices()


def ak_get_sectors(sector_type: str = "industry") -> List[Dict]:
    """板块行情：industry/概念"""
    try:
        fn = ak.stock_board_industry_name_em if sector_type == "industry" else ak.stock_board_concept_name_em
        df = fn()
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "name": str(row.get("板块名称", row.get("名称", ""))),
                "code": str(row.get("板块代码", row.get("代码", ""))),
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "total_mv": float(row.get("总市值", 0) or 0),
                "turnover": float(row.get("换手率", 0) or 0),
                "up_count": int(float(row.get("上涨家数", 0) or 0)),
                "down_count": int(float(row.get("下跌家数", 0) or 0)),
                "source": "akshare",
            })
        results.sort(key=lambda x: x["change_pct"], reverse=True)
        return results
    except Exception as e:
        log.warning("AKShare %s sectors failed: %s", sector_type, str(e)[:60])
        return []


def ak_get_north_flow(days: int = 30) -> List[Dict]:
    """北向资金净流入"""
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return []
        df = df.tail(days)
        results = []
        for _, row in df.iterrows():
            results.append({
                "date": str(row.get("日期", "")),
                "net_flow": float(row.get("当日净流入", 0) or 0),
                "cum_flow": float(row.get("累计净流入", 0) or 0),
                "source": "akshare",
            })
        return results
    except Exception as e:
        log.warning("AKShare north flow failed: %s", str(e)[:60])
        return []


def ak_get_stock_news(code: str, limit: int = 20) -> List[Dict]:
    """个股新闻"""
    try:
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.head(limit).iterrows():
            results.append({
                "title": str(row.get("新闻标题", "")),
                "time": str(row.get("发布时间", "")),
                "url": str(row.get("新闻链接", "")),
                "source": "akshare",
            })
        return results
    except Exception as e:
        log.warning("AKShare news %s failed: %s", code, str(e)[:60])
        return []


def ak_get_limit_up(date: str = None) -> List[Dict]:
    """涨停股池
    返回: [{code, name, price, change_pct, volume, amount, turnover, total_mv, type}]
    """
    from datetime import datetime as dt
    if date is None:
        date = dt.now().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_em(date=date)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "volume": int(float(row.get("成交额", 0) or 0)),  # AKShare 这列是成交额
                "amount": float(row.get("成交额", 0) or 0),
                "turnover": float(row.get("换手率", 0) or 0),
                "total_mv": float(row.get("总市值", 0) or 0),
                "type": "limit_up",
                "date": date,
                "source": "akshare",
            })
        log.info("AKShare limit_up(%s): %d stocks", date, len(results))
        return results
    except Exception as e:
        log.warning("AKShare limit_up failed: %s", str(e)[:60])
        return []


def ak_get_lhb_stock_statistic(period: str = "近一月") -> List[Dict]:
    """龙虎榜个股统计
    period: 近一月/近三月/近六月/近一年
    返回: [{code, name, last_date, price, change_pct, times, net_buy}]
    """
    try:
        df = ak.stock_lhb_stock_statistic_em(symbol=period)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "last_date": str(row.get("最近上榜日", "")),
                "price": float(row.get("收盘价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "times": int(float(row.get("上榜次数", 0) or 0)),
                "net_buy": float(row.get("龙虎榜净买额", 0) or 0),
                "period": period,
                "source": "akshare",
            })
        log.info("AKShare lhb_statistic(%s): %d stocks", period, len(results))
        return results
    except Exception as e:
        log.warning("AKShare lhb failed: %s", str(e)[:60])
        return []


def ak_get_high_low() -> List[Dict]:
    """创新高/新低统计
    返回: [{date, close, high20, low20, high60, low60, high120, low120}]
    """
    try:
        df = ak.stock_a_high_low_statistics(symbol="all")
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "date": str(row.get("date", "")),
                "close": int(row.get("close", 0) or 0),
                "high20": int(row.get("high20", 0) or 0),
                "low20": int(row.get("low20", 0) or 0),
                "high60": int(row.get("high60", 0) or 0),
                "low60": int(row.get("low60", 0) or 0),
                "high120": int(row.get("high120", 0) or 0),
                "low120": int(row.get("low120", 0) or 0),
                "source": "akshare",
            })
        log.info("AKShare high_low: %d rows", len(results))
        return results
    except Exception as e:
        log.warning("AKShare high_low failed: %s", str(e)[:60])
        return []


def ak_get_etf_list() -> List[Dict]:
    """ETF实时行情"""
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            results.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "price": float(row.get("最新价", 0) or 0),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "volume": int(float(row.get("成交量", 0) or 0)),
                "amount": float(row.get("成交额", 0) or 0),
                "source": "akshare",
            })
        return results
    except Exception as e:
        log.warning("AKShare ETF failed: %s", str(e)[:60])
        return []


# ══════════════════════════════════════════════════════════════
#  数据源诊断
# ══════════════════════════════════════════════════════════════

def _diagnose_limit_up():
    from datetime import datetime
    return ak.stock_zt_pool_em(date=datetime.now().strftime("%Y%m%d"))


def _diagnose_lhb_detail():
    from datetime import datetime, timedelta
    today = datetime.now()
    return ak.stock_lhb_detail_em(
        start_date=(today - timedelta(days=3)).strftime("%Y%m%d"),
        end_date=today.strftime("%Y%m%d"),
    )


def diagnose_akshare() -> dict:
    """诊断 AKShare 各个接口可用性"""
    import time
    results = {}
    tests = {
        "spot": lambda: ak.stock_zh_a_spot_em(),
        "index": lambda: ak.stock_zh_index_spot_em(),
        "industry": lambda: ak.stock_board_industry_name_em(),
        "concept": lambda: ak.stock_board_concept_name_em(),
        "etf": lambda: ak.fund_etf_spot_em(),
        "north_flow": lambda: ak.stock_hsgt_north_net_flow_in_em(symbol="北向资金"),
        "stock_hist": lambda: ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="20260701", end_date="20260705", adjust="qfq"),
        "news": lambda: ak.stock_news_em(symbol="000001"),
        "gdhs": lambda: ak.stock_zh_a_gdhs(symbol="000001"),
        "limit_up": lambda: _diagnose_limit_up(),
        "lhb": lambda: ak.stock_lhb_stock_statistic_em(symbol="近一月"),
        "high_low": lambda: ak.stock_a_high_low_statistics(symbol="all"),
        "fund_flow": lambda: ak.stock_individual_fund_flow_rank(indicator="今日"),
        "lhb_detail": lambda: _diagnose_lhb_detail(),
    }
    for name, fn in tests.items():
        t0 = time.time()
        try:
            df = fn()
            ok = df is not None and (not hasattr(df, "empty") or not df.empty)
            results[name] = {
                "ok": ok,
                "rows": len(df) if hasattr(df, "__len__") else 0,
                "time": round(time.time() - t0, 2),
            }
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:80], "time": round(time.time() - t0, 2)}
    return results


def ak_get_cyq_chip_data(code: str, days: int = 1250, window: int = 250) -> List[Dict]:
    """筹码分布数据
    使用 Sina K 线数据（含换手率）+ JS 引擎计算筹码分布
    通过滑动窗口 (window) 控制单次计算量，支持长周期数据 (days)
    days: 返回的交易日数（5年约1250）
    window: 每次计算使用的历史数据窗口（1年约250）
    Returns: [{code, date, 获利比例, 平均成本, ...}]
    """
    import py_mini_racer, os
    prefix = "sh" if code.startswith(("6", "9", "5")) else "sz"
    try:
        df = ak.stock_zh_a_daily(symbol=prefix + code, adjust="qfq")
        if df is None or df.empty:
            log.warning("cyq %s: no kline data", code)
            return []
        df = df.tail(days + window).reset_index(drop=True)
    except Exception as e:
        log.warning("cyq %s: kline fetch failed: %s", code, str(e)[:60])
        return []
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "cyq_calculator.js")
    try:
        with open(js_path, "r", encoding="utf-8") as f:
            js_code = f.read()
    except Exception:
        return []
    try:
        ctx = py_mini_racer.MiniRacer()
        ctx.eval(js_code)
    except Exception as e:
        log.warning("cyq %s: js init failed: %s", code, str(e)[:60])
        return []
    records = []
    for i, (_, row) in enumerate(df.iterrows()):
        records.append({
            "index": i,
            "date": str(row["date"])[:10],
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": int(row["volume"]),
            "volume_money": float(row["amount"]),
            "hsl": float(row["turnover"]) * 100,
            "zf": 0.0,
            "zdf": 0.0,
            "zde": 0.0,
        })
    total_records = len(records)
    results = []
    for i in range(total_records):
        try:
            wstart = max(0, i - window + 1)
            subset = records[wstart:i+1]
            r = ctx.call("CYQCalculator", len(subset) - 1, subset)
            results.append({
                "code": code,
                "date": records[i]["date"],
                "获利比例": r["benefitPart"],
                "平均成本": float(r["avgCost"]),
                "90成本-低": float(r["percentChips"]["90"]["priceRange"][0]),
                "90成本-高": float(r["percentChips"]["90"]["priceRange"][1]),
                "90集中度": float(r["percentChips"]["90"]["concentration"]),
                "70成本-低": float(r["percentChips"]["70"]["priceRange"][0]),
                "70成本-高": float(r["percentChips"]["70"]["priceRange"][1]),
                "70集中度": float(r["percentChips"]["70"]["concentration"]),
            })
        except Exception:
            continue
    return results[-days:]
