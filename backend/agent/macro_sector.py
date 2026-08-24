# -*- coding: utf-8 -*-
"""M2: 宏观条件化选板块 — 把宏观 regime 喂给标的域选择。

确定性启发式(可被 LLM 取代)：根据宏观 categories(equity/fx/rate/commodity/vol)
映射到 25 个粗赛道之一，再取该板块代表股。板块名必须存在于 catalog.sectors() 白名单。
"""
from __future__ import annotations

from ..strategy import catalog as catalog_mod

# 宏观状态 → 优先板块(均须在 25 粗板块白名单内)
_DEFENSIVE = ["银行", "医药/医疗"]                 # risk-off / 高波动
_RESOURCE = ["黄金/有色", "稀有金属/稀土", "电力/能源", "化工/材料"]  # 通胀+利率上行
_GROWTH = ["半导体/芯片", "AI/人工智能", "互联网/软件"]              # 利率下行
_FX_STRONG = ["白酒/食品", "银行"]                  # 人民币升值(外资偏好)
_DEFAULT = ["白酒/食品", "银行"]


def pick_sector(macro: dict, known: list[str] | None = None) -> tuple[str, str]:
    """返回 (板块名, 理由)。known 若不传则取 catalog.sectors()。"""
    if known is None:
        known = catalog_mod.sectors()
    known_set = set(known)

    def first(items: list[str]) -> str | None:
        for s in items:
            if s in known_set:
                return s
        return None

    cat = macro.get("categories", {}) or {}
    rate = cat.get("rate", {}) or {}
    com = cat.get("commodity", {}) or {}
    vol = cat.get("vol", {}) or {}
    overall = str(macro.get("overall", ""))

    # 1) 高波动 / risk-off → 防御
    if "高波动" in str(vol.get("label", "")) or "risk-off" in overall:
        s = first(_DEFENSIVE)
        if s:
            return s, "风险偏好弱→防御(银行/医药)"

    # 2) 商品通胀 + 利率上行 → 顺周期/资源
    com_label = str(com.get("label", ""))
    rate_label = str(rate.get("label", ""))
    if ("金" in com_label or "油" in com_label) and "上行" in rate_label:
        s = first(_RESOURCE)
        if s:
            return s, "通胀+利率上行→顺周期/资源"

    # 3) 利率下行 → 成长(降息利好长久期成长)
    if "下行" in rate_label:
        s = first(_GROWTH)
        if s:
            return s, "利率下行→成长(科技/半导体)"

    # 4) 人民币升值(美元走弱) → 外资偏好消费白马
    if "升值" in overall:
        s = first(_FX_STRONG)
        if s:
            return s, "人民币升值→消费白马"

    s = first(_DEFAULT)
    return (s or "银行"), "默认(白酒/银行)"


def pick_universe(macro: dict, owner=None) -> dict:
    """宏观→板块→代表股。owner: 提供 catalog 操作(缺省用 catalog 模块)。返回
    {id, code, name, sector, reason, universe_selector}。"""
    sector, reason = pick_sector(macro)

    # 取板块内第一只(按 code 升序)作为代表股；可后续按市值/流动性优化
    items = catalog_mod.select(sector=sector, status="active", exclude_st=True)
    if not items:
        items = catalog_mod.select(sector=sector, status="active")
    if items:
        top = items[0]
        return {"id": top["code"], "code": top["code"], "name": top["name"],
                "sector": sector, "reason": reason,
                "desc": f"{sector} 代表股({len(items)}只候选)", "universe_selector": True}
    return {"id": "600036", "code": "600036", "name": "招商银行", "sector": "银行",
            "reason": reason, "desc": "默认标的", "universe_selector": False}
