# -*- coding: utf-8 -*-
"""每日方向预测：产出（submit_decision.outlook）+ 落库 + 自动打分。

目的：把"模型自评"变成"可对账的客观记录"——每天让操盘手给出**次日净值方向 + 置信度**，
次日用真实净值结算，长期统计命中率与 Brier 分数。这比单看总收益更能区分运气与能力
（借鉴 PA_Agent 的"未来走势预期"，但我们把它做成可打分的闭环）。
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date
from typing import Optional

from ..api.paths import SIM_DB
from . import store

DIRECTIONS = ("up", "down", "flat", "abstain")
CN = {"up": "看涨", "down": "看跌", "flat": "看平", "abstain": "弃权（看不清）"}
FLAT_BAND_PCT = 0.3          # |涨跌| <= 0.3% 视为"平"


def normalize_outlook(raw) -> dict:
    """规范化模型给出的预测（容忍字符串/缺字段）。返回 {} 表示无效。"""
    if not isinstance(raw, dict):
        return {}
    d = str(raw.get("direction") or raw.get("方向") or "").strip().lower()
    alias = {"看涨": "up", "涨": "up", "up": "up", "bull": "up", "多": "up",
             "看跌": "down", "跌": "down", "down": "down", "bear": "down", "空": "down",
             "看平": "flat", "平": "flat", "flat": "flat", "sideways": "flat", "震荡": "flat",
             # 弃权（借鉴 Laya 的 noul）：宁可不表态，也不要被迫三选一污染校准数据
             "弃权": "abstain", "看不清": "abstain", "无信号": "abstain", "noul": "abstain",
             "abstain": "abstain", "不确定": "abstain", "无观点": "abstain"}
    d = alias.get(d, d)
    if d not in DIRECTIONS:
        return {}
    try:
        conf = float(raw.get("confidence", raw.get("置信度", 0)) or 0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(100.0, conf))
    if d == "abstain":
        # 弃权不需要置信度，但要有理由
        return {"direction": "abstain", "confidence": conf,
                "reason": str(raw.get("reason") or raw.get("依据") or "").strip()[:300],
                "target": str(raw.get("target") or "").strip()[:40]}
    reason = str(raw.get("reason") or raw.get("依据") or "").strip()[:300]
    target = str(raw.get("target") or raw.get("关注") or "").strip()[:40]
    return {"direction": d, "confidence": conf, "reason": reason, "target": target}


# ───────────────────────── 打分 ─────────────────────────

def _nav_series(account_id: int) -> dict:
    try:
        con = sqlite3.connect(str(SIM_DB))
        rows = con.execute("SELECT date, nav FROM account_nav WHERE account_id=? ORDER BY date",
                           (int(account_id),)).fetchall()
        con.close()
        return {str(d)[:10]: float(v) for d, v in rows if v}
    except Exception:
        return {}


def _cmp(a: str, b: str) -> int:
    return (str(a) > str(b)) - (str(a) < str(b))


def score_decision(profile_id: int, trade_date: str) -> Optional[dict]:
    """给某天的预测打分（需要有次一交易日的净值）。返回打分结果，未就绪/无预测返回 None。"""
    prof = store.get_profile(int(profile_id))
    if not prof:
        return None
    dec = store.get_decision(int(profile_id), str(trade_date)[:10]) or {}
    raw_outlook = dec.get("outlook")
    outlook = normalize_outlook(raw_outlook) if isinstance(raw_outlook, dict) else _load_json(raw_outlook)
    if not outlook:
        return None
    nav = _nav_series(int(prof["account_id"]))
    base = nav.get(str(trade_date)[:10])
    if not base:
        return None
    nxt = sorted([d for d in nav if _cmp(d, trade_date) > 0])
    if not nxt:
        return None                      # 次日净值还没结算
    next_day = nxt[0]
    if outlook.get("direction") == "abstain":
        # 弃权：只记"当时确实看不清"，不计命中/不参与校准（否则等于白拿一条样本）
        return {"as_of": next_day, "abstained": True, "scored_at": date.today().isoformat(),
                "note": "弃权日：不计命中，也不计入校准统计"}
    actual_pct = (nav[next_day] / base - 1) * 100 if base else 0.0
    if abs(actual_pct) <= FLAT_BAND_PCT:
        actual = "flat"
    else:
        actual = "up" if actual_pct > 0 else "down"
    hit = actual == outlook["direction"]
    conf = float(outlook.get("confidence") or 0) / 100.0
    # Brier：多分类按目标类 1/0 计
    brier = (conf - (1.0 if hit else 0.0)) ** 2
    return {"as_of": next_day, "actual": actual, "actual_pct": round(actual_pct, 3),
            "hit": bool(hit), "confidence": outlook["confidence"], "brier": round(brier, 4),
            "predicted": outlook["direction"], "scored_at": date.today().isoformat()}


def score_pending(profile_id: Optional[int] = None, limit: int = 120) -> int:
    """扫描未打分的预测并补分（每日流程/回放结束时调用）。返回补分条数。"""
    try:
        con = sqlite3.connect(str(store.DB_PATH))
        rows = con.execute(
            "SELECT profile_id, trade_date, outlook, outlook_score FROM trader_decision "
            "WHERE outlook IS NOT NULL AND outlook != '' AND outlook != '{}' "
            "ORDER BY trade_date DESC LIMIT ?", (int(limit),)).fetchall()
        con.close()
    except Exception:
        return 0
    done = 0
    for pid, tdate, outlook_raw, score_raw in rows:
        if profile_id and int(pid) != int(profile_id):
            continue
        if score_raw and str(score_raw) not in ("", "{}"):
            continue
        res = score_decision(int(pid), str(tdate))
        if not res:
            continue
        try:
            store.upsert_decision(int(pid), str(tdate), outlook_score=res)
            done += 1
        except Exception:
            pass
    return done


def _load_json(raw):
    try:
        v = json.loads(raw or "{}")
        return normalize_outlook(v) if isinstance(v, dict) else {}
    except Exception:
        return {}


# ───────────────────────── 统计（校准度） ─────────────────────────

def stats(profile_id: int, days: int = 60) -> dict:
    """命中率 / 按置信度分桶 / Brier 分数。样本少时明确标注。"""
    try:
        con = sqlite3.connect(str(store.DB_PATH))
        rows = con.execute(
            "SELECT trade_date, outlook, outlook_score FROM trader_decision "
            "WHERE profile_id=? AND outlook_score IS NOT NULL AND outlook_score != '' "
            "AND outlook_score != '{}' ORDER BY trade_date DESC LIMIT ?",
            (int(profile_id), int(days))).fetchall()
        con.close()
    except Exception:
        rows = []
    scored, abstained = [], 0
    for tdate, o_raw, s_raw in rows:
        o = _load_json(o_raw)
        try:
            s = json.loads(s_raw or "{}")
        except Exception:
            s = None
        if s and s.get("abstained"):
            abstained += 1
            continue
        if o and s:
            scored.append({"date": str(tdate)[:10], **s, "reason": o.get("reason", ""),
                           "target": o.get("target", "")})
    n = len(scored)
    hits = sum(1 for x in scored if x.get("hit"))
    brier = sum(float(x.get("brier") or 0) for x in scored) / n if n else None
    buckets = []
    for lo, hi, label in ((0, 55, "≈50% 随口"), (55, 70, "55-70 有点感觉"),
                          (70, 85, "70-85 比较确定"), (85, 101, "85+ 非常确定")):
        sub = [x for x in scored if lo <= float(x.get("confidence") or 0) < hi]
        if sub:
            buckets.append({"label": label, "n": len(sub),
                            "hit_rate": round(sum(1 for x in sub if x.get("hit")) / len(sub) * 100, 1),
                            "avg_conf": round(sum(float(x.get("confidence") or 0) for x in sub) / len(sub), 1)})
    by_dir = []
    for d in DIRECTIONS:
        sub = [x for x in scored if x.get("predicted") == d]
        if sub:
            by_dir.append({"direction": d, "label": CN[d], "n": len(sub),
                           "hit_rate": round(sum(1 for x in sub if x.get("hit")) / len(sub) * 100, 1)})
    # 方向性命中率（排除"看平"）：全现金账户天天预测"平"会白拿命中率，这个口径更诚实
    dir_sub = [x for x in scored if x.get("predicted") in ("up", "down")]
    flat_sub = [x for x in scored if x.get("predicted") == "flat"]
    return {"n": n, "abstained": abstained,
            "abstain_rate": round(abstained / (n + abstained) * 100, 1) if (n + abstained) else None,
            "hit_rate": round(hits / n * 100, 1) if n else None,
            "brier": round(brier, 4) if brier is not None else None,
            "baseline_hit": 33.3, "recent": scored[:20], "buckets": buckets, "by_direction": by_dir,
            "n_directional": len(dir_sub),
            "hit_rate_directional": round(sum(1 for x in dir_sub if x.get("hit")) / len(dir_sub) * 100, 1)
            if dir_sub else None,
            "n_flat": len(flat_sub),
            "hit_rate_flat": round(sum(1 for x in flat_sub if x.get("hit")) / len(flat_sub) * 100, 1)
            if flat_sub else None,
            "note": "三分类（涨/跌/平，±0.3% 视为平）随机基线 ≈33%；Brier 越低越好（0=完美，"
                    ">0.66 比乱猜更差）。**看方向性命中率**（排除看平）更有意义：空仓时天天预测"
                    "「平」会让总命中率虚高。样本 <20 条时不要下结论。"}
