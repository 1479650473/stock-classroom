# -*- coding: utf-8 -*-
"""news_driven.py — 事件驱动候选池生成器 (🅱️ 新闻调研 → 突发利好·短期观察).

蓝图: 在"总体选股之前"加新闻调研(当日热门板块/重大消息), 相关股票纳入考虑范围;
      **这类是突发利好, 不能影响长期策略** —— 故本池独立, 仅"考虑范围/短期观察",
      不进入 F价值Tilt 等长期组合重平衡.

数据源(本地零成本, 豆包搜索仅用于重大政策/宏观消息的板块热点词):
  - data/kline.db limit_up 表: 当日涨停股 (事件驱动核心)
  - data/kline.db sector_board 表: 热点板块(涨跌幅榜前N) 领涨股
  - 豆包搜索(可选, 每天1-2次): 重大政策/全球宏观消息 → 提取热点板块词
  - data/regime.json: 若系统风险触发, 事件驱动池收缩(不与截断交易矛盾)

产出 data/news_driven.json:
  {as_of, generated_at, regime, entries:[{code,name,price,change_pct,sector,source,reason,rank_score}],
   topics:[热点板块/消息词], macro_risk:{...}}

隔离: 本池仅供"选股页事件驱动页签/看盘页"展示 + 短期观察, 不喂给 portfolio_rebalance.
"""
from __future__ import annotations

import os, json, sqlite3, time
from datetime import datetime

from ..api.paths import DATA_DIR, KLINE_DB

NEWS_DRIVEN_PATH = os.path.join(DATA_DIR, "news_driven.json")
REGIME_PATH = os.path.join(DATA_DIR, "regime.json")

HOT_SECTOR_TOP_N = 10      # 取涨跌幅榜前N个热点板块
LIMIT_UP_TOP_N = 30        # 事件池最多取前N个涨停(按成交额排序, 封单/资金代表性强)
NEWS_QUERY_LIMIT = 2       # 每天最多豆包搜索次数(重大政策/宏观)


def _load_limit_up(date=None) -> list:
    """当日涨停股, 按成交额降序前 LIMIT_UP_TOP_N. date: YYYYMMDD, None=最新."""
    con = sqlite3.connect(KLINE_DB); con.row_factory = sqlite3.Row
    try:
        if not date:
            d = con.execute("SELECT MAX(date) FROM limit_up").fetchone()[0]
        else:
            d = str(date).replace("-", "").replace("/", "")
        if not d:
            return []
        rows = con.execute(
            "SELECT code,name,price,change_pct,amount,total_mv FROM limit_up "
            "WHERE date=? ORDER BY amount DESC LIMIT ?", (d, LIMIT_UP_TOP_N)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _load_hot_sectors(top_n: int = HOT_SECTOR_TOP_N) -> list:
    """热点板块(涨跌幅榜前N, 行业+概念), 含领涨股."""
    con = sqlite3.connect(KLINE_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT name,type,rank,change_pct,up_count,dn_count,leader,leader_chg "
            "FROM sector_board WHERE name IS NOT NULL AND name!='' "
            "ORDER BY change_pct DESC LIMIT ?", (top_n,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _sector_of(code: str) -> str:
    """若股票在 stock_sector 有板块映射则返回, 否则 ''."""
    try:
        con = sqlite3.connect(KLINE_DB)
        r = con.execute("SELECT sector FROM stock_sector WHERE code=?", (code,)).fetchone()
        con.close()
        return r[0] if r else ""
    except Exception:
        return ""


def _load_regime_field(key: str, default=None):
    try:
        with open(REGIME_PATH, encoding="utf-8") as f:
            return json.load(f).get(key, default)
    except Exception:
        return default


def _search_hot_topics(n_queries: int = NEWS_QUERY_LIMIT) -> list:
    """豆包搜索抓真正可用的财经/市场/政策消息 → 热点板块词.

    n_queries 限制每天搜索次数(节省额度); 只搜"全局市场"类 query, 不逐股搜.
    提示词必须带金融语境限定词(央行/沪深/证券/A股/政策/业绩), 否则返回社会/娱乐杂讯.
    """
    topics = []
    try:
        from ..agent.search_client import SearchClient, SearchError
        c = SearchClient()
    except Exception:
        return topics
    # 财经语境的查询(经实测: 带 央行/沪深股市/政策/业绩 等词 → 返回真实财经/市场/政策消息;
    #   "财经要闻"太宽泛 → 返回法拍别墅/娱乐杂讯)
    queries = [
        "央行 政策 今日 A股市场 影响 热点板块",
        "沪深股市 今日 重大公告 业绩预增 政策利好",
    ]
    # 非财经关键词黑名单(过滤豆包返回的社会/娱乐杂讯)
    _noise_kw = ["别墅", "马桶", "英伟达", "豪宅", "明星", "网红", "离婚", "拍卖", "撤拍",
                 "房", "房价", "包包", "直播", "网红", "外卖", "房子", "彩礼"]
    for q in queries[:max(0, n_queries)]:
        try:
            results = c.search_web(q, limit=6)
        except SearchError:
            continue
        for it in results:
            t = (it.get("title") or "").strip()
            if not t:
                continue
            if any(kw in t for kw in _noise_kw):
                continue    # 跳过杂讯
            topics.append(t[:80])
        if len(topics) >= 5:
            break
    return topics[:5]


def build_event_pool(use_news: bool = True, progress=None) -> dict:
    """构建事件驱动候选池, 落库 data/news_driven.json."""
    def _emit(m):
        if progress:
            try: progress(m)
            except Exception: pass
    _emit("① 取当日涨停股...")
    limit_up = _load_limit_up()
    _emit("② 取热点板块+领涨股...")
    hot_sectors = _load_hot_sectors()
    sectors = [{"name": s["name"], "type": s.get("type", ""),
                "change_pct": s.get("change_pct"), "leader": s.get("leader"),
                "leader_chg": s.get("leader_chg")} for s in hot_sectors]

    # ③ 事件驱动个股: 涨停股 ∪ 热点板块领涨股
    entries = []
    seen = set()
    for r in limit_up:
        code = str(r.get("code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        entries.append({
            "code": code, "name": r.get("name", ""),
            "price": r.get("price"), "change_pct": r.get("change_pct"),
            "amount": r.get("amount"), "sector": _sector_of(code),
            "source": "涨停", "reason": "当日涨停(成交额排序)", "rank_score": r.get("amount") or 0,
        })
    for s in hot_sectors:
        ld = s.get("leader")
        if ld:
            code = _resolve_leader_code(ld)
            if code and code not in seen:
                seen.add(code)
                entries.append({
                    "code": code, "name": ld, "price": None, "change_pct": s.get("leader_chg"),
                    "amount": None, "sector": s.get("name", ""),
                    "source": "热点板块", "reason": f"热点板块[{s.get('name')}]领涨股",
                    "rank_score": s.get("change_pct") or 0,
                })
    # 按成交额/涨幅排序
    entries.sort(key=lambda e: e["rank_score"] if isinstance(e["rank_score"], (int, float)) else 0, reverse=True)

    # ④ 宏观/政策消息 → 热点话题词(豆包搜索, 每天 n 次)
    topics = _search_hot_topics(NEWS_QUERY_LIMIT) if use_news else []

    regime = _load_regime_field("regime_cn", "震荡")
    sys_risk = _load_regime_field("sys_risk", {}) or {}
    # 系统风险触发时, 事件池收缩标注(不新建, 只标注风险, 与截断交易一致)
    macro_risk = {"regime": regime,
                  "triggered": bool(sys_risk.get("triggered")),
                  "reason": sys_risk.get("reason", "")}

    out = {
        "as_of": _load_limit_up_date(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "regime": regime, "macro_risk": macro_risk,
        "topics": topics, "hot_sectors": sectors,
        "entries": entries,
        "isolated": True,   # 隔离标记: 不进长期策略
    }
    try:
        with open(NEWS_DRIVEN_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return out


def _load_limit_up_date() -> str:
    try:
        con = sqlite3.connect(KLINE_DB)
        d = con.execute("SELECT MAX(date) FROM limit_up").fetchone()[0]
        con.close()
        return str(d) if d else ""
    except Exception:
        return ""


def _resolve_leader_code(leader_name: str) -> str:
    """按领涨股名查代码(尽力; 找不到返回 '')."""
    if not leader_name:
        return ""
    try:
        con = sqlite3.connect(KLINE_DB)
        r = con.execute("SELECT code FROM stock_list WHERE name=? LIMIT 1", (leader_name,)).fetchone()
        con.close()
        return str(r[0]) if r else ""
    except Exception:
        return ""


if __name__ == "__main__":
    pool = build_event_pool(use_news=True)
    print("事件驱动池 as_of:", pool.get("as_of"), "| regime:", pool.get("regime"))
    print("热点板块数:", len(pool.get("hot_sectors")), "| 事件股数:", len(pool.get("entries")))
    print("热门话题:", pool.get("topics", [])[:3])
    for e in pool.get("entries", [])[:8]:
        print(f"  [{e['source']}] {e['code']} {e['name']} {e['change_pct']}% 板块={e['sector']}")
