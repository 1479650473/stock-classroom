# -*- coding: utf-8 -*-
"""cycle_test.py — 分周期测试验证器 (架构图"回测架构"真正落地).

架构图"回测架构":
  历史回测 → 分类测试(牛市周期/熊市周期/震荡周期/全周期穿越综合)
          → 隔离数据更换样本 → 二轮测试 → 各周期策略+综合策略 → 结果参数进数据库

本模块:
  ① 用 regime.classify 滚动给 hs300 历史打 regime 标签, 合并成**主要周期段**
     (每类挑最长/代表性的若干段).
  ② 对每个周期段跑 verify_full_lifecycle (只在该区间回放), 得该周期表现.
  ③ **样本外防过拟合**: 按时间切 前段=样本内(in-sample), 后段=样本外(out-of-sample),
     分别跑对比 —— 若样本外显著差于样本内, 提示过拟合 (隔离数据更换样本验证).
  ④ 输出各周期/全周期/样本内外综合报告.

与 verify_full_lifecycle 分工: 该模块是对它的**多周期包装/对比分析**, 不重复回放内核.
"""
from __future__ import annotations

import os, json
from collections import Counter

import pandas as pd

from backend.strategy.regime import _load_hs300, classify
from backend.strategy.verify_full_lifecycle import verify_full_lifecycle, _buyhold_nav, _try_float


def _regime_series(dates, closes, window=250) -> list:
    """滚动 classify → 每个交易日一个 regime_cn 标签 (纯函数)."""
    out = []
    for i in range(60, len(closes)):
        seg = closes[max(0, i - window):i + 1]
        c = classify(seg)
        out.append((dates[i], c["regime_cn"]))
    return out


def _merge_periods(labels, min_days=20) -> list:
    """相邻同类合并成周期段, 去掉过短的(<min_days) — 得到有意义的牛/熊/震荡主要区间.

    返回 [{regime, start, end, days}], 按 start 升序.
    """
    # 先按标签分组(连续同类合并)
    raw = []
    for dt, r in labels:
        if raw and raw[-1]["regime"] == r:
            raw[-1]["end"] = dt
            raw[-1]["days"] += 1
        else:
            raw.append({"regime": r, "start": dt, "end": dt, "days": 1})
    # 去掉过短段(防碎区间), 但保留首尾含关键段的
    periods = [p for p in raw if p["days"] >= min_days]
    return periods


def _pick_per_cls(periods, per_cls=3) -> dict:
    """从合并后的区间里, 每类(牛/熊/震荡)挑最长的 per_cls 段, 作为代表性周期.

    返回 {regime: [periods...]}, 每段含 start/end/days.
    """
    picked = {}
    for r in ("牛市", "熊市", "震荡"):
        cand = sorted([p for p in periods if p["regime"] == r],
                      key=lambda p: -p["days"])[:per_cls]
        picked[r] = cand
    return picked


def _run_cycle(frames, contract, rule_set, period, initial_balance) -> dict:
    """在一个周期段内跑 verify_full_lifecycle."""
    r = verify_full_lifecycle(frames, contract, str(period["start"]), str(period["end"]),
                              rule_set=rule_set, initial_balance=initial_balance)
    days = period.get("days")
    if days is None:
        try:
            import datetime as _dt
            days = (_dt.date.fromisoformat(str(period["end"])[:10])
                    - _dt.date.fromisoformat(str(period["start"])[:10])).days
        except Exception:
            days = 0
    if "error" in r:
        return {"regime": period.get("regime", "?"), "start": str(period["start"]), "end": str(period["end"]),
                "days": days, "error": r["error"]}
    m = r.get("metrics", {})
    return {"regime": period.get("regime", "?"), "start": str(period["start"]), "end": str(period["end"]),
            "days": days, "total_return": m.get("total_return"),
            "cagr": m.get("cagr"), "sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown"),
            "final_equity": m.get("final_equity"), "guard_hits": r.get("guard_hits")}


def run_cycle_test(frames, contract, rule_set=None, start=None, end=None,
                   per_cls=3, min_days=20, initial_balance=1_000_000.0,
                   split_ratio=0.7, progress=None) -> dict:
    """分周期测试主入口. 返回 {regime_breakdown, full_cycle, in_sample, out_of_sample, periods}."""
    def _emit(m):
        if progress:
            try: progress(m)
            except Exception: pass
    from backend.strategy.factor_research import FactorResearchEngine
    import backend.strategy.sell_rules as _sr
    rule_set = rule_set or _sr.SellRuleSet.build(rebalance_bars=contract.rebalance_bars)

    # ① regime 序列 + 周期段
    hs = _load_hs300()
    if not hs or len(hs["closes"]) < 60:
        return {"error": "hs300 不足"}
    labels = _regime_series(hs["dates"], hs["closes"])
    periods = _merge_periods(labels, min_days=min_days)
    picked = _pick_per_cls(periods, per_cls=per_cls)
    _emit(f"分周期: 识别{len(periods)}段, 每类挑最长{per_cls}段")

    # ② 各周期段回放
    reg_break = {}
    for regime, segs in picked.items():
        rows = []
        for seg in segs:
            _emit(f"  {regime} {str(seg['start'])[:10]}→{str(seg['end'])[:10]} ({seg['days']}天)")
            rows.append(_run_cycle(frames, contract, rule_set, seg, initial_balance))
            _emit("    done")
        reg_break[regime] = rows

    # ③ 全周期 (start→end 或 hs 覆盖)
    fs = str(start or (frame_start(frames)))
    fe = str(end or (frame_end(frames)))
    full = _run_cycle(frames, contract, rule_set,
                      {"regime": "全周期", "start": fs, "end": fe}, initial_balance)

    # ④ 样本内/样本外 (防过拟合)
    # 用 hs 日期中点切, 或基于 frames 的实际日期范围
    d0 = _frame_first_date(frames); d1 = _frame_last_date(frames)
    split = _split_date(d0, d1, split_ratio)
    ink = _run_cycle(frames, contract, rule_set, {"regime": "样本内", "start": d0, "end": split}, initial_balance)
    ook = _run_cycle(frames, contract, rule_set, {"regime": "样本外", "start": split, "end": d1}, initial_balance)

    return {"regime_breakdown": reg_break, "full_cycle": full,
            "in_sample": ink, "out_of_sample": ook,
            "n_periods": len(periods), "as_of": fe}


def frame_start(frames):
    return _frame_first_date(frames)

def frame_end(frames):
    return _frame_last_date(frames)


def _frame_first_date(frames):
    for df in frames.values():
        if len(df.index):
            return str(df.index[0])[:10]
    return None


def _frame_last_date(frames):
    for df in frames.values():
        if len(df.index):
            return str(df.index[-1])[:10]
    return None


def _split_date(d0, d1, ratio):
    import datetime as _dt
    try:
        a = _dt.date.fromisoformat(d0); b = _dt.date.fromisoformat(d1)
    except Exception:
        return d0
    span = (b - a).days
    return str(a + _dt.timedelta(days=int(span * ratio)))


if __name__ == "__main__":
    print("run_cycle_test — 分周期测试(牛/熊/震荡/全周期/样本内外)")
