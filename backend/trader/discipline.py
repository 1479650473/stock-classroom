# -*- coding: utf-8 -*-
"""交易纪律 —— 把自省结论变成交易系统强制执行的硬规则。

解决的问题：自省产出的教训如果只写进长期记忆，模型可以选择不照做，等于没有约束
（实测：模型写下「减速期禁新开仓」之后仍然在下跌途中追高分股）。本模块把这些结论
规范化为**可机器判定**的规则，落库 `trader_memory(kind='rule')`，并在两条路径上强制：

    ① 下单路径（tools.place_order / preview_order）—— 违规委托被系统直接拒绝并返回原因，
       模型只能按拒绝原因调整，与「资金不足 / T+1 违规」的处理方式一致（模拟券商风控）。
    ② 每日持仓保护（enforce_protection）—— 收盘后对未平仓持仓做兜底止损/移动止损，
       模型不卖的由系统卖（这正是「惠达卫浴扛到 -12% 才割」缺的那一层）。

两条原则：
  - **不可放宽**：规则只能让交易更保守（阈值更严、限制更多）。试图放宽系统兜底的规则
    在规范化阶段被丢弃，模型无法用自省给自己松绑。
  - **会过期**：每条规则可带有效期（默认 5 个交易日），到期自动失效，避免永久锁死。

规则白名单（模型不能自创类型）：
    block_new_buy         禁止开新仓；可限定市场环境 regimes 与到期日
    position_cap_pct      单票仓位上限（%）
    stop_loss_pct         止损线（%），只能比系统兜底更严
    max_new_positions_day 单日最多开几个新仓
    require_momentum_up   买入前需 20 日动量为正（动能未回升不得买入）
    sell_reentry_cooldown 卖出后冷静期：N 个交易日内不得买回同一只（反手冷却）
    pending_expiry_days   限价挂单超过 N 个交易日未成交自动撤销（挂单超时）

后两条借鉴 PA_Agent 的 decision_continuity（反手冷却 / 挂单过期）：前者抑制「今天割明天追」的
来回横跳，后者避免陈旧限价单长期占着冻结资金与仓位。系统有兜底默认值，规则只能收紧。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable, Optional

from ..api.paths import DATA_DIR, KLINE_DB, SIM_DB
from . import store

RULE_KIND = "rule"
REGIMES = ("牛市", "熊市", "震荡", "震荡偏强", "震荡偏弱")

#: 系统兜底（不可放宽，只能由规则收紧）
DEFAULT_PROTECTION = {
    "stop_loss_pct": 8.0,
    "trailing_stop_pct": 10.0,
    "trailing_activation_pct": 15.0,
    # 反手冷却：卖出后 1 个交易日内不得买回同一只（可被规则收紧到更长）
    "sell_reentry_cooldown": 1,
    # 挂单超时：限价挂单 3 个交易日未成交自动撤销
    "pending_expiry_days": 3,
}

DEFAULT_RULE_DAYS = 5          # 规则默认有效期（交易日）
MAX_RULES = 6                  # 同时生效的规则条数上限


# ───────────────────────── 交易日 ─────────────────────────

def _trading_days_from(start: str, limit: int = 60) -> list:
    import os
    try:
        with open(os.path.join(str(DATA_DIR), "trade_calendar.json"), encoding="utf-8") as f:
            cal = [str(x) for x in json.load(f)]
    except Exception:
        cal = []
    days = [d for d in cal if d >= start]
    return days[:limit]


def _iso(as_of) -> str:
    """把 as_of 规范成 YYYY-MM-DD；空值/非日期（如「最新」）→ 今天。"""
    s = str(as_of or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    from datetime import date
    return date.today().isoformat()


def expire_date(start: str, days: int = DEFAULT_RULE_DAYS) -> str:
    """从 start（含）起第 days 个交易日的日期；无日历时用自然日估算。"""
    ds = _trading_days_from(start, limit=max(1, int(days or 1)) + 1)
    if len(ds) >= 2:
        return ds[min(len(ds) - 1, int(days or 1))]
    from datetime import date, timedelta
    try:
        d0 = date.fromisoformat(str(start)[:10])
        return (d0 + timedelta(days=int(days or 1) * 2)).isoformat()
    except Exception:
        return start


# ───────────────────────── 规范化 / 落库 ─────────────────────────

def _fnum(v, lo, hi, default=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x <= 0:
        return default
    return max(lo, min(hi, x))


def normalize_rules(raw_rules, base_rules: Optional[list] = None,
                    as_of: str = "") -> list:
    """校验并规范化自省产出的规则。

    只保留白名单类型；阈值只能收紧（更保守）；去重（同类型只留最后一条）；
    最多 MAX_RULES 条。非法条目直接丢弃，不抛异常。
    """
    out: list = []
    seen: set = set()
    as_of = _iso(as_of) if as_of else ""
    for r in (raw_rules or []):
        if not isinstance(r, dict):
            continue
        kind = str(r.get("kind") or r.get("type") or "").strip()
        if kind not in ("block_new_buy", "position_cap_pct", "stop_loss_pct",
                        "max_new_positions_day", "require_momentum_up",
                        "sell_reentry_cooldown", "pending_expiry_days"):
            continue
        if kind in seen:
            continue
        days = int(_fnum(r.get("days"), 1, 30, DEFAULT_RULE_DAYS) or DEFAULT_RULE_DAYS)
        item = {
            "kind": kind,
            "reason": str(r.get("reason") or r.get("note") or "")[:120],
            "from": as_of or "",
            "until": expire_date(as_of, days) if as_of else "",
            "days": days,
        }
        if kind == "block_new_buy":
            regs = [str(x).strip() for x in (r.get("regimes") or []) if str(x).strip()]
            item["regimes"] = [x for x in regs if x in REGIMES][:4]
        elif kind in ("position_cap_pct", "stop_loss_pct", "max_new_positions_day",
                      "sell_reentry_cooldown", "pending_expiry_days"):
            v = _fnum(r.get("value"), 0.5, 100, None)
            if v is None:
                continue
            item["value"] = round(v, 2)
        elif kind == "require_momentum_up":
            item["value"] = 1
        # 不可放宽：position_cap_pct / stop_loss_pct 直接与兜底比较
        if kind == "stop_loss_pct" and item.get("value", 99) >= DEFAULT_PROTECTION["stop_loss_pct"]:
            continue   # 不严于系统兜底，无意义
        if kind == "position_cap_pct" and item.get("value", 0) >= 100:
            continue
        # 反手冷却 / 挂单超时：只能更保守（>= 系统兜底，上限 10）
        if kind == "sell_reentry_cooldown":
            v = item.get("value")
            if v is None or float(v) < DEFAULT_PROTECTION["sell_reentry_cooldown"]:
                item["value"] = DEFAULT_PROTECTION["sell_reentry_cooldown"]
            elif float(v) > 10:
                item["value"] = 10
        if kind == "pending_expiry_days":
            v = item.get("value")
            if v is None or float(v) < DEFAULT_PROTECTION["pending_expiry_days"]:
                item["value"] = DEFAULT_PROTECTION["pending_expiry_days"]
            elif float(v) > 10:
                item["value"] = 10
        if kind == "max_new_positions_day" and item.get("value", 99) >= 10:
            continue
        seen.add(kind)
        out.append(item)
        if len(out) >= MAX_RULES:
            break
    return out


def save_rules(profile_id: int, rules: list, decision_id: Optional[int] = None) -> int:
    """写入规则记忆：同类型旧规则置为失效，只保留最新一条生效。"""
    n = 0
    for r in rules or []:
        rid = f"{r['kind']}"
        try:
            store.add_memory(profile_id, json.dumps(r, ensure_ascii=False),
                             kind=RULE_KIND, code=rid, decision_id=decision_id)
            n += 1
        except Exception:
            continue
    return n


def active_rules(profile_id: int, as_of: Optional[str] = None) -> list:
    """取截至 as_of 生效的规则（同类只留最新；自动过滤过期）。

    as_of 为空时按今天算（实盘路径），避免过期规则被无限期执行。
    """
    as_of = _iso(as_of)
    rows = store.list_memory(int(profile_id), active_only=True, kind=RULE_KIND, limit=100)
    out: dict = {}
    for m in rows:
        try:
            r = json.loads(m.get("content") or "{}")
        except Exception:
            continue
        if not isinstance(r, dict) or not r.get("kind"):
            continue
        if r.get("from") and r["from"] > as_of:
            continue
        if r.get("until") and r["until"] < as_of:
            continue
        k = r["kind"]
        if k in out:
            continue   # list_memory 按 id 倒序，先到的即最新
        r["_memory_id"] = m.get("id")
        r["_at"] = m.get("created_at")
        out[k] = r
    return list(out.values())


def protection_rules(profile_id: int, as_of: Optional[str] = None) -> dict:
    """系统兜底保护参数 + 规则收紧（只取更严的值）。"""
    prot = dict(DEFAULT_PROTECTION)
    for r in active_rules(profile_id, as_of):
        if r["kind"] == "sell_reentry_cooldown":
            try:
                prot["sell_reentry_cooldown"] = max(
                    int(prot.get("sell_reentry_cooldown", 1)), int(float(r.get("value") or 1)))
            except Exception:
                pass
            continue
        if r["kind"] == "pending_expiry_days":
            try:
                prot["pending_expiry_days"] = max(
                    int(prot.get("pending_expiry_days", 3)), int(float(r.get("value") or 3)))
            except Exception:
                pass
            continue
        if r["kind"] == "stop_loss_pct":
            prot["stop_loss_pct"] = min(prot["stop_loss_pct"], float(r.get("value") or 99))
    return prot


# ───────────────────────── 判定：买入 ─────────────────────────

def _momentum_asof(code: str, as_of: str, window: int = 20):
    """20 日动量（%）。as_of 为空用最新一根 K 线。"""
    try:
        con = sqlite3.connect(KLINE_DB)
        if as_of:
            rows = con.execute("SELECT close FROM kline_daily WHERE code=? AND date<=? "
                               "ORDER BY date DESC LIMIT ?",
                               (str(code), str(as_of).replace("-", ""), window + 1)).fetchall()
        else:
            rows = con.execute("SELECT close FROM kline_daily WHERE code=? "
                               "ORDER BY date DESC LIMIT ?",
                               (str(code), window + 1)).fetchall()
        con.close()
        cl = [float(r[0]) for r in reversed(rows) if r and r[0]]
        if len(cl) < 2:
            return None
        return round((cl[-1] / cl[0] - 1) * 100, 2)
    except Exception:
        return None


def _account_of(profile_id: int) -> Optional[int]:
    """档案 → 模拟账户 id。"""
    try:
        prof = store.get_profile(int(profile_id))
        return int(prof["account_id"]) if prof and prof.get("account_id") is not None else None
    except Exception:
        return None


def _trading_gap(d1: str, d2: str) -> Optional[int]:
    """两个日期之间隔了几个交易日（不含起始日、含结束日），用于冷静期与挂单龄。"""
    a, b = str(d1 or "")[:10], str(d2 or "")[:10]
    if not a or not b or b < a:
        return None
    days = _trading_days_from(a, limit=120)
    return len([d for d in days if a < d <= b])


def last_sell_date(account_id: int, code: str, as_of: str = "") -> str:
    """该账户对某只股票最近一次卖出的日期（<= as_of，取成交记录里的模拟交易日）。"""
    try:
        con = sqlite3.connect(str(SIM_DB))
        row = con.execute(
            "SELECT MAX(substr(traded_at,1,10)) FROM trades "
            "WHERE account_id=? AND code=? AND side='sell' "
            "AND (?='' OR substr(traded_at,1,10)<=?)",
            (int(account_id), str(code), str(as_of)[:10], str(as_of)[:10])).fetchone()
        con.close()
        return str((row or [""])[0] or "")
    except Exception:
        return ""


def check_buy(profile_id: int, code: str, ratio_after: float = 0.0,
              regime: str = "", new_buys_today: int = 0,
              as_of: Optional[str] = None) -> Optional[dict]:
    """买入前的纪律检查。返回违规说明 dict（None=通过）。

    ratio_after: 本笔成交后该股占组合的比例（0~1）
    """
    try:
        rules = active_rules(int(profile_id), as_of)
    except Exception:
        return None

    # 反手冷却（借鉴 PA_Agent 的 flip cooldown）：卖出后 N 个交易日内不得买回同一只。
    # 系统默认 1 个交易日（防"今天割、明天追"），模型可用规则收紧到更长。
    try:
        prot = protection_rules(int(profile_id), as_of)
        cool = int(prot.get("sell_reentry_cooldown") or 0)
        acc = _account_of(profile_id) if cool > 0 else None
        if cool > 0 and acc and code:
            sold = last_sell_date(acc, code, as_of or "")
            if sold:
                gap = _trading_gap(sold, as_of or "")
                if gap is not None and gap <= cool:
                    tightened = next((r for r in rules if r["kind"] == "sell_reentry_cooldown"), None)
                    src = "纪律规则" if tightened else "系统默认冷静期"
                    return {"rule": tightened or {"kind": "sell_reentry_cooldown", "value": cool},
                            "message": f"{src}：{code} 卖出后需冷静 {cool} 个交易日"
                                       f"（上次卖出 {sold}，距今 {gap} 个交易日）"}
    except Exception:
        pass

    for r in rules:
        k = r["kind"]
        if k == "block_new_buy":
            regs = r.get("regimes") or []
            if not regs or (regime and regime in regs) or (not regime and not regs):
                why = ("当前环境 " + regime) if (regs and regime) else "当前处于观察期"
                return {"rule": r, "message": f"本交易日的纪律规则禁止开新仓（{why}）：{r.get('reason') or '自省结论'}"}
        elif k == "max_new_positions_day":
            if new_buys_today >= int(r.get("value") or 1):
                return {"rule": r, "message": f"纪律规则限定单日最多开 {int(r.get('value') or 1)} 个新仓，今日已开 {new_buys_today} 个"}
        elif k == "position_cap_pct":
            if ratio_after * 100 > float(r.get("value") or 100):
                return {"rule": r,
                        "message": f"纪律规则限定单票仓位不超过 {float(r.get('value')):g}%，"
                                   f"本笔将达 {ratio_after * 100:.1f}%"}
        elif k == "require_momentum_up":
            mom = _momentum_asof(code, as_of or "")
            if mom is not None and mom <= 0:
                return {"rule": r,
                        "message": f"纪律规则要求 20 日动量为正才可买入，{code} 当前动量 {mom:+.2f}%"}
    return None


def describe_rules(rules: list) -> list:
    """把规则压成给模型看的短句。"""
    CN = {
        "block_new_buy": "禁止开新仓",
        "position_cap_pct": "单票仓位上限",
        "stop_loss_pct": "止损线",
        "max_new_positions_day": "单日新仓数上限",
        "require_momentum_up": "买入需 20 日动量为正",
        "sell_reentry_cooldown": "卖出后冷静期",
        "pending_expiry_days": "挂单超时撤销",
    }
    out = []
    for r in rules or []:
        k = r.get("kind")
        txt = CN.get(k, k)
        if k in ("position_cap_pct", "stop_loss_pct"):
            txt += f" {float(r.get('value') or 0):g}%"
        elif k == "max_new_positions_day":
            txt += f" {int(r.get('value') or 0)} 个"
        elif k in ("sell_reentry_cooldown", "pending_expiry_days"):
            txt += f" {int(float(r.get('value') or 0))} 个交易日"
        if k == "block_new_buy" and r.get("regimes"):
            txt += "（" + "/".join(r["regimes"]) + "）"
        if r.get("until"):
            txt += f"，至 {r['until']}"
        if r.get("reason"):
            txt += f" —— {r['reason']}"
        out.append({"kind": k, "text": txt, "rule": r})
    return out


def expire_pending_orders(engine, profile_id: int, account_id: int, as_of: str) -> list:
    """挂单超时：限价挂单超过 N 个交易日未成交，由系统撤销（释放冻结资金/仓位）。

    借鉴 PA_Agent 的 pending limit 过期（默认 3 根 K 线）：陈旧挂单既占额度，
    也会让模型误以为"已经在下单了"。返回被撤销的委托列表（供落库与前端展示）。
    """
    prot = protection_rules(int(profile_id), as_of)
    limit_days = int(prot.get("pending_expiry_days") or 0)
    out: list = []
    if limit_days <= 0:
        return out
    try:
        pendings = engine.get_orders(int(account_id), "pending") or []
    except Exception:
        return out
    for o in pendings:
        placed = str(o.get("created_at") or "")[:10]
        if not placed:
            continue
        age = _trading_gap(placed, as_of)
        if age is None or age <= limit_days:
            continue
        rec = {"order_id": o.get("id"), "code": o.get("code"),
               "name": o.get("name") or o.get("code"), "side": o.get("side"),
               "qty": o.get("qty"), "price": o.get("price"), "placed": placed,
               "days": age, "forced": True, "ok": False, "detail": ""}
        try:
            ok, msg = engine.cancel_order(int(o.get("id")))
        except Exception as e:
            ok, msg = False, str(e)
        if ok:
            rec.update({"ok": True,
                        "detail": f"挂单超时（{age} 个交易日未成交 > {limit_days} 日）已由系统撤销"})
        else:
            rec["detail"] = f"撤销失败：{msg}"
        out.append(rec)
    return out


# ───────────────────────── 每日持仓保护（强制卖出） ─────────────────────────

def _closes_since(code: str, start: str, as_of: str, limit: int = 120) -> list:
    try:
        con = sqlite3.connect(KLINE_DB)
        rows = con.execute(
            "SELECT close FROM kline_daily WHERE code=? AND date>=? AND date<=? ORDER BY date",
            (str(code), str(start).replace("-", "") if start else "19000101",
             str(as_of).replace("-", ""))).fetchall()
        con.close()
        return [float(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []


def enforce_protection(engine, profile_id: int, account_id: int, as_of: str,
                       price_fn: Callable, trade_date: Optional[str] = None,
                       emit: Optional[Callable] = None) -> list:
    """收盘后的兜底保护：浮亏触及止损线、或移动止损触发 → 由系统强制卖出。

    「模型不卖的，系统卖」是「规则归系统」的兜底部分：模型可以自己更早卖，
    但系统不允许持仓无限扛亏（实测回放里出现过 -12% 才被模型割掉的情况）。
    """
    prot = protection_rules(int(profile_id), as_of)
    out: list = []
    try:
        positions = engine.get_positions(int(account_id))
    except Exception:
        return out
    for pos in positions or []:
        code = str(pos.get("code") or "")
        qty = int(pos.get("qty") or 0)
        cost = float(pos.get("cost_price") or 0)
        if not code or qty <= 0 or cost <= 0:
            continue
        try:
            px = float(price_fn(code) or 0)
        except Exception:
            px = 0
        if px <= 0:
            continue
        buy_date = str(pos.get("last_buy_date") or as_of)
        closes = _closes_since(code, buy_date, as_of)
        peak = max([cost] + closes) if closes else cost
        pnl_pct = (px / cost - 1) * 100
        peak_pct = (peak / cost - 1) * 100
        from_peak = (px / peak - 1) * 100 if peak > 0 else 0.0
        reason = ""
        if pnl_pct <= -float(prot["stop_loss_pct"]):
            reason = f"止损（浮亏 {pnl_pct:.2f}% 触及 {prot['stop_loss_pct']:g}% 兜底线）"
        elif peak_pct >= float(prot["trailing_activation_pct"]) and from_peak <= -float(prot["trailing_stop_pct"]):
            reason = f"移动止损（自高点 {peak:.2f} 回落 {abs(from_peak):.2f}%）"
        if not reason:
            continue
        rec = {"code": code, "name": pos.get("name") or code, "side": "sell", "qty": qty,
               "price": round(px, 3), "reason": reason, "forced": True,
               "pnl_pct": round(pnl_pct, 2), "ok": False, "detail": ""}
        if buy_date == str(trade_date or as_of):
            rec["detail"] = "T+1：今日买入，系统保护无法卖出"
            out.append(rec)
            continue
        try:
            order, trade = engine.place_order(
                int(account_id), code, pos.get("name") or code, "sell", "market", 0, qty,
                current_price=px, trade_date=trade_date or as_of)
        except Exception as e:
            rec["detail"] = f"保护卖出失败：{e}"
            out.append(rec)
            continue
        if trade:
            rec.update({"ok": True, "detail": "系统保护卖出（已成交）",
                        "commission": round(float(trade.get("commission") or 0), 2),
                        "stamp_tax": round(float(trade.get("stamp_tax") or 0), 2)})
            try:
                store.resolve_memory_by_code(int(profile_id), code, kind="thesis")
            except Exception:
                pass
        elif order is not None:
            rec.update({"ok": True, "detail": "系统保护卖出（已挂单）"})
        else:
            rec["detail"] = f"保护卖出被拒：{trade}"
        out.append(rec)
        if emit:
            try:
                emit(f"系统保护：{rec['name']}({code}) {reason} → {rec['detail']}")
            except Exception:
                pass
    return out
