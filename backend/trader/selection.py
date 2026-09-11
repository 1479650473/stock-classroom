# -*- coding: utf-8 -*-
"""选股链路 —— 候选池构建与审计。

"候选股是怎么来的"必须说得清、查得到，否则就是黑箱。本模块把整条链路结构化输出：

    股票池(stock_list) → 规则过滤(ST/北交所/价格) → 60 日 K 线 → 五组加权打分 → Top N

返回的快照里包含：股票池口径与数量、生效的过滤规则、评分卡与各组权重、基准日、
参与评分数与被跳过数、每只候选的总分与分项得分、事件驱动池。

同一份快照有三个用途：
  1. 注入模型上下文（模型自己能看到候选是怎么筛出来的）
  2. 随决策一起落库 trader_decision.candidates（事后可逐日核对，不发生前视/替换）
  3. API 与前端展示

实时与回放共用本模块：ref_date=None 走最新数据，传 YYYY-MM-DD/YYYYMMDD 则按 as-of 截断
（回放的候选必须截止到当天，绝不能用未来数据）。
"""
from __future__ import annotations

import json
import os

from ..api.paths import DATA_DIR, KLINE_DB

NEWS_DRIVEN_PATH = os.path.join(DATA_DIR, "news_driven.json")

UNIVERSE_NOTE = (
    "kline.db · stock_list(status='active')，仅保留 60/00/30/68 开头"
    "（沪主板/深主板/创业板/科创板）；北交所代码不进入股票池"
)

# 与 factor_engine.filters.DEFAULT_FILTERS 一一对应的可读规则
_FILTER_LABELS = (
    ("exclude_st", "剔除 ST/*ST"),
    ("exclude_bj", "剔除北交所（83/87/43 开头）"),
    ("exclude_kcb", "剔除科创板（688 开头）"),
    ("exclude_cyb", "剔除创业板（30 开头）"),
)


def _filter_rows(filters: dict) -> list:
    rows = [{"rule": label, "on": bool(filters.get(k))} for k, label in _FILTER_LABELS]
    mp = float(filters.get("min_price") or 0)
    xp = float(filters.get("max_price") or 0)
    rows.append({"rule": f"价格区间 {'不限' if not mp else mp} ~ {'不限' if not xp else xp}",
                 "on": bool(mp or xp)})
    return rows


def _scorecard_info(weights=None) -> dict:
    """评分卡口径：数据窗口 + 各因子组权重（config.groups 是 dict 列表）。

    weights 非空时展示覆盖后的口径（对照实验用），并标出改了哪几组。
    """
    try:
        from ..factor_engine.config import load_config_with_weights, resolve_weights
        cfg = load_config_with_weights(weights)
        groups = []
        for g in cfg.groups or []:
            groups.append({
                "id": g.get("id") or "",
                "name": g.get("name") or "",
                "weight": float(g.get("weight") or 0),
                "max_score": float(g.get("max_score") or g.get("weight") or 0),
            })
        w = resolve_weights(weights)
        return {"name": cfg.name or "", "version": cfg.version or "",
                "data_window": int(cfg.data_window or 0), "groups": groups,
                "weights_override": w}
    except Exception as e:
        return {"error": f"评分卡读取失败：{e}"}


def _events_block(top_n: int) -> dict:
    """事件驱动池（涨停/热点板块/消息），仅实时可用；回放不可回溯历史新闻。"""
    try:
        with open(NEWS_DRIVEN_PATH, encoding="utf-8") as f:
            nd = json.load(f)
        return {
            "events": [{
                "code": e.get("code"), "name": e.get("name"),
                "reason": e.get("reason") or e.get("tag") or "",
            } for e in (nd.get("entries") or [])[:top_n]],
            "hot_sectors": nd.get("hot_sectors") or [],
            "as_of": nd.get("date") or nd.get("updated_at") or "",
        }
    except Exception:
        return {"events": [], "hot_sectors": [], "as_of": ""}


def build_snapshot(ref_date: str | None = None, top_n: int = 12,
                   with_events: bool = True, weights=None) -> dict:
    """构建候选池快照。

    Args:
        ref_date: None=实时最新；'YYYY-MM-DD' 或 'YYYYMMDD'=按该日 as-of 截断（回放/回测）
        top_n: 返回候选数量
        with_events: 是否附事件驱动池（回放应为 False）
        weights: 评分口径覆盖（预设名 'steady' / {组id:满分} / "trend:18,..."），None=默认口径
    """
    ref = (str(ref_date or "").replace("-", "") or None)
    from ..factor_engine.config import resolve_weights
    wover = resolve_weights(weights)
    out = {
        "as_of": ref or "实时最新",
        "mode": "as_of" if ref else "live",
        "chain": "stock_list(active) → 规则过滤 → 60日K线 → 五组加权打分 → TopN",        "universe": UNIVERSE_NOTE,
        "reference_date": ref or "",
        "scorecard": _scorecard_info(weights),
        "weights_override": wover,
        "filters": [],
        "stats": {},
        "picks": [],
        "events": [],
        "hot_sectors": [],
        "error": "",
    }
    try:
        from ..factor_engine import DEFAULT_FILTERS, FactorScorer
        from ..factor_engine.config import load_config_with_weights
        from ..factor_engine.filters import apply_filters

        universe = FactorScorer._get_candidates(KLINE_DB)
        kept_pairs = apply_filters(universe, DEFAULT_FILTERS, KLINE_DB)
        stats: dict = {}
        scorer = FactorScorer(config=load_config_with_weights(weights))
        picks = scorer.score_batch(KLINE_DB, top_n=int(top_n or 12), min_klines=10,
                                   timeout_seconds=90, filters=DEFAULT_FILTERS,
                                   ref_date=ref, stats=stats)
        out["filters"] = _filter_rows(DEFAULT_FILTERS)
        out["stats"] = {
            "universe_total": len(universe),
            "after_filters": len(kept_pairs),
            "filtered_out": len(universe) - len(kept_pairs),
            "scored": int(stats.get("scored") or 0),
            "skipped_short_history": int(stats.get("skipped_short") or 0),
            "failed": int(stats.get("failed") or 0),
            "returned": len(picks),
        }
        out["picks"] = [{
            "rank": i,
            "code": s.code,
            "name": s.name,
            "score": round(float(getattr(s, "total_score", 0) or 0), 2),
            "groups": [{
                "name": g.name,
                "weight": float(g.weight),
                "score": round(float(g.weighted_score), 2),
            } for g in getattr(s, "groups", [])],
        } for i, s in enumerate(picks, 1)]
    except Exception as e:
        out["error"] = f"候选池构建失败：{e}"
    if with_events:
        ev = _events_block(int(top_n or 12))
        out["events"] = ev["events"]
        out["hot_sectors"] = ev["hot_sectors"]
        out["events_as_of"] = ev["as_of"]
    out["scope_note"] = compact_note(out)
    return out


def compact_note(snap: dict) -> dict:
    """给模型的「候选池说明」——只保留口径，不重复候选明细。"""
    st = snap.get("stats") or {}
    return {
        "链路": snap.get("chain"),
        "股票池": snap.get("universe"),
        "基准日": snap.get("as_of"),
        "生效过滤": [f["rule"] for f in (snap.get("filters") or []) if f.get("on")] or ["无"],
        "评分卡": {
            "名称": (snap.get("scorecard") or {}).get("name"),
            "窗口": f"{(snap.get('scorecard') or {}).get('data_window')} 个交易日",
            "权重": [f"{g.get('name')}{g.get('weight'):g}" for g in (snap.get("scorecard") or {}).get("groups") or []],
        },        "统计": {
            "股票池": st.get("universe_total"),
            "过滤后": st.get("after_filters"),
            "实际评分": st.get("scored"),
            "K线不足跳过": st.get("skipped_short_history"),
            "返回候选": st.get("returned"),
        },
        "说明": "候选是系统按上述规则自动筛出的，你也可以只凭自己的判断买池外的股票，但要在 reason 里写清依据。",
    }
    if (snap.get("weights_override") or {}):
        note["评分卡"]["口径覆盖"] = snap["weights_override"]
    return note
