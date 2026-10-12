# -*- coding: utf-8 -*-
"""stock_deep.py — 🅰️ 个股资讯深挖 + LLM 独立主观判断 (选股剩最后几只后).

蓝图: "选股选到最后剩几只之后, 针对这几只查看它的公司资讯做分析".
关键设计(用户明确):
  - 只对**最后剩的少数几只**(如 top 8)深挖, 不逐全市场(省额度);
  - LLM **直接独立主观判断**, 输出文字结论(前置/后移/保持/剔名 + 理由),
    系统**原样采纳**, 不再解析成数值评分/二次加工.

数据流:
  picks 选股 top_n → deep_analyze(candidates) →
    ① 每只豆包搜索公司资讯(search_client.search_web)
    ② 组装上下文: 公司新闻 + 多因子得分/各维度 + 当前排名 + 长期策略角色
    ③ LLM(llm_client) 判断 → 输出 {code, verdict(前置/后移/保持/剔名), reason, confidence}
  落库 data/stock_deep.json; 供选股页'资讯深挖'区块展示 + 最终排序微调.

隔离: 本模块只做**最终排序微调**, 不改变因子权重/策略契约; LLM 判断偏向"风险/关注度",
      极端情况下提示剔名(有重大利空), 但不硬性剔除(尊重多因子为主).
"""
from __future__ import annotations

import os, json
from datetime import datetime

from ..api.paths import DATA_DIR, KLINE_DB

STOCK_DEEP_PATH = os.path.join(DATA_DIR, "stock_deep.json")

VERDICTS = ("前置", "后移", "保持", "剔名")


def _search_company_news(name: str, code: str, limit: int = 4) -> list:
    """豆包搜索个股公司资讯(标题+摘要). 无 key/失败返回 [](降级, 不阻塞)."""
    try:
        from ..agent.search_client import SearchClient, SearchError
        c = SearchClient()
    except Exception:
        return []
    # 财经语境的个股查询
    q = f"{name} {code} 公司 公告 业绩 最新消息"
    try:
        return c.search_web(q, limit=limit)
    except SearchError:
        return []


def _llm_verdict(name: str, code: str, profile: dict, news: list) -> dict:
    """LLM 独立主观判断: 给出 {verdict, reason, confidence}.

    profile: 该股的多因子画像(rank/total_score/groups_name/亮点/短板).
    news:   豆包搜索到的公司资讯(标题+摘要).
    """
    try:
        from ..agent.llm_client import LLMClient, LLMError
        llm = LLMClient()
    except Exception:
        return {"verdict": "保持", "reason": "LLM不可用, 维持多因子排序", "confidence": 0.0}
    news_lines = "\n".join(f"- {n.get('title','')} | {n.get('snippet','')[:60]}" for n in news[:4])
    if not news_lines:
        news_lines = "(未搜索到公司相关资讯)"
    prompt = (
        "你是A股资深基本面+消息面研究员, 正在对一只已通过多因子技术面筛选的股票做公司资讯深挖。\n"
        "请基于以下【多因子画像】和【最新公司资讯】,**独立主观判断**这只股票在当前选股结果里应该怎么调整。\n\n"
        f"【股票】{name}({code})\n"
        f"【多因子画像】综合分 {profile.get('total_score')}, 当前排名 {profile.get('rank')}/{profile.get('pool')}\n"
        f"  亮点: {profile.get('highlights', '—')}\n"
        f"  短板: {profile.get('weaknesses', '—')}\n"
        f"【最新公司资讯】\n{news_lines}\n\n"
        "请判断: 这只股票的公司资讯对该股是 利好/利空/中性? 结合多因子表现, 你建议在选股排序里怎么调?\n"
        "只输出 JSON, 格式: {\"verdict\":\"前置|后移|保持|剔名\",\"reason\":\"一句话理由\",\"confidence\":0~1}\n"
        "规则: 重大利好(业绩预增/重组/政策受益)→前置; 重大利空(暴雷/诉讼/业绩暴降)→剔名或后移;\n"
        "一般消息→保持; 不确定→保持. 不要输出 markdown 围栏, 不要解释.\n"
    )
    try:
        text = llm.complete("你是A股消息面判断助手, 只输出JSON。", prompt, max_tokens=300)
        obj = _extract_json(text)
        verdict = obj.get("verdict", "保持")
        if verdict not in VERDICTS:
            verdict = "保持"
        return {"verdict": verdict,
                "reason": str(obj.get("reason", ""))[:120],
                "confidence": float(obj.get("confidence", 0.5))}
    except LLMError as e:
        return {"verdict": "保持", "reason": f"LLM异常: {str(e)[:60]}", "confidence": 0.0}


def _extract_json(text: str) -> dict:
    import re
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def deep_analyze(candidates: list, progress=None) -> dict:
    """对最后剩的几只候选股做资讯深挖 + LLM 主观判断.

    candidates: [{code,name,total_score,rank,groups,...}] 选股 final 结果.
    返回落库 data/stock_deep.json: {as_of, entries:[{code,name,verdict,reason,confidence,news:[...]}]}.
    """
    def _emit(m):
        if progress:
            try: progress(m)
            except Exception: pass
    as_of = None
    entries = []
    # 压缩 profile: 每只的亮点/短板(从 groups 高分/低分维度提取)
    for cand in candidates[:8]:
        code = cand.get("code", ""); name = cand.get("name", "")
        if not code:
            continue
        groups = cand.get("groups", []) or []
        # 亮短板: 按 weighted 排序取前2高分/后1低分维度名
        gs = sorted(groups, key=lambda g: g.get("weighted_score", 0), reverse=True)
        highlights = "; ".join(f"{g.get('name')}({g.get('weighted_score')})" for g in gs[:2]) or "—"
        weaknesses = "; ".join(f"{g.get('name')}({g.get('weighted_score')})" for g in gs[-1:]) if len(gs) > 2 else "—"
        profile = {"total_score": cand.get("total_score"), "rank": cand.get("rank"),
                   "pool": cand.get("pool", 8), "highlights": highlights, "weaknesses": weaknesses}
        _emit(f"深挖 {name}({code}) 公司资讯...")
        news = _search_company_news(name, code)
        _emit(f"  → 搜到 {len(news)} 条, LLM 判断...")
        v = _llm_verdict(name, code, profile, news)
        if not as_of:
            as_of = _latest_as_of()
        entries.append({"code": code, "name": name, "verdict": v.get("verdict"),
                        "reason": v.get("reason"), "confidence": v.get("confidence"),
                        "news": news[:4]})
    out = {"as_of": as_of, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "entries": entries}
    try:
        with open(STOCK_DEEP_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return out


def _latest_as_of() -> str:
    try:
        import sqlite3
        con = sqlite3.connect(KLINE_DB)
        d = con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
        con.close()
        return str(d) if d else ""
    except Exception:
        return ""


if __name__ == "__main__":
    # 冒烟测试: 就用事件驱动池里前几只做深挖
    import sys
    sys.path.insert(0, os.path.join(ROOT, "backend"))
    from backend.strategy.news_driven import build_event_pool
    pool = build_event_pool(use_news=False)
    cands = [{"code": e["code"], "name": e["name"], "total_score": 60 + i, "rank": i + 1,
              "groups": [{"name": "价值", "weighted_score": 80}, {"name": "动量", "weighted_score": 55},
                         {"name": "低波", "weighted_score": 70}]} for i, e in enumerate(pool["entries"][:3])]
    r = deep_analyze(cands)
    print("深挖 as_of:", r.get("as_of"))
    for e in r["entries"]:
        print(f"  {e['name']}({e['code']}) → {e['verdict']} conf={e['confidence']} | {e['reason'][:50]}")
