# -*- coding: utf-8 -*-
"""基金套利数据源：新浪（LOF 名单/快照）、腾讯（场内日线）、东财（净值/费率/申购门槛）。

环境说明：东财行情服务器（push2 系）在本机不可达 → 不用 fund_lof_spot_em / fund_lof_hist_em 一类接口；
改用 新浪 + 腾讯 + 东财 fund.eastmoney.com（净值/费率/门槛）这套组合。
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from typing import List, Optional

import akshare as ak

try:
    from ..resilience import akshare_wait as _akshare_wait
except Exception:  # 独立脚本运行
    def _akshare_wait():  # type: ignore
        time.sleep(0.2)


def akshare_wait():
    try:
        return _akshare_wait()
    except Exception:
        return 0.0


def _retry(fn, tries: int = 3, base_delay: float = 0.8):
    """简单重试（项目 resilience.retry_with_backoff 是装饰器工厂，这里要函数式）。"""
    last = None
    for i in range(max(1, tries)):
        try:
            r = fn()
            if r is None:
                raise RuntimeError("empty result")
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(base_delay * (i + 1))
    raise last  # type: ignore[misc]


def _f(v):
    """安全转 float。"""
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "").replace("%", "")
        if s in ("", "-", "nan", "None", "NaT"):
            return None
        return float(s)
    except Exception:
        return None


# ---------------- 新浪：LOF 名单 + 实时快照 ----------------

def fetch_lof_list() -> List[dict]:
    """新浪 LOF 基金列表（含实时快照）。代码形如 sz161725 / sh501050。"""
    df = _retry(lambda: ak.fund_etf_category_sina(symbol="LOF基金"), tries=3)
    rows = []
    for _, r in df.iterrows():
        raw = str(r.get("代码", "")).strip()
        m = re.match(r"^(sh|sz)(\d{6})$", raw, re.I)
        if not m:
            continue
        exch, code = m.group(1).lower(), m.group(2)
        rows.append({
            "code": code, "exchange": exch, "name": str(r.get("名称", "")).strip(),
            "last": _f(r.get("最新价")), "prev_close": _f(r.get("昨收")),
            "amount": _f(r.get("成交额")), "volume": _f(r.get("成交量")),
        })
    return rows


# ---------------- 腾讯：场内日线（不复权） ----------------

def _tx_symbol(code: str, exchange: Optional[str] = None) -> str:
    if exchange:
        return f"{exchange}{code}"
    # 15/16/18 段在深市；501/502/506 及其余在沪市
    return ("sz" if code[:2] in ("15", "16", "18") else "sh") + code


def fetch_daily_tx(code: str, start: str, end: Optional[str] = None, exchange: Optional[str] = None) -> List[dict]:
    """腾讯日线。start/end: YYYY-MM-DD。返回未复权日线。

    注：腾讯该接口 amount 字段为**成交量(手)**，这里换算成 份 与 元(按当日收盘估) 统一口径。
    """
    end = end or _dt.date.today().isoformat()
    sym = _tx_symbol(code, exchange)
    df = _retry(lambda: ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date=end, adjust=""), tries=3)
    out = []
    for _, r in df.iterrows():
        d = str(r.get("date"))[:10]
        close = _f(r.get("close"))
        if not d or close is None:
            continue
        vol_hand = _f(r.get("amount"))          # 手
        volume = vol_hand * 100 if vol_hand is not None else None   # 份
        out.append({
            "code": code, "date": d,
            "open": _f(r.get("open")), "high": _f(r.get("high")),
            "low": _f(r.get("low")), "close": close,
            "volume": volume,
            "amount": (volume * close) if volume is not None else None,  # 近似成交额(元)
        })
    return out


# ---------------- 东财：单位净值 ----------------

def fetch_nav(code: str, since: Optional[str] = None) -> List[dict]:
    """东财-单位净值走势（全历史，一次请求）。since: YYYY-MM-DD 只保留之后的行。"""
    df = _retry(lambda: ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势"), tries=3)
    out = []
    for _, r in df.iterrows():
        d = str(r.get("净值日期"))[:10]
        nav = _f(r.get("单位净值"))
        if not d or nav is None or nav <= 0:
            continue
        if since and d < since:
            continue
        out.append({"code": code, "nav_date": d, "nav": nav, "growth": _f(r.get("日增长率"))})
    return out


# ---------------- 东财：费率 ----------------

def _rate_pct(s: Optional[str]) -> Optional[float]:
    """'1.50%' → 1.5；'0.00%' → 0。"""
    if s is None:
        return None
    m = re.search(r"([\d.]+)\s*%", str(s))
    return float(m.group(1)) if m else None


def fetch_fee(code: str) -> dict:
    """东财-申购/赎回费率分档。返回 {buy_tiers:[...], redeem_tiers:[...]}。"""
    buy, redeem = [], []
    try:
        df = _retry(lambda: ak.fund_fee_em(symbol=code, indicator="申购费率"), tries=2)
        for _, r in df.iterrows():
            amt = str(r.get("适用金额", r.get("申购金额", ""))).strip()
            rate = str(r.get("申购费率", "")).strip()
            if amt or rate:
                buy.append({"amount": amt, "rate": rate, "rate_pct": _rate_pct(rate)})
    except Exception:
        pass
    try:
        df = _retry(lambda: ak.fund_fee_em(symbol=code, indicator="赎回费率"), tries=2)
        for _, r in df.iterrows():
            term = str(r.get("适用期限", "")).strip()
            rate = str(r.get("赎回费率", "")).strip()
            if term or rate:
                redeem.append({"term": term, "rate": rate, "rate_pct": _rate_pct(rate)})
    except Exception:
        pass
    return {"buy_tiers": buy, "redeem_tiers": redeem}


# ---------------- 东财：申购状态全表（门槛） ----------------

def _mmdd_to_date(s) -> Optional[str]:
    """'09-24' → '2026-09-24'（按当前年份推断）。"""
    try:
        txt = str(s).strip()
        m = re.match(r"^(\d{2})-(\d{2})$", txt)
        if not m:
            return None
        today = _dt.date.today()
        mm, dd = int(m.group(1)), int(m.group(2))
        year = today.year
        if mm > today.month + 1:   # 明显是去年的日期
            year -= 1
        return f"{year:04d}-{mm:02d}-{dd:02d}"
    except Exception:
        return None


def fetch_purchase_all() -> List[dict]:
    """东财-基金申购状态一览（全部基金，含购买起点/日限额/手续费）。"""
    df = _retry(lambda: ak.fund_purchase_em(), tries=3)
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("基金代码", "")).strip()
        if not re.match(r"^\d{6}$", code):
            continue
        rows.append({
            "code": code,
            "name": str(r.get("基金简称", "")).strip(),
            "ftype": str(r.get("基金类型", "")).strip(),
            "nav": _f(r.get("最新净值/万份收益")),
            "nav_date": _mmdd_to_date(r.get("最新净值/万份收益-报告时间")),
            "purchase_status": str(r.get("申购状态", "")).strip(),
            "redeem_status": str(r.get("赎回状态", "")).strip(),
            "next_open": None if str(r.get("下一开放日")) in ("NaT", "nan", "None") else str(r.get("下一开放日"))[:10],
            "min_amount": _f(r.get("购买起点")),
            "daily_limit": _f(r.get("日累计限定金额")),
            "fee_rate": _f(r.get("手续费")),
        })
    return rows


if __name__ == "__main__":  # 快速自检
    print(json.dumps(fetch_lof_list()[:3], ensure_ascii=False))
    print(json.dumps(fetch_daily_tx("161725", "2026-09-01")[-2:], ensure_ascii=False))
    print(json.dumps(fetch_nav("161725", since="2026-09-01"), ensure_ascii=False))
    print(json.dumps(fetch_fee("161725"), ensure_ascii=False))
