# -*- coding: utf-8 -*-
"""预测校准（借鉴 Laya 的 RLCD / temperature scaling 与它的"诚实局限"）。

为什么需要它：模型给的 confidence 只是**它自己的说法**，不是概率。Laya 的经验是：
  · 两个 checkpoint 出厂时都**过度自信**（ECE 0.466 / 0.314）；用一份留出数据拟合**温度**后
    降到 0.081 / 0.106 —— 校准是靠拟合出来的，不是训练出来的；
  · 更狠的一条：**当模型读不懂输入时，置信度不会报警**（高棉语准确率 0.000，平均置信度 0.952），
    所以"置信度门槛"救不了系统性问题 —— 输入校验必须放在模型之前。
我们的对应物：AI 操盘手每天给 `outlook={direction, confidence}`，我们已经在打分。
本模块把"它的置信度到底有没有意义"算清楚：

    ECE（期望校准误差）、可靠性曲线（分箱：声称 70% 实际命中多少）、
    温度拟合后的校准置信度、**区分度**（高置信与低置信的命中率有没有差）、
    以及**门槛建议**（到什么置信度才有边际；若置信度无区分度就直说别用）。

样本 < 20 条时明确标注不可下结论。
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Optional

from . import outlook as outlook_mod
from . import store

MIN_SAMPLES = 20        # 少于这个数不做结论（与 outlook.stats 的口径一致）


def _logit(p: float) -> float:
    p = min(0.999, max(0.001, float(p)))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _pairs(profile_id: int, days: int = 180) -> list:
    """取已打分的预测 → [(confidence 0~1, hit 0/1, trade_date)]，跳过弃权/看平无信号的日子。"""
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
    out = []
    for tdate, o_raw, s_raw in rows:
        try:
            o = json.loads(o_raw or "{}")
            s = json.loads(s_raw or "{}")
        except Exception:
            continue
        if not isinstance(o, dict) or not isinstance(s, dict):
            continue
        if s.get("abstained"):          # 弃权不计入校准（它本来就说"没信号"）
            continue
        try:
            conf = float(o.get("confidence") or 0) / 100.0
        except (TypeError, ValueError):
            continue
        if conf <= 0:
            continue
        out.append((conf, 1 if s.get("hit") else 0, str(tdate)[:10]))
    return out


def fit_temperature(pairs: list) -> dict:
    """一维逻辑回归（温度+偏置）：logit(p_cal) = a·logit(p) + b。返回 {"a","b","n"}。"""
    xs = [_logit(p) for p, _, _ in pairs]
    ys = [float(y) for _, y, _ in pairs]
    n = len(xs)
    if n == 0:
        return {"a": 1.0, "b": 0.0, "n": 0}
    a, b = 1.0, 0.0
    lr = 0.5
    for _ in range(400):                      # 梯度下降，够用且无需依赖
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            p = _sigmoid(a * x + b)
            err = p - y
            ga += err * x
            gb += err
        a -= lr * ga / n
        b -= lr * gb / n
    return {"a": round(a, 4), "b": round(b, 4), "n": n}


def calibrate(conf: float, params: Optional[dict] = None) -> float:
    p = min(0.999, max(0.001, float(conf)))
    if not params:
        return round(p, 4)
    return round(_sigmoid(float(params.get("a", 1.0)) * _logit(p) + float(params.get("b", 0.0))), 4)


def ece(pairs: list, params: Optional[dict] = None, bins: int = 5) -> Optional[float]:
    """期望校准误差：|平均声称 − 实际命中| 按样本量加权。"""
    if not pairs:
        return None
    buckets = [[] for _ in range(bins)]
    for p, y, _ in pairs:
        pc = calibrate(p, params) if params else p
        idx = min(bins - 1, int(pc * bins))
        buckets[idx].append((pc, y))
    total = len(pairs)
    err = 0.0
    for b in buckets:
        if not b:
            continue
        avg_p = sum(x[0] for x in b) / len(b)
        avg_y = sum(x[1] for x in b) / len(b)
        err += abs(avg_p - avg_y) * len(b) / total
    return round(err, 4)


def reliability(pairs: list, params: Optional[dict] = None, bins: int = 5) -> list:
    """可靠性曲线：每箱的"声称概率 / 实际命中率 / 样本量"（校准后）。"""
    out = [[] for _ in range(bins)]
    for p, y, _ in pairs:
        pc = calibrate(p, params) if params else p
        idx = min(bins - 1, int(pc * bins))
        out[idx].append((pc, y))
    rows = []
    for i, b in enumerate(out):
        if not b:
            continue
        rows.append({"bin": f"{i * 100 // bins}-{(i + 1) * 100 // bins}%",
                     "n": len(b),
                     "claimed": round(sum(x[0] for x in b) / len(b) * 100, 1),
                     "actual": round(sum(x[1] for x in b) / len(b) * 100, 1)})
    return rows


def discrimination(pairs: list) -> dict:
    """置信度有没有区分度：高置信组与低置信组的命中率之差。"""
    if len(pairs) < 4:
        return {"ok": False, "note": "样本不足"}
    s = sorted(pairs, key=lambda x: x[0])
    k = max(1, len(s) // 3)
    low, high = s[:k], s[-k:]
    lr = sum(y for _, y, _ in low) / len(low)
    hr = sum(y for _, y, _ in high) / len(high)
    return {"ok": True, "low_bin_hit": round(lr * 100, 1), "high_bin_hit": round(hr * 100, 1),
            "spread": round((hr - lr) * 100, 1),
            "note": ("置信度有区分度（高置信更准）" if hr - lr >= 0.15 else
                     "置信度区分度弱：别拿它当行动门槛" if hr - lr < 0.05 else "区分度一般")}


def log_loss(pairs: list, params: Optional[dict] = None) -> Optional[float]:
    if not pairs:
        return None
    eps = 1e-6
    tot = 0.0
    for p, y, _ in pairs:
        pc = calibrate(p, params) if params else p
        pc = min(1 - eps, max(eps, pc))
        tot += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
    return round(tot / len(pairs), 4)


def gate_suggestion(pairs: list, params: Optional[dict] = None) -> dict:
    """门槛建议：找出"校准后置信度 ≥ X"时历史命中率最高的、且样本足够的门槛。"""
    if len(pairs) < MIN_SAMPLES:
        return {"ok": False, "note": f"样本不足（n={len(pairs)}，建议 ≥{MIN_SAMPLES} 条再定门槛）"}
    best = None
    for thr in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8):
        sub = [(p, y) for p, y, _ in pairs if calibrate(p, params) >= thr]
        if len(sub) < 8:
            continue
        hit = sum(y for _, y in sub) / len(sub)
        cand = {"threshold": round(thr * 100), "n": len(sub), "hit_rate": round(hit * 100, 1)}
        if best is None or cand["hit_rate"] > best["hit_rate"]:
            best = cand
    if best is None:
        return {"ok": False, "note": "没有样本足够的门槛可建议"}
    # 与全体对比，判断门槛是否真的提升了命中率
    base = sum(y for _, y, _ in pairs) / len(pairs)
    best["baseline_hit"] = round(base * 100, 1)
    best["lift"] = round(best["hit_rate"] - base * 100, 1)
    best["note"] = ("该门槛下命中率显著高于整体，可作为'只在此时行动'的依据"
                    if best["lift"] >= 10 else
                    "门槛带来的提升有限（<10pp），不建议把置信度当硬门槛")
    return {"ok": True, **best}


def report(profile_id: int, days: int = 180) -> dict:
    """完整校准报告（给 API 与上下文用）。"""
    pairs = _pairs(profile_id, days)
    n = len(pairs)
    params = fit_temperature(pairs) if n >= MIN_SAMPLES else None
    out = {
        "n": n,
        "raw_ece": ece(pairs) if n else None,
        "calibrated_ece": ece(pairs, params) if (params and n) else None,
        "temperature": params,
        "log_loss": log_loss(pairs) if n else None,
        "log_loss_calibrated": log_loss(pairs, params) if (params and n) else None,
        "reliability": reliability(pairs, params) if n else [],
        "discrimination": discrimination(pairs) if n else {"ok": False, "note": "样本不足"},
        "gate": gate_suggestion(pairs, params) if n else {"ok": False, "note": "样本不足"},
        "note": ("置信度是模型自己的说法；本报告看它是否可信（ECE 越低越好，"
                 "校准后 ECE 明显低于原始 ECE 说明模型系统性过度自信）。"
                 "样本 <20 条时不要据此调整。" if n else "还没有已打分的预测。"),
    }
    return out
