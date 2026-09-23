# -*- coding: utf-8 -*-
"""组合纸面盘：把「固定因子组合」的回测结论变成**前瞻记录**（B 项）。

为什么需要它：所有组合结论（K=20/H=10 净 +5%/年等）都是回测。纸面盘每天按同一套规则
真实地"往前跑"，积累无法回看、无法调参的记录 —— 这是唯一能验证结论的办法，也是审计依据。

策略（与 `data/experiments/portfolio_cost_grid.json` 的实证口径一致）：
    · 域：流动性排名 601~1800 的中盘域（as-of 2018-01-01 冻结池，避免选择偏误）
    · 选股：固定因子组合 -RET1 / -RET5 / -HIGH60_GAP / -LOG_AMT20 等权 rank（composite.py 同口径）
    · 持仓：K=20 只、持有 H=10 个交易日**分仓制**（每天新开 1/H 的仓位、同时卖掉 10 日前那仓）
      → 每天换手约 1/H，成本按**单边 10bp**扣
    · 成交价：信号日收盘（**近似**；真实下单在次日开盘，差异记为执行口径风险）
    · 状态：`data/paper_portfolio.json`（持仓/分仓/净值历史），同日幂等

用法：
    python -m backend.alpha.paper_portfolio            # 按最新可用交易日跑一次
    python -m backend.alpha.paper_portfolio --status    # 只看状态
    python -m backend.alpha.paper_portfolio --reset     # 重置（清空记录重新开始）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from typing import Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (ROOT, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ..api.paths import DATA_DIR, KLINE_DB                 # noqa: E402
from . import panel as P                                    # noqa: E402

STATE_PATH = os.path.join(str(DATA_DIR), "paper_portfolio.json")

DEFAULTS = {
    "name": "组合纸面盘（K=20 / H=10 / 中盘域）",
    "initial_capital": 1_000_000,      # 名义本金 100 万
    "initial_nav": 1.0,
    "pool_skip": 600,
    "pool_take": 1200,
    "K": 20,
    "H": 10,
    "cost_one_way": 0.001,          # 单边 10bp
    "weights": "默认（-RET1/-RET5/-HIGH60_GAP/-LOG_AMT20 等权 rank）",
}


# ───────────────────────── 状态 ─────────────────────────

def _load_state() -> Optional[dict]:
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_state(s: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def _new_state(as_of: str) -> dict:
    return {"config": dict(DEFAULTS), "cash": float(DEFAULTS["initial_capital"]),
            "tranches": [], "holdings": {}, "nav_history": [], "created_at": as_of,
            "last_date": None, "log": []}


# ───────────────────────── 行情 ─────────────────────────

def _trading_dates(end: str, n: int = 400) -> List[str]:
    con = sqlite3.connect(str(KLINE_DB))
    try:
        rows = con.execute("SELECT DISTINCT date FROM kline_daily WHERE date<=? "
                           "ORDER BY date DESC LIMIT ?", (end.replace("-", ""), n)).fetchall()
    finally:
        con.close()
    return sorted(str(r[0]) for r in rows)


def _closes(codes: List[str], date: str) -> Dict[str, float]:
    con = sqlite3.connect(str(KLINE_DB))
    try:
        ph = ",".join("?" for _ in codes)
        rows = con.execute(f"SELECT code, close FROM kline_daily WHERE date=? AND code IN ({ph})",
                           [date.replace("-", "")] + list(codes)).fetchall()
    finally:
        con.close()
    return {str(c): float(v or 0) for c, v in rows if v}


# ───────────────────────── 选股 ─────────────────────────

def _score(codes: List[str], as_of: str) -> Dict[str, float]:
    """固定因子组合的截面等权 rank 得分（与 composite.py / 回测同口径）。"""
    import numpy as np
    start = _shift(as_of, 200)
    pan = P.load_panel(codes, _fmt(start), _fmt(as_of))
    dates: List[str] = pan["dates"]                        # type: ignore[assignment]
    if not dates:
        return {}
    feats = P.build_features(pan["fields"])                # type: ignore[arg-type]
    last = len(dates) - 1
    legs = []
    for nm, sign in (("RET1", -1.0), ("RET5", -1.0), ("HIGH60_GAP", -1.0), ("LOG_AMT20", -1.0)):
        arr = feats.get(nm)
        if arr is None:
            continue
        v = sign * np.asarray(arr, dtype=float)[:, last]
        ok = np.isfinite(v)
        if ok.sum() < 2:
            continue
        r = np.full_like(v, np.nan)
        r[ok] = np.argsort(np.argsort(v[ok])) / (ok.sum() - 1)
        legs.append(r)
    if not legs:
        return {}
    score = np.nanmean(np.vstack(legs), axis=0)
    out = {}
    for i, c in enumerate(pan["codes"]):                   # type: ignore[attr-defined]
        s = score[i]
        if s == s:
            out[str(c)] = float(s)
    return out


def _shift(date8: str, back_days: int) -> str:
    d = dt.datetime.strptime(_fmt(date8), "%Y-%m-%d") - dt.timedelta(days=int(back_days))
    return d.strftime("%Y%m%d")


def _fmt(d: str) -> str:
    d = str(d).replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


# ───────────────────────── 主流程 ─────────────────────────

def run_once(as_of: Optional[str] = None, verbose: bool = True) -> dict:
    """按 as_of（默认最新交易日）跑一次：卖到期分仓 → 开新分仓 → 记净值。同日幂等。"""
    if as_of:
        d8 = str(as_of).replace("-", "")[:8]
    else:
        con = sqlite3.connect(str(KLINE_DB))
        try:
            d8 = str(con.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0])
        finally:
            con.close()
    d8 = str(d8).replace("-", "")[:8]
    state = _load_state() or _new_state(d8)
    cfg = state["config"]
    if state.get("last_date") == d8:
        if verbose:
            print(f"{d8} 已跑过（幂等跳过）")
        return state

    # 交易日序列（含 d8）→ 卖出到期分仓 & 判断是否交易日
    cal = _trading_dates(d8, 400)
    if not cal or cal[-1] != d8:
        if verbose:
            print(f"{d8} 不是（或有数据缺失的）交易日，跳过")
        return state
    idx = {d: i for i, d in enumerate(cal)}
    K, H, c1 = int(cfg["K"]), int(cfg["H"]), float(cfg["cost_one_way"])
    per_tranche = max(1, round(K / H))

    # ① 卖到期分仓（buy_date 在 H 个交易日前）
    keep, sold = [], []
    for tr in state["tranches"]:
        bi = idx.get(tr["buy_date"])
        if bi is not None and idx[d8] - bi >= H:
            sold.append(tr)
        else:
            keep.append(tr)
    state["tranches"] = keep

    # ② 计算当前持仓市值与净值（用今日收盘）
    held_codes = sorted({h["code"] for tr in keep for h in tr["names"]})
    px_today = _closes(held_codes, d8) if held_codes else {}
    mv = 0.0
    for tr in keep:
        for h in tr["names"]:
            p = px_today.get(h["code"]) or h["price"]
            mv += h["qty"] * p
    cap = float(cfg.get("initial_capital") or 1_000_000)
    nav = (state["cash"] + mv) / cap

    # ③ 卖出到期的：按今日收盘成交，扣成本
    sell_proceeds = 0.0
    for tr in sold:
        for h in tr["names"]:
            p = px_today.get(h["code"]) or h["price"]
            gross = h["qty"] * p
            sell_proceeds += gross * (1 - c1)
    state["cash"] += sell_proceeds

    # ④ 开新分仓：用「总净值 / H」的金额买组合 Top-K 里当前未持有的名字
    total = state["cash"] + mv - sell_proceeds * 0  # mv 已含卖出前
    total = state["cash"] + mv
    budget = total / H
    held_now = {h["code"] for tr in state["tranches"] for h in tr["names"]}
    uni = P.pick_universe(limit=int(cfg["pool_take"]), skip=int(cfg["pool_skip"]),
                          as_of=_fmt(d8))
    sc = _score(uni, d8)
    picks = [c for c in sorted(sc, key=lambda x: -sc[x]) if c not in held_now][:per_tranche]
    px_buy = _closes(picks, d8) if picks else {}
    names = []
    for c in picks:
        p = px_buy.get(c) or 0
        if p <= 0:
            continue
        amt = budget / max(1, len(picks))
        qty = int(amt / p / 100) * 100          # 100 股整数倍
        if qty <= 0:
            continue
        cost = qty * p * (1 + c1)
        if cost > state["cash"]:
            qty = int(state["cash"] / (p * (1 + c1)) / 100) * 100
            cost = qty * p * (1 + c1)
        if qty <= 0:
            continue
        state["cash"] -= cost
        names.append({"code": c, "name": (P.load_panel([c], _fmt(_shift(d8, 30)), _fmt(d8)).get("names") or {}).get(c, ""),
                      "qty": qty, "price": round(p, 3), "score": round(sc[c], 4)})
    if names:
        state["tranches"].append({"buy_date": d8, "sell_due": H, "budget": round(budget, 2),
                                  "names": names})

    # ⑤ 净值与历史
    held_codes2 = sorted({h["code"] for tr in state["tranches"] for h in tr["names"]})
    px2 = _closes(held_codes2, d8) if held_codes2 else {}
    mv2 = sum((px2.get(h["code"]) or h["price"]) * h["qty"]
              for tr in state["tranches"] for h in tr["names"])
    nav2 = (state["cash"] + mv2) / cap
    state["nav_history"].append({"date": d8, "nav": round(nav2, 5),
                                 "cash": round(state["cash"], 2), "market_value": round(mv2, 2),
                                 "positions": len(held_codes2), "tranches": len(state["tranches"]),
                                 "opened": len(names), "closed": len(sold)})
    state["holdings"] = {}
    for tr in state["tranches"]:
        for h in tr["names"]:
            state["holdings"].setdefault(h["code"], {"name": h["name"], "qty": 0, "buy_dates": []})
            state["holdings"][h["code"]]["qty"] += h["qty"]
            state["holdings"][h["code"]]["buy_dates"].append(tr["buy_date"])
    state["last_date"] = d8
    state["log"].append({"date": d8, "opened": [n["code"] for n in names],
                         "closed": [h["code"] for tr in sold for h in tr["names"]],
                         "nav": round(nav2, 5)})
    state["log"] = state["log"][-400:]
    _save_state(state)
    if verbose:
        print(f"{d8}: 净值 {nav2:.4f}｜开仓 {len(names)} 只（{' '.join(n['code'] for n in names) or '—'}）"
              f"｜平仓 {len(sold)} 个分仓｜持仓 {len(held_codes2)} 只｜现金 {state['cash']:.0f}")
    return state


def status() -> dict:
    s = _load_state()
    if not s:
        return {"started": False, "hint": "还没跑过：python -m backend.alpha.paper_portfolio"}
    hist = s.get("nav_history") or []
    nav = hist[-1]["nav"] if hist else 1.0
    out = {"started": True, "config": s["config"], "last_date": s.get("last_date"),
           "nav": nav, "total_return_pct": round((nav - 1) * 100, 2),
           "days": len(hist), "positions": len(s.get("holdings") or {}),
           "recent": hist[-10:], "created_at": s.get("created_at")}
    # 完整的净值历史 + 基准（沪深300，同起点归一）—— 给前端画曲线用
    try:
        dates = [h["date"] for h in hist]
        out["history"] = [{"date": h["date"], "nav": h["nav"],
                           "positions": h.get("positions"), "opened": h.get("opened"),
                           "closed": h.get("closed")} for h in hist]
        if dates:
            con = sqlite3.connect(str(KLINE_DB))
            try:
                # 取区间内全部指数收盘（指数可能比个股晚一天更新 → 前向填充）
                rows = con.execute(
                    "SELECT date, close FROM kline_daily WHERE code='sh000300' AND date<=? "
                    "AND date>=? ORDER BY date",
                    (dates[-1], _shift(dates[0], 20))).fetchall()
            finally:
                con.close()
            px_all = [(str(d), float(c)) for d, c in rows if c]
            px = {}
            k = 0
            cur = None
            for d in dates:
                while k < len(px_all) and px_all[k][0] <= d:
                    cur = px_all[k][1]
                    k += 1
                if cur:
                    px[d] = cur
            base = None
            bench = []
            for d in dates:
                v = px.get(d)
                if v is None:
                    bench.append(None)
                    continue
                if base is None:
                    base = v
                bench.append(round(v / base, 5))
            out["benchmark"] = {"code": "sh000300", "name": "沪深300", "nav": bench}
        # 持仓明细（带买入日）
        out["holdings"] = [{"code": c, **v} for c, v in (s.get("holdings") or {}).items()]
        out["log"] = (s.get("log") or [])[-20:]
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--date", default=None, help="指定交易日（默认最新）")
    a = ap.parse_args()
    if a.reset:
        if os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
            print("已重置（删除状态文件）")
        return
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return
    run_once(a.date)


if __name__ == "__main__":
    main()
