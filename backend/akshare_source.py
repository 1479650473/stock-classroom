"""
akshare_source.py — AKShare 主数据源 + 数据字典
独立模块，被 data_manager.py 和 app.py 引用。
主用 AKShare 本地 Python 库直连，失败时 fallback 到新浪直连。

AKShare 安装位置：C:/Python314/Lib/site-packages/akshare/
完整接口文档：https://akshare.akfamily.xyz/data/stock/stock.html
"""

import logging
import time
from typing import List, Dict, Optional
import pandas as pd
import akshare as ak

from codec import normalize_a_code, ak_symbol
from resilience import (
    retry_with_backoff, akshare_wait, sina_wait, get_request_headers, get_random_user_agent,
)

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

@retry_with_backoff(max_attempts=3, retry_on_empty=True, on_retry=lambda a, e: log.warning("ak_fetch_kline 第%s次重试: %s", a, str(e)[:60]))
def ak_fetch_kline(code: str, days: int = 10, timeout: float = 20.0):
    """获取个股日K线（前复权）。code 经 normalize_a_code 规范化成裸 6 位存储码。

    来源韧性(参考 daily_stock_analysis): 主用新浪 stock_zh_a_daily, 失败/超时回退
    腾讯 stock_zh_a_hist_tx/东财 stock_zh_a_hist, 每次调用绑定硬超时, 防挂起返回 []。
    Returns: [(stored_code, date_yyyymmdd, open, high, low, close, volume, amount, hsl)]
    """
    stored = normalize_a_code(code, "stock")       # 规范存储码(裸6位)
    symbol = ak_symbol(code, "stock")              # akshare 用 sh/sz 前缀
    rows = _fetch_kline_with_fallback(symbol, days=days, timeout=timeout)
    return _normalize_kline_rows(stored, rows, days=days)


_TIMEOUT_EXEC = None


def _timeout_exec():
    """共享的单一超时执行器 —— 避免每次调用都新建 ThreadPoolExecutor(5200×池会线程爆炸崩 native)."""
    global _TIMEOUT_EXEC
    if _TIMEOUT_EXEC is None or _TIMEOUT_EXEC._shutdown:
        from concurrent.futures import ThreadPoolExecutor
        _TIMEOUT_EXEC = ThreadPoolExecutor(max_workers=24)
    return _TIMEOUT_EXEC


def _run_with_timeout(fn, timeout: float):
    """把 fn() 放进共享线程池跑, 超时终止(akshare 库内挂起无法真正 kill, 靠超时返回 None)。"""
    from concurrent.futures import TimeoutError as _TE
    ex = _timeout_exec()
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except _TE:
        return None


def _fetch_kline_with_fallback(symbol: str, days: int, timeout: float):
    """依次尝试 新浪/腾讯/东财 三个 akshare 源, 每个挂在独立线程 + 硬超时。

    源健康缓存: 某源连续异常 3 次 → 进程内暂停 300s(跳过), 避免单源被反爬/故障时
    每只股票都 3 源空转(5000 只 × 3 源 × 重试 3 次 会拖到 1 小时+)。成功一次即恢复。
    """
    import akshare as ak

    def _sina():
        akshare_wait()
        df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        return df

    def _tx():
        akshare_wait()
        # 腾讯需要日期窗口(取近 enough 天)
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=days * 2 + 30)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start, end_date=end, adjust="qfq")
        return df

    def _em():
        akshare_wait()
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=days * 2 + 30)).strftime("%Y%m%d")
        end = datetime.now().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=symbol.replace("sh", "").replace("sz", ""),
                                period="daily", start_date=start, end_date=end, adjust="qfq")
        return df

    df = None
    for name, fn in (("sina", _sina), ("tx", _tx), ("em", _em)):
        if _src_bad(name):
            continue
        try:
            df = _run_with_timeout(fn, timeout)
        except Exception as e:
            log.warning("ak_fetch_kline[%s] %s 异常: %s", name, symbol, str(e)[:50])
            _src_note_fail(name)
            df = None
        if df is not None and not df.empty:
            _src_note_ok(name)
            return df
        if df is not None:
            _src_note_ok(name)   # 源本身正常(空=该股无数据), 不记故障
    return None


# ══════════════════════════════════════════════════════════════
#  数据源健康状态(进程内): 连续异常 → 暂停, 防单源故障拖垮全市场更新
# ══════════════════════════════════════════════════════════════
_SRC_HEALTH: dict = {}
_SRC_PAUSE_SECS = 300


def _src_bad(name: str) -> bool:
    st = _SRC_HEALTH.get(name)
    return bool(st and time.time() < st.get("until", 0))


def _src_note_fail(name: str) -> None:
    st = _SRC_HEALTH.setdefault(name, {"fail": 0, "until": 0})
    st["fail"] += 1
    if st["fail"] >= 3:
        st["until"] = time.time() + _SRC_PAUSE_SECS
        st["fail"] = 0
        log.warning("数据源 %s 连续异常 3 次 → 暂停 %ss", name, _SRC_PAUSE_SECS)


def _src_note_ok(name: str) -> None:
    _SRC_HEALTH.setdefault(name, {"fail": 0, "until": 0})["fail"] = 0


def _normalize_kline_rows(stored: str, df, days: int = 10):
    """把任意源的 DataFrame 归一化成 (stored,date,open,high,low,close,volume,amount,hsl)。"""
    if df is None or df.empty:
        return []
    import pandas as pd
    d = df.copy()
    # 统一日期列
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y%m%d")
    elif "日期" in d.columns:
        d["date"] = pd.to_datetime(d["日期"]).dt.strftime("%Y%m%d")
    else:
        return []
    # 列名统一(东财/新浪/腾讯不同): open/high/low/close/volume/amount
    colmap = {"开盘": "open", "open": "open", "最高": "high", "high": "high",
              "最低": "low", "low": "low", "收盘": "close", "close": "close",
              "成交量": "volume", "volume": "volume", "成交额": "amount", "amount": "amount",
              "换手率": "turnover", "turnover": "turnover"}
    d = d.rename(columns={k: v for k, v in colmap.items() if k in d.columns})
    rows = []
    for _, bar in d.tail(days).iterrows():
        try:
            close = float(bar["close"])
            vol = float(bar.get("volume", 0) or 0)
            amt = float(bar.get("amount", 0) or 0)
            if not amt and vol:
                amt = close * vol
            turn = float(bar.get("turnover", 0) or 0)
            if turn and turn <= 1.0:   # 换手率可能为小数, 放大到 %
                turn = turn * 100
            rows.append((stored, str(bar["date"]), float(bar["open"]), float(bar["high"]),
                         float(bar["low"]), close, int(vol), amt, turn))
        except Exception:
            continue
    return rows


def _normalize_index_code(code: str) -> str:
    """指数码规范化为 sh/sz 前缀(委托 codec)；保留旧名向后兼容。"""
    return normalize_a_code(code, "index")


@retry_with_backoff(max_attempts=3, retry_on_empty=True, on_retry=lambda a, e: log.warning("ak_fetch_index_kline 第%s次重试: %s", a, str(e)[:60]))
def ak_fetch_index_kline(code: str, days: int = 500):
    """获取指数日K线。code 强制带 sh/sz 前缀入库，避免与同码股票撞库(详见 codec)。
    Returns: [(stored_code, date_yyyymmdd, open, high, low, close, volume, amount)]
    """
    stored = normalize_a_code(code, "index")       # 规范存储码(sh000001/sz399001)
    akshare_wait()
    try:
        df = ak.stock_zh_index_daily(symbol=stored)
        if df is None or df.empty:
            return []
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        df = df.tail(days)
        rows = []
        for _, bar in df.iterrows():
            rows.append((
                stored,
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


@retry_with_backoff(max_attempts=2, retry_on_empty=True, on_retry=lambda a, e: log.warning("ak_get_all_stocks 第%s次重试: %s", a, str(e)[:60]))
def ak_get_all_stocks():
    """用新浪原生 API 获取全部 A 股列表(带限流+UA轮换+每页容错)"""
    import http.client, json as _json
    sina_wait()
    codes = []
    for board in ("sh_a", "sz_a"):
        for page in range(1, 60):
            try:
                conn = http.client.HTTPConnection("vip.stock.finance.sina.com.cn", timeout=15)
                path = f"/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={board}"
                conn.request("GET", path, headers=get_request_headers(referer="https://vip.stock.finance.sina.com.cn/"))
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
    akshare_wait()
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
    akshare_wait()
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


def ak_fetch_fund_flow(code: str, timeout: float = 25.0) -> List[tuple]:
    """个股日频资金流全历史(东财 daykline, 起点约2010年).

    直接请求 push2his.eastmoney.com 资金流 daykline 接口(lmt=0 全历史), 自带 UA/Referer/
    重试+退避/硬超时, 并接入坏源健康缓存(连续异常暂停300s — 东财反爬时快速降级).
    返回: [(code, date_yyyymmdd, close, change_pct,
            main_net, main_ratio, super_net, super_ratio, large_net, large_ratio,
            medium_net, medium_ratio, small_net, small_ratio)]
    """
    import requests as _rq
    secid_market = "1" if str(code).startswith(("6", "5", "9")) else "0"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept": "*/*",
    }
    params = {
        "lmt": "0", "klt": "101", "secid": f"{secid_market}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }

    def _fetch():
        return _rq.get(url, params=params, headers=headers, timeout=timeout)

    resp = None
    for attempt in range(3):
        if _src_bad("em"):
            return []
        try:
            resp = _run_with_timeout(_fetch, timeout + 5)
        except Exception as e:
            log.warning("ak_fetch_fund_flow %s 异常: %s", code, str(e)[:50])
            _src_note_fail("em")
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp is not None and resp.status_code == 200:
            _src_note_ok("em")
            break
        _src_note_fail("em")
        time.sleep(1.5 * (attempt + 1))
    if resp is None or resp.status_code != 200:
        return []

    rows = []
    try:
        data = resp.json().get("data") or {}
        klines = data.get("klines") or []
        for item in klines:
            p = item.split(",")
            # 0日期 1主力净 2小单净 3中单净 4大单净 5超大单净 6主力占比 7小单占比 8中单占比 9大单占比 10超大单占比 11收盘 12涨跌幅
            try:
                rows.append((code, p[0].replace("-", ""),
                             float(p[11]), float(p[12]),
                             float(p[1]), float(p[6]),
                             float(p[5]), float(p[10]),
                             float(p[4]), float(p[9]),
                             float(p[3]), float(p[8]),
                             float(p[2]), float(p[7])))
            except (ValueError, IndexError):
                continue
    except Exception as e:
        log.warning("ak_fetch_fund_flow %s 解析失败: %s", code, str(e)[:60])
        return []
    return rows


def ak_get_etf_list() -> List[Dict]:
    """ETF实时行情"""
    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return []

        def _f(v, default=0.0):
            try:
                x = float(v)
                return x if x == x else default
            except (TypeError, ValueError):
                return default

        results = []
        for _, row in df.iterrows():
            results.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "price": _f(row.get("最新价")),
                "change_pct": _f(row.get("涨跌幅")),
                "volume": int(_f(row.get("成交量"))),
                "amount": _f(row.get("成交额")),
                "type": str(row.get("类型", "") or ""),
                "source": "akshare",
            })
        return results
    except Exception as e:
        log.warning("AKShare ETF failed: %s", str(e)[:60])
        return []


def ak_fetch_etf_kline(code: str, days: int = 4000, timeout: float = 25.0) -> List[tuple]:
    """ETF 日K线全历史(前复权)。code 为裸 6 位 ETF 代码(5/1 开头)。

    主源新浪 fund_etf_hist_sina(volume=股/amount=元, 与股票库同口径, 全历史);
    回退东财 fund_etf_hist_em(volume=手 → ×100 转股)。复用坏源健康缓存(连续异常暂停)。
    Returns: [(code, date_yyyymmdd, open, high, low, close, volume, amount, turnover)]
    """
    from codec import ak_symbol
    # ETF 专用前缀: 沪市 ETF/LOF 以 5 开头(51/56/58/50/52/53), 深市 1 开头(15/16/18)
    symbol = ("sh" if str(code).startswith("5") else "sz") + str(code)
    stored = code

    def _sina():
        akshare_wait()
        return ak.fund_etf_hist_sina(symbol=symbol)

    def _em():
        akshare_wait()
        return ak.fund_etf_hist_em(symbol=code, period="daily",
                                   start_date="20040101", end_date="20270101", adjust="qfq")

    df = None
    for name, fn in (("sina", _sina), ("em", _em)):
        if _src_bad(name):
            continue
        try:
            df = _run_with_timeout(fn, timeout)
        except Exception as e:
            log.warning("ak_fetch_etf_kline[%s] %s 异常: %s", name, symbol, str(e)[:50])
            _src_note_fail(name)
            df = None
        if df is not None and not df.empty:
            _src_note_ok(name)
            break
        if df is not None:
            _src_note_ok(name)
    if df is None or df.empty:
        return []

    d = df.copy()
    # 列统一 → date/open/high/low/close/volume/amount/turnover
    colmap = {"日期": "date", "date": "date", "开盘": "open", "open": "open",
              "最高": "high", "high": "high", "最低": "low", "low": "low",
              "收盘": "close", "close": "close", "成交量": "volume", "volume": "volume",
              "成交额": "amount", "amount": "amount", "换手率": "turnover", "turnover": "turnover"}
    d = d.rename(columns={k: v for k, v in colmap.items() if k in d.columns})
    if "date" not in d.columns:
        return []
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y%m%d")
    rows = []
    for _, bar in d.tail(days).iterrows():
        try:
            vol = float(bar.get("volume", 0) or 0)
            amt = float(bar.get("amount", 0) or 0)
            if name == "em" and vol:
                vol = vol * 100          # 东财成交量单位=手 → 股
            if not amt and vol:
                amt = float(bar["close"]) * vol
            turn = float(bar.get("turnover", 0) or 0)
            rows.append((stored, str(bar["date"]), float(bar["open"]), float(bar["high"]),
                         float(bar["low"]), float(bar["close"]), int(vol), amt, turn))
        except Exception:
            continue
    return rows


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
    js_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cyq_calculator.js")
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
