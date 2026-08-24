# -*- coding: utf-8 -*-
"""为截面因子研究加载"个股池 frames" — 从 kline.db 构建 {code: DataFrame}。

每只股票 DataFrame index=date(升序), columns=[open,high,low,close,volume]。
供 FactorResearchEngine 做截面 IC/分组/多空 研究。
"""
from __future__ import annotations

import pandas as pd

from .data import load_klines


def load_universe_frames(codes, start: str | None = None, end: str | None = None,
                         limit: int = 1200, with_fundamentals: bool = False,
                         fetch_missing: bool = False) -> dict:
    """codes: 列表; 返回 {code: DataFrame}。start/end: 'YYYYMMDD' 过滤。

    with_fundamentals=True 时附加点时间 EP/BP/ROE 列(价值/质量, 含披露滞后或无前视)。
    fetch_missing=False(默认): **只读已缓存**基本面 —— 研究/回测读路径绝不联网, 避免重复拉取;
    True 时对未缓存代码补抓(仅预抓场景用, 会联网且慢)。
    """
    frames = {}
    for code in codes:
        kd, _ = load_klines(code, limit=limit, warn_short=False)
        if not kd:
            continue
        df = pd.DataFrame([{**k, "date": str(k["date"])} for k in kd])
        if df.empty:
            continue
        # 日期可能是 "20260518" 或 "2026-05-18"(源不一致) → 归一化再解析, 坏行丢弃
        df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.set_index("date").sort_index()
        if start:
            df = df.loc[df.index >= pd.Timestamp(start)]
        if end:
            df = df.loc[df.index <= pd.Timestamp(end)]
        needed = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in needed if c in df.columns]]
        if len(df) >= 60:
            # 附加行业(板块)列 → 支持 neutralize_industry 去板块效应
            df["industry"] = _sector_of(code)
            frames[code] = df
    if with_fundamentals and frames:
        from ..fundamental import attach_fundamentals, ensure_fundamental
        # 只读缓存(默认)不触发抓取 → 本地化保证; 显式 fetch_missing 才补抓
        if fetch_missing:
            for code in list(frames):
                ensure_fundamental(code)
        frames = attach_fundamentals(frames)
    return frames


def _sector_of(code: str):
    """股所属板块(用于行业中性化); 无则 None。"""
    try:
        from . import catalog as _cat
        d = _cat.describe(code) or {}
        secs = d.get("sectors") or []
        return secs[0] if secs else None
    except Exception:
        return None
