# -*- coding: utf-8 -*-
"""为截面因子研究加载"个股池 frames" — 从 kline.db 构建 {code: DataFrame}。

每只股票 DataFrame index=date(升序), columns=[open,high,low,close,volume]。
供 FactorResearchEngine 做截面 IC/分组/多空 研究。
"""
from __future__ import annotations

import pandas as pd

from .data import load_klines


def load_universe_frames(codes, start: str | None = None, end: str | None = None,
                         limit: int = 1200) -> dict:
    """codes: 列表; 返回 {code: DataFrame}。start/end: 'YYYYMMDD' 过滤。"""
    frames = {}
    for code in codes:
        kd, _ = load_klines(code, limit=limit, warn_short=False)
        if not kd:
            continue
        df = pd.DataFrame([{**k, "date": str(k["date"])} for k in kd])
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df = df.set_index("date").sort_index()
        if start:
            df = df.loc[df.index >= pd.Timestamp(start)]
        if end:
            df = df.loc[df.index <= pd.Timestamp(end)]
        needed = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in needed if c in df.columns]]
        if len(df) >= 60:
            frames[code] = df
    return frames
