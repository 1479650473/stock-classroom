# -*- coding: utf-8 -*-
"""交易员战绩 —— 让 AI 看得见自己的历史成绩，用于自我提升。

覆盖的问题：模型只能"凭印象"说自己学到了什么，看不到自己的真实胜率/回撤/连亏。
本模块从决策记录里的 executions（带交易日）+ 账户净值序列算出客观战绩，注入每日上下文：

    累计收益 / 最大回撤 / 日胜率 / 已平仓笔数 / 胜率 / 盈亏比 / 平均盈亏 /
    平均持有天数 / 当前连亏或连盈 / 最近 N 笔已平仓明细 / 持仓浮动盈亏

实现上用 FIFO 把同一只股票的买入与卖出配对成一次完整交易（回放与实盘通用），
as_of 非空时只用该日（含）之前的数据，保证回放无前视。
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Optional

from ..api.paths import SIM_DB
from . import store


def _day_gap(d1: str, d2: str) -> int:
    try:
        a = date.fromisoformat(str(d1)[:10])
        b = date.fromisoformat(str(d2)[:10])
        return max(0, (b - a).days)
    except Exception:
        return 0


def _closed_trades(decisions: list) -> list:
    """把买卖流水按 FIFO 配对成完整交易（同一只股票先进先出）。"""
    chrono = sorted(decisions, key=lambda d: (d.get("trade_date") or "", d.get("id") or 0))
    lots: dict = {}
    closed: list = []
    for d in chrono:
        dstr = d.get("trade_date") or ""
        for e in (d.get("executions") or []):
            if not isinstance(e, dict) or not e.get("ok"):
                continue
            side = str(e.get("side") or "").lower()
            code = str(e.get("code") or "")
            qty = int(e.get("qty") or 0)
            px = float(e.get("price") or 0)
            name = e.get("name") or code
            fee = float(e.get("commission") or 0) + float(e.get("stamp_tax") or 0)
            if qty <= 0 or px <= 0 or not code:
                continue
            if side == "buy":
                lots.setdefault(code, []).append({"qty": qty, "price": px, "date": dstr, "name": name})
                continue
            if side != "sell":
                continue
            left = qty
            while left > 0 and lots.get(code):
                lot = lots[code][0]
                take = min(left, lot["qty"])
                gross = (px - lot["price"]) * take
                pnl = gross - fee * (take / qty if qty else 1)
                cost = lot["price"] * take
                closed.append({
                    "code": code, "name": name,
                    "buy_date": lot["date"], "sell_date": dstr,
                    "hold_days": _day_gap(lot["date"], dstr),
                    "qty": take,
                    "buy_price": round(lot["price"], 3), "sell_price": round(px, 3),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(gross / cost * 100, 2) if cost else 0.0,
                })
                lot["qty"] -= take
                left -= take
                if lot["qty"] <= 0:
                    lots[code].pop(0)
    return closed


def _nav_series(account_id: int, as_of: Optional[str]) -> list:
    try:
        con = sqlite3.connect(SIM_DB)
        con.row_factory = sqlite3.Row
        sql = "SELECT date, nav, total_assets FROM account_nav WHERE account_id=?"
        args: list = [account_id]
        if as_of:
            sql += " AND date<=?"
            args.append(as_of)
        sql += " ORDER BY date"
        rows = [dict(r) for r in con.execute(sql, args).fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def _open_positions(account_id: int) -> list:
    try:
        con = sqlite3.connect(SIM_DB)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT code,name,qty,cost_price,current_price,float_pnl FROM positions "
            "WHERE account_id=? AND qty>0", (account_id,)).fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def performance_block(profile_id: int, account_id: int,
                      as_of: Optional[str] = None,
                      history_limit: int = 400, recent: int = 8) -> dict:
    """算该交易员截至 as_of 的客观战绩。"""
    decisions = store.list_decisions(int(profile_id), limit=history_limit)
    if as_of:
        decisions = [d for d in decisions if (d.get("trade_date") or "") <= as_of]
    done = [d for d in decisions if d.get("status") in ("done", "error")]

    closed = _closed_trades(done)
    navs = _nav_series(int(account_id), as_of)
    pos = _open_positions(int(account_id))

    out: dict = {
        "as_of": as_of or "最新",
        "decision_days": len([d for d in done if d.get("trade_date")]),
        "trading": {},
        "nav": {},
        "open_positions": [],
        "recent_closed": [],
        "review_prompt": "",
    }

    # ── 净值与回撤 ──
    if navs:
        vals = [float(r["nav"] or 1) for r in navs]
        peak = vals[0]
        mdd = 0.0
        for v in vals:
            peak = max(peak, v)
            if peak > 0:
                mdd = min(mdd, v / peak - 1)
        rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1]]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r < 0]
        out["nav"] = {
            "start": round(vals[0], 5), "last": round(vals[-1], 5),
            "cum_return_pct": round((vals[-1] / vals[0] - 1) * 100, 2) if vals[0] else 0.0,
            "max_drawdown_pct": round(mdd * 100, 2),
            "best_day_pct": round(max(rets) * 100, 2) if rets else 0.0,
            "worst_day_pct": round(min(rets) * 100, 2) if rets else 0.0,
            "up_days": len(wins), "down_days": len(losses),
            "day_win_rate_pct": round(len(wins) / len(rets) * 100, 1) if rets else 0.0,
            "last_5_days_nav": [round(v, 5) for v in vals[-5:]],
        }

    # ── 已平仓交易 ──
    if closed:
        win = [t for t in closed if t["pnl"] > 0]
        lose = [t for t in closed if t["pnl"] <= 0]
        avg_win = sum(t["pnl"] for t in win) / len(win) if win else 0.0
        avg_lose = sum(t["pnl"] for t in lose) / len(lose) if lose else 0.0
        # 尾部连亏/连盈
        streak, sign = 0, 0
        for t in reversed(closed):
            s = 1 if t["pnl"] > 0 else -1
            if sign == 0 or s == sign:
                streak += 1
                sign = s
            else:
                break
        out["trading"] = {
            "closed_count": len(closed),
            "win_count": len(win), "lose_count": len(lose),
            "win_rate_pct": round(len(win) / len(closed) * 100, 1),
            "total_realized_pnl": round(sum(t["pnl"] for t in closed), 2),
            "avg_win": round(avg_win, 2), "avg_lose": round(avg_lose, 2),
            "profit_loss_ratio": round(abs(avg_win / avg_lose), 2) if avg_lose else None,
            "avg_hold_days": round(sum(t["hold_days"] for t in closed) / len(closed), 1),
            "worst_trade": min(closed, key=lambda t: t["pnl"]),
            "best_trade": max(closed, key=lambda t: t["pnl"]),
            "current_streak": {"type": "盈" if sign > 0 else "亏", "count": streak},
        }
        out["recent_closed"] = list(reversed(closed[-int(recent or 8):]))

    # ── 当前持仓浮盈 ──
    if pos:
        out["open_positions"] = [{
            "code": p["code"], "name": p["name"], "qty": p["qty"],
            "cost_price": round(float(p["cost_price"] or 0), 3),
            "price": round(float(p["current_price"] or 0), 3),
            "float_pnl": round(float(p["float_pnl"] or 0), 2),
            "float_pnl_pct": round((float(p["current_price"] or 0) / float(p["cost_price"]) - 1) * 100, 2)
            if p["cost_price"] else 0.0,
        } for p in pos]

    # ── 给模型看的一句话自省提示 ──
    t = out["trading"] or {}
    tip = []
    if t:
        tip.append(f"已平仓 {t['closed_count']} 笔，胜率 {t['win_rate_pct']}%，"
                   f"平均盈利 {t['avg_win']:.0f} / 平均亏损 {t['avg_lose']:.0f}，"
                   f"平均持有 {t['avg_hold_days']} 天，当前{t['current_streak']['type']}势 {t['current_streak']['count']} 笔")
    if out["nav"]:
        tip.append(f"累计 {out['nav']['cum_return_pct']}%，最大回撤 {out['nav']['max_drawdown_pct']}%")
    if tip:
        out["review_prompt"] = "；".join(tip) + "。请据此判断自己的方法是否真的有效，而不是凭印象。"
    return out


REVIEW_SYS = (
    "你是这个账户交易员的复盘教练。下面是它自己的真实战绩数据和最近若干天的决策原文。"
    "请只基于数据说话，不要客套，指出哪些判断被盈亏证伪、哪些有效。"
    "直接输出 JSON，不要推理过程，不要 markdown 代码块，越短越好："
    '{"self_critique":"不超过150字，指出具体错误、错在哪一天、被什么数据证伪",'
    '"lessons":["最多3条，每条不超过40字，针对具体行为"],'
    '"style":"不超过60字，更新后的自我风格认知"}'
)


def loads_json(text: str):
    """从 LLM 回复里抽出 JSON（允许包在 ``` 里或前后有废话）。"""
    s = str(text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s
        s = s.split("\n", 1)[1] if "\n" in s else s
    try:
        return json.loads(s)
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(s[i:j + 1])
        except Exception:
            return None
    return None


def _salvage_field(raw: str, key: str) -> str:
    """从被截断的 JSON 里抢救某个字符串字段（模型输出被 max_tokens 截断时）。"""
    m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)' % re.escape(key), str(raw or ""))
    if not m:
        return ""
    try:
        return json.loads('"' + m.group(1) + '"')
    except Exception:
        return m.group(1)


def review_trader(llm, perf: dict, decisions: list, max_tokens: int = 2600) -> dict:
    """强制自省：把自己的战绩 + 最近决策原文交给模型，产出教训与风格。

    不写库，由调用方决定落库与推送。返回 {self_critique, lessons, style} 或 {error}。
    """
    lines = ["【我的真实战绩】", performance_summary_text(perf), "", "【最近逐日决策与操作】"]
    for d in decisions:
        acts = "、".join(
            f"{o.get('side')}{o.get('name') or o.get('code')}x{o.get('qty')}@{o.get('price')}"
            f"({'成交' if o.get('ok') else '失败'})" for o in (d.get("executions") or [])) or "无操作"
        lines.append(f"{d.get('trade_date')} 净值 {d.get('nav_after')} | {acts}")
        lines.append(f"  思考：{(d.get('thinking') or '')[:400]}")
        lines.append(f"  复盘：{(d.get('reflection') or '')[:200]}")
    try:
        raw = llm.complete(REVIEW_SYS, "\n".join(lines), max_tokens=max_tokens, temperature=0.3)
    except Exception as e:
        return {"error": f"自省调用失败：{e}"}
    data = loads_json(raw)
    if not isinstance(data, dict):
        data = {}
    crit = str(data.get("self_critique") or "").strip()
    lessons = [str(x)[:400] for x in (data.get("lessons") or []) if str(x).strip()][:5]
    style = str(data.get("style") or "").strip()
    if not (crit or lessons or style):
        # 模型输出被截断或没给 JSON：从原文里救回自评文本，至少不丢这次自省
        crit = (_salvage_field(raw, "self_critique") or str(raw or "").strip())[:1200]
    if not (crit or lessons or style):
        return {"error": "自省无内容（模型返回空）"}
    return {"self_critique": crit[:1500], "lessons": lessons, "style": style[:800]}


def performance_summary_text(perf: dict) -> str:
    """压成一段纯文本，供复盘 LLM 调用使用。"""
    lines = [f"截至 {perf.get('as_of')}，决策 {perf.get('decision_days')} 个交易日"]
    nav = perf.get("nav") or {}
    if nav:
        lines.append(f"净值 {nav.get('start')} → {nav.get('last')}（{nav.get('cum_return_pct')}%），"
                     f"最大回撤 {nav.get('max_drawdown_pct')}%，日胜率 {nav.get('day_win_rate_pct')}%")
    t = perf.get("trading") or {}
    if t:
        lines.append(f"已平仓 {t.get('closed_count')} 笔：胜率 {t.get('win_rate_pct')}%，"
                     f"盈亏比 {t.get('profit_loss_ratio')}，平均盈利 {t.get('avg_win')}，"
                     f"平均亏损 {t.get('avg_lose')}，平均持有 {t.get('avg_hold_days')} 天，"
                     f"当前{t.get('current_streak', {}).get('type')}势 {t.get('current_streak', {}).get('count')} 笔")
    for tr in perf.get("recent_closed") or []:
        lines.append(f"  {tr['sell_date']} 平仓 {tr['name']}({tr['code']}) "
                     f"{tr['buy_price']}→{tr['sell_price']} {tr['pnl']:+.0f} 元 ({tr['pnl_pct']:+.1f}%) 持有{tr['hold_days']}天")
    for p in perf.get("open_positions") or []:
        lines.append(f"  持仓 {p['name']}({p['code']}) {p['qty']}股 成本{p['cost_price']} 现价{p['price']} "
                     f"浮动{p['float_pnl']:+.0f}元 ({p['float_pnl_pct']:+.1f}%)")
    return "\n".join(lines)
