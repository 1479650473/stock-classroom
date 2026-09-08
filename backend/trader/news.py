# -*- coding: utf-8 -*-
"""操盘手行情新闻采集。

数据源（本地零成本，按日缓存）：
  - 市场/宏观：ak.stock_info_global_em()  东财全球财经快讯（标题/摘要/时间/链接）
  - 个股：akshare_source.ak_get_stock_news(code)  东财个股新闻
  - 豆包搜索（可选）：settings.json 的 search 节配置了 api_key 时补充查询

设计约束：所有外部调用都可能慢/失败，必须短超时、失败降级为空列表，
绝不阻塞每日决策。市场新闻按日期缓存到 data/trader_news.json。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import List, Optional

from ..api.paths import DATA_DIR

_CACHE_PATH = os.path.join(DATA_DIR, "trader_news.json")
_MARKET_TTL = 30 * 60      # 30 分钟内复用同一份市场新闻
_MARKET_LIMIT = 20


def _cache_read() -> dict:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cache_write(data: dict) -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def market_news(limit: int = _MARKET_LIMIT, force: bool = False) -> List[dict]:
    """东财全球财经快讯，返回 [{title, summary, time, url}]。失败返回 []。"""
    today = datetime.now().strftime("%Y-%m-%d")
    cache = _cache_read()
    slot = cache.get("market") or {}
    fresh = (slot.get("date") == today
             and time.time() - float(slot.get("ts", 0)) < _MARKET_TTL
             and len(slot.get("items") or []) >= min(limit, 5))
    if fresh and not force:
        return (slot.get("items") or [])[:limit]

    items: List[dict] = []
    try:
        import akshare as ak
        df = ak.stock_info_global_em()
        for _, r in df.iterrows():
            title = str(r.get("标题", "") or "").strip()
            if not title:
                continue
            items.append({
                "title": title,
                "summary": str(r.get("摘要", "") or "")[:180],
                "time": str(r.get("发布时间", "") or ""),
                "url": str(r.get("链接", "") or ""),
            })
            if len(items) >= limit:
                break
    except Exception:
        items = []

    if items:
        cache["market"] = {"date": today, "ts": time.time(), "items": items}
        _cache_write(cache)
    return items[:limit]


def stock_news(code: str, name: str = "", limit: int = 4) -> List[dict]:
    """个股新闻，返回 [{title, time, url, source}]。失败返回 []。"""
    try:
        from ..akshare_source import ak_get_stock_news
        rows = ak_get_stock_news(str(code), limit=limit) or []
    except Exception:
        return []
    out = []
    for r in rows[:limit]:
        out.append({
            "title": str(r.get("title", "") or ""),
            "time": str(r.get("time", "") or ""),
            "url": str(r.get("url", "") or ""),
            "source": str(r.get("source", "") or ""),
        })
    return out


def doubao_search(query: str, limit: int = 5) -> List[dict]:
    """豆包搜索（可选）：settings.json 未配置 search.api_key 时返回 []。"""
    try:
        from ..agent.search_client import SearchClient, SearchError
        try:
            client = SearchClient()
        except SearchError:
            return []
        return client.search_web(query, limit=limit) or []
    except Exception:
        return []
