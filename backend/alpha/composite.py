# -*- coding: utf-8 -*-
"""固定权重因子组合打分（已用 10 折滚动验证：样本外为正 8/10 折，多空价差 +9.0%/年）。

组合成分（体检台筛出、等权 rank 合成）：
    -RET1        1 日反转（买跌的）
    -RET5        5 日反转
    -HIGH60_GAP  远离 60 日高点（超跌/便宜）
    -LOG_AMT20   小市值代理（成交额小）

对外只做一件事：给定基准日，按 as-of 数据算组合分并排出候选池
（结构与 trader.selection 的候选池一致，便于注入模型上下文、落库与前端展示）。
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import panel as P
from . import reward as R

#: (特征名, 方向)：负号表示"值越小越好"
COMPOSITE: Tuple[Tuple[str, float], ...] = (
    ("RET1", -1.0),
    ("RET5", -1.0),
    ("HIGH60_GAP", -1.0),
    ("LOG_AMT20", -1.0),
)

#: 因子中文名（审计输出用）
CN_NAME = {
    "RET1": "1日反转", "RET5": "5日反转", "HIGH60_GAP": "远离60日高点", "LOG_AMT20": "小市值",
    "VOL20": "20日波动", "TURN_RATIO": "换手率", "TURN_STD20": "换手波动",
}


def composite_score(codes: List[str], as_of: str, lookback_days: int = 130
                    ) -> Tuple[np.ndarray, Dict[str, np.ndarray], List[str], np.ndarray]:
    """返回 (组合分, 各成分分, 日期列表, 当日是否有行情)。as-of 安全。"""
    pan = P.load_panel(codes, _shift_days(as_of, lookback_days), as_of)
    dates: List[str] = pan["dates"]  # type: ignore[assignment]
    feats = P.build_features(pan["fields"])
    # 参考列 = 覆盖率≥60% 的最后一个交易日（日更未跑完时，最后一天可能只有部分股票有数据）
    close_all = pan["fields"]["close"]  # type: ignore[index]
    cov = (close_all > 0).mean(axis=0) if close_all.size else np.zeros(1, dtype=np.float32)
    good = np.where(cov >= 0.6)[0]
    t = int(good[-1]) if good.size else int(close_all.shape[1] - 1)
    dates = dates[: t + 1]
    parts: Dict[str, np.ndarray] = {}
    for name, sign in COMPOSITE:
        arr = feats.get(name)
        if arr is None:
            continue
        parts[name] = (arr[:, t] * sign).astype(np.float32)      # 只用参考日那一列（as-of 安全）
    last_ok = close_all[:, t] > 0
    if not parts:
        return np.zeros(len(codes), dtype=np.float32), {}, dates, last_ok
    # 等权 rank 合成（截面 rank 归一，天然抗量纲）
    acc = np.zeros(len(codes), dtype=np.float32)
    for name, v in parts.items():
        order = np.argsort(np.argsort(v)) / max(1, len(v) - 1)
        acc += order.astype(np.float32)
    acc /= float(len(parts))
    return acc, parts, dates, last_ok


def _shift_days(as_of: str, back: int) -> str:
    """把 YYYYMMDD / YYYY-MM-DD 往前推 back 个自然日（只用于取数据窗口）。"""
    import datetime as _dt
    s = as_of.replace("-", "")
    d = _dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])) - _dt.timedelta(days=int(back))
    return d.isoformat()


def snapshot(as_of: Optional[str] = None, top_n: int = 12, universe_limit: int = 400,
             min_amount: float = 3e7) -> Dict:
    """按组合分构建候选池快照（结构与 trader.selection.build_snapshot 对齐）。"""
    t0 = time.time()
    ref = (str(as_of or "").replace("-", "") or None)
    if ref is None:
        import datetime as _dt
        ref = _dt.date.today().strftime("%Y%m%d")
    iso = f"{ref[:4]}-{ref[4:6]}-{ref[6:8]}"
    codes = P.pick_universe(limit=int(universe_limit), min_amount=float(min_amount), as_of=iso)
    score, parts, dates, live = composite_score(codes, iso)
    if not dates:
        return {"as_of": ref, "picks": [], "stats": {"universe": len(codes)}, "error": "没有可用行情"}

    keep = np.isfinite(score) & live          # 当日必须有行情（停牌/退市剔除）
    names: Dict[str, str] = {}
    try:
        import sqlite3
        from ..api.paths import KLINE_DB
        con = sqlite3.connect(KLINE_DB)
        ph = ",".join("?" for _ in codes)
        for c, n in con.execute(f"SELECT code, name FROM stock_list WHERE code IN ({ph})", codes):
            names[str(c)] = str(n or "")
        con.close()
    except Exception:
        names = {}
    order = np.argsort(-np.nan_to_num(score, nan=-1e9))
    picks: List[Dict] = []
    for i in order:
        if len(picks) >= int(top_n):
            break
        if not keep[i]:
            continue
        picks.append({
            "rank": len(picks) + 1,
            "code": codes[i],
            "name": names.get(codes[i], ""),
            "score": round(float(score[i]) * 100.0, 2),   # 0~100 便于与评分卡比较
            "groups": [{"name": CN_NAME.get(n, n), "weight": 1.0,
                        "score": round(float(np.argsort(np.argsort(parts[n]))[i]) /
                                       max(1, len(codes) - 1) * 100.0, 1)}
                       for n in parts],
        })
    return {
        "as_of": dates[-1],
        "components": [{"factor": n, "direction": ("+" if s > 0 else "-"),
                        "cn": CN_NAME.get(n, n)} for n, s in COMPOSITE],
        "universe": len(codes),
        "picks": picks,
        "stats": {"universe": len(codes), "scored": int(keep.sum()),
                  "returned": len(picks), "elapsed_sec": round(time.time() - t0, 1)},
        "error": "",
    }
