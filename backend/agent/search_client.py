# -*- coding: utf-8 -*-
"""search_client.py — 豆包搜索 Custom 版客户端 (LLM 主观判断的资讯/消息源).

数据源: 豆包搜索 API Key 接入, URL https://open.feedcoopapi.com/search_api/web_search
认证:   Authorization: Bearer <api_key>  (存 backend/configs/settings.json 的 search 节)
请求体: 大驼峰字段 {Query: str, SearchType: 'web'|'image'}  (小驼峰 query/search_type 会 10400)
返回:   Result.WebResults[] 每条含 Title/Url/SiteName/Snippet/PublishTime/.../RankScore

用途: 第2期『LLM 介入主观内容』 — 读个股新闻/研报/资讯做情绪&消息面判断.
     LLM 调用方拿 search_web(query) 的结果标题+摘要投喂 LLM, 输出利好/利空/中性评分.

安全: api_key 读自 settings.json (gitignored), 日志/异常里绝不打印完整 key.
"""
from __future__ import annotations

import json, urllib.request, urllib.parse
from pathlib import Path
from typing import Optional

SEARCH_URL = "https://open.feedcoopapi.com/search_api/web_search"


def get_search_config() -> dict:
    """读 settings.json 的 search 节 (豆包搜索凭证). 未配置返回 {}."""
    p = Path(__file__).resolve().parents[2] / "backend" / "configs" / "settings.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data.get("search", {}) or {}


class SearchError(Exception):
    pass


class SearchClient:
    """豆包搜索客户端. api_key 为空时抛 SearchError, 调用方应降级(跳过资讯因子)."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 20.0):
        cfg = get_search_config()
        self.api_key = api_key or cfg.get("api_key", "")
        self.timeout = timeout
        if not self.api_key:
            raise SearchError("未配置豆包搜索 api_key(可在 backend/configs/settings.json 的 search 节设置)")

    def search_web(self, query: str, limit: int = 5, search_type: str = "web") -> list:
        """搜索网页, 返回 [{title,url,site,snippet,publish_time,rank_score,...}] 前 limit 条.

        空结果/失败返回 [] (调用方自行降级, 不抛异常).
        """
        body = {"Query": query, "SearchType": search_type}
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key}
        req = urllib.request.Request(SEARCH_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise SearchError(f"豆包搜索 HTTP {e.code}: {e.read()[:200].decode('utf-8','replace')}")
        except Exception as e:
            raise SearchError(f"豆包搜索失败: {str(e)[:120]}")

        meta = resp.get("ResponseMetadata", {})
        err = meta.get("Error") or {}
        if err.get("Code") and err.get("Code") != "0":
            raise SearchError(f"豆包搜索 {err.get('Code')}: {err.get('Message', '')[:120]}")
        result = resp.get("Result") or {}
        rows = result.get("WebResults") or []
        out = []
        for r0 in rows[:max(1, limit)]:
            out.append({
                "title": r0.get("Title", ""),
                "url": r0.get("Url", ""),
                "site": r0.get("SiteName", ""),
                "snippet": r0.get("Snippet", ""),
                "publish_time": r0.get("PublishTime", ""),
                "authority": r0.get("Authority", ""),
                "rank_score": r0.get("RankScore"),
            })
        return out


if __name__ == "__main__":
    # 冒烟测试: 查询个股最新消息
    import sys
    try:
        c = SearchClient()
        for q in ("贵州茅台 半年报", "宁德时代 最新"):
            print(f"=== 查询: {q} ===")
            for it in c.search_web(q, limit=3):
                print(f"  [{it['site']}] {it['title']} | {it['publish_time']}")
                print(f"    {it['snippet'][:80]}")
    except SearchError as e:
        print("SearchError:", e)
        sys.exit(1)
