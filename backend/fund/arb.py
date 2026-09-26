# -*- coding: utf-8 -*-
"""LOF 折溢价套利：机会计算 + 成本模型 + 明细。

两条腿（都按「当天可执行」口径，收盘价 + 最新公布净值）：
  溢价套利：场外按净值申购 →（T+2 确认 + 转托管 T+1）→ 场内卖出
  折价套利：场内买入 →（T+1 可转托管）→ 场外按净值赎回（赎回费按持有天数分档）

成本项：申购费(分档,支持折扣) / 场内佣金(含最低) / 赎回费(按档) / 转托管费 / 滑点（跳）。
所有比例都是「相对投入本金」的百分比；金额类默认按 1 万元投入展示。
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from . import store

TICK = 0.001  # 基金场内最小报价单位（元）

DEFAULT_CFG = {
    "amount": 10000.0,        # 展示用投入金额（元）
    "commission_rate": 0.00025,   # 场内佣金费率（单边）
    "commission_min": 5.0,        # 单笔最低佣金（元）
    "buy_fee_discount": 1.0,      # 场外申购费率折扣（1.0 = 按公布费率；0.1 = 1 折）
    "transfer_fee": 0.0,          # 转托管费（元/笔）
    "slippage_ticks": 1.0,        # 卖出滑点（跳，1 跳 = 0.001 元/份）
    "premium_days": 3,            # 溢价路径资金占用天数（场外申购 T+2 到账 + 转托管 T+1）
    "discount_days": 3,           # 折价路径资金占用天数（T+1 转托管 + 赎回确认 + 到账）
    "annual_days": 250,
    "min_liquidity": 500000.0,    # 场内日成交额低于此值标"流动性弱"（元）
    "default_buy_fee_pct": 1.5,   # 拿不到申购费率时的兜底（%）
}


# ---------------- 赎回费率分档解析 ----------------

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
           "百": 100, "千": 1000, "万": 10000}


def _to_days(num_txt: str, unit: str) -> Optional[int]:
    """把 '7天' / '一年' / '三个月' / '365' 等换成天数。"""
    if not num_txt:
        return None
    n = None
    m = re.search(r"(\d+(?:\.\d+)?)", num_txt)
    if m:
        n = float(m.group(1))
    else:
        # 中文数字（简单支持：一~十万）
        s = num_txt.strip()
        if s and all(ch in _CN_NUM or ch == "" for ch in s):
            total, cur = 0, 0
            for ch in s:
                v = _CN_NUM.get(ch)
                if v is None:
                    continue
                if v >= 10:      # 十/百/千/万 作为单位
                    cur = (cur or 1) * v
                    total += cur
                    cur = 0
                else:
                    cur = cur * 10 + v if cur and cur < 10 else v
            total += cur
            n = float(total) if total else None
    if n is None:
        return None
    u = unit or ""
    if "年" in u:
        return int(round(n * 365))
    if "月" in u:
        return int(round(n * 30))
    return int(round(n))          # 天/日/无单位


def parse_redeem_tiers(tiers: List[dict]) -> List[dict]:
    """[{'term':'小于7天','rate':'1.50%'}] → [{min_days,max_days,rate_pct,label}]，按 min_days 排序。"""
    out = []
    for t in tiers or []:
        term = str(t.get("term", ""))
        rate = t.get("rate_pct")
        if rate is None:
            m = re.search(r"([\d.]+)\s*%", str(t.get("rate", "")))
            rate = float(m.group(1)) if m else None
        if rate is None:
            continue
        lo = hi = None
        # 逐段解析（一段可能同时含上下界，如「大于等于15天，小于30天」）
        for p in re.split(r"[，,、;；]", term):
            d = _to_days(p, p)
            if d is None:
                continue
            if "小于" in p:
                hi = d if hi is None else min(hi, d)
            elif "大于等于" in p or "以上" in p or "起" in p:
                lo = d if lo is None else max(lo, d)
            elif "大于" in p:
                lo = d + 1 if lo is None else max(lo, d + 1)
        if lo is None and hi is not None:
            lo = 0
        if hi is None and lo is not None:
            hi = 10 ** 9
        if lo is None and hi is None:
            continue
        out.append({"min_days": lo or 0, "max_days": hi if hi is not None else 10 ** 9,
                    "rate_pct": float(rate), "label": term or f"≥{lo}天"})
    out.sort(key=lambda x: (x["min_days"], x["max_days"]))
    if not out:   # 兜底：行业最常见档位
        out = [{"min_days": 0, "max_days": 7, "rate_pct": 1.5, "label": "小于7天(默认)"},
               {"min_days": 7, "max_days": 365, "rate_pct": 0.5, "label": "7天~1年(默认)"},
               {"min_days": 365, "max_days": 10 ** 9, "rate_pct": 0.25, "label": "1年以上(默认)"}]
    return out


def redeem_rate_for(tiers: List[dict], hold_days: int) -> Optional[dict]:
    """按持有天数取赎回费率档。找不到匹配时：
    早于最低档覆盖范围 → 用**第一档（最严）**，保守；晚于所有档 → 用最后一档（最宽）。"""
    for t in tiers:
        if t["min_days"] <= hold_days < t["max_days"]:
            return t
    if not tiers:
        return None
    if hold_days < tiers[0]["min_days"]:
        return tiers[0]
    return tiers[-1]


def _annualize(ret: float, days: int, annual_days: int = 250) -> float:
    """线性折算年化 = 单次收益 × (250/占用天数)。短窗口不用复利（3 天复利会给出天文数字）。"""
    if days <= 0:
        return 0.0
    try:
        return ret * (annual_days / days)
    except Exception:
        return 0.0


# ---------------- 两条腿的成本模型 ----------------

def premium_plan(price: float, nav: float, cfg: Dict, buy_fee_pct: float) -> Dict:
    """溢价套利：场外按净值申购 → 场内卖出。返回成本拆解。"""
    amount = float(cfg["amount"])
    fee_rate = max(0.0, (buy_fee_pct or cfg["default_buy_fee_pct"]) / 100.0 * cfg["buy_fee_discount"])
    net_sub = amount / (1.0 + fee_rate)          # 外扣法：净申购金额
    buy_fee = amount - net_sub
    shares = net_sub / nav if nav > 0 else 0.0
    sell_px = max(0.0, price - cfg["slippage_ticks"] * TICK)
    gross = shares * sell_px
    comm = max(gross * cfg["commission_rate"], cfg["commission_min"]) if gross > 0 else 0.0
    net = gross - comm - cfg["transfer_fee"]
    profit = net - amount
    ret = profit / amount if amount else 0.0
    days = int(cfg["premium_days"])
    return {
        "kind": "premium",
        "amount": amount, "shares": round(shares, 2),
        "buy_fee": round(buy_fee, 2), "commission": round(comm, 2),
        "transfer_fee": cfg["transfer_fee"], "slippage_cost": round(shares * cfg["slippage_ticks"] * TICK, 2),
        "gross_in": round(gross, 2), "net_back": round(net, 2),
        "profit": round(profit, 2), "space_pct": round(ret * 100, 4),
        "days": days, "annual_pct": round(_annualize(ret, days, cfg["annual_days"]) * 100, 2),
        "fee_pct": round((buy_fee + comm + cfg["transfer_fee"] + shares * cfg["slippage_ticks"] * TICK)
                         / amount * 100, 4),
        "costs": round(buy_fee + comm + cfg["transfer_fee"] + shares * cfg["slippage_ticks"] * TICK, 2),
    }


def discount_plan(price: float, nav: float, cfg: Dict, tiers_raw: List[dict], hold_days: Optional[int] = None) -> Dict:
    """折价套利：场内买入 → 场外赎回。hold_days=None 时用 cfg['discount_days']（短期最快方案）。"""
    amount = float(cfg["amount"])
    days = int(hold_days if hold_days is not None else cfg["discount_days"])
    tiers = parse_redeem_tiers(tiers_raw)
    tier = redeem_rate_for(tiers, days)
    redeem_pct = (tier or {}).get("rate_pct", 0.0)
    # 买入（佣金按名义金额近似，误差 < 0.01%）
    comm = max(amount * cfg["commission_rate"], cfg["commission_min"])
    gross_buy = amount - comm
    shares = gross_buy / price if price > 0 else 0.0
    # 赎回（按当前净值；持有期内净值会变 → 这是"按现价估算"的口径）
    redeem_amt = shares * nav
    redeem_fee = redeem_amt * redeem_pct / 100.0
    net = redeem_amt - redeem_fee - cfg["transfer_fee"]
    profit = net - amount
    ret = profit / amount if amount else 0.0
    return {
        "kind": "discount",
        "amount": amount, "shares": round(shares, 2),
        "commission": round(comm, 2), "redeem_fee": round(redeem_fee, 2),
        "redeem_rate_pct": redeem_pct, "tier_label": (tier or {}).get("label"),
        "transfer_fee": cfg["transfer_fee"],
        "gross_in": round(redeem_amt, 2), "net_back": round(net, 2),
        "profit": round(profit, 2), "space_pct": round(ret * 100, 4),
        "days": days, "annual_pct": round(_annualize(ret, days, cfg["annual_days"]) * 100, 2),
        "fee_pct": round((comm + redeem_fee + cfg["transfer_fee"]) / amount * 100, 4),
        "costs": round(comm + redeem_fee + cfg["transfer_fee"], 2),
    }


def best_discount_plan(price: float, nav: float, cfg: Dict, tiers_raw: List[dict]) -> Dict:
    """折价路径的「最省费方案」：用最低费率档（通常是长持档）。"""
    tiers = parse_redeem_tiers(tiers_raw)
    cheapest = min(tiers, key=lambda t: (t["rate_pct"], t["min_days"]))
    return discount_plan(price, nav, cfg, tiers_raw, hold_days=int(cheapest["min_days"]))


# ---------------- 机会表 ----------------

def _breakeven(make_plan, lo: float = 100.0, hi: float = 2_000_000.0, iters: int = 40):
    """二分求「覆盖手续费开始盈利」的最小申购金额（profit 随金额单调增）。

    来源：场内佣金有 5 元最低值 → 本金越小、固定成本占比越高；低于保本金额时净空间为负。
    """
    try:
        if make_plan(hi)["profit"] <= 0:
            return None          # 再大也不赚（费率型成本吃掉了空间）
        if make_plan(lo)["profit"] > 0:
            return round(lo, 0)
        for _ in range(iters):
            mid = (lo + hi) / 2
            if make_plan(mid)["profit"] > 0:
                hi = mid
            else:
                lo = mid
        return round(hi, 0)
    except Exception:
        return None


def max_amount_hint(daily_limit, turnover, liquidity_share: float = 0.10):
    """本金上限提示：申购日限额 与「当日成交额 × 10%」取小（卖出冲击的经验口径）。"""
    caps = []
    if daily_limit and 0 < daily_limit < 1e10:
        caps.append(float(daily_limit))
    if turnover and turnover > 0:
        caps.append(float(turnover) * liquidity_share)
    return round(min(caps), 0) if caps else None


def sizing_curve(price: float, nav: float, tiers_raw, buy_fee_pct, cfg: Dict,
                 kind: str = "premium", n: int = 48, upper: Optional[float] = None) -> List[Dict]:
    """本金-收益曲线（试算图用）：本金 100 元 →上限（对数均匀取点）。

    kind: premium（申购→卖出）| discount（买入→赎回）
    """
    if not price or not nav or price <= 0 or nav <= 0:
        return []
    hi = float(upper or 1_000_000.0)
    hi = max(20000.0, min(hi, 5_000_000.0))
    lo = min(100.0, hi / 10)
    out = []
    for i in range(n):
        a = lo * (hi / lo) ** (i / (n - 1))
        c = {**cfg, "amount": a}
        plan = (premium_plan(price, nav, c, buy_fee_pct) if kind == "premium"
                else discount_plan(price, nav, c, tiers_raw))
        out.append({"amount": round(a, 0), "profit": plan["profit"],
                    "space_pct": plan["space_pct"], "fee_pct": plan["fee_pct"]})
    return out


def sizing_table(price: float, nav: float, tiers_raw, buy_fee_pct, cfg: Dict,
                 amounts=(1000, 5000, 10000, 50000, 100000)) -> List[Dict]:
    """不同本金下的净赚与收益率（两条腿都算），给明细页用。"""
    out = []
    for a in amounts:
        c = dict(cfg); c["amount"] = float(a)
        prem = premium_plan(price, nav, c, buy_fee_pct)
        disc = discount_plan(price, nav, c, tiers_raw)
        out.append({"amount": a,
                    "premium": {"profit": prem["profit"], "space_pct": prem["space_pct"], "fee_pct": prem["fee_pct"]},
                    "discount": {"profit": disc["profit"], "space_pct": disc["space_pct"], "fee_pct": disc["fee_pct"]}})
    return out


def _merge_cfg(**over) -> Dict:
    cfg = dict(DEFAULT_CFG)
    for k, v in over.items():
        if v is not None:
            cfg[k] = v
    return cfg


def opportunities(cfg_over: Optional[Dict] = None, direction: Optional[str] = None,
                  min_space: float = 0.0, only_open: bool = False, limit: int = 500,
                  executable_only: bool = False, liquid_only: bool = False) -> Dict:
    """全量 LOF 折溢价机会表（按净空间排序）。"""
    cfg = _merge_cfg(**(cfg_over or {}))
    rows = store.latest_snapshot()
    out = []
    for r in rows:
        price, nav = r.get("price"), r.get("nav")
        if not price or not nav or price <= 0 or nav <= 0:
            continue
        prem = (price / nav - 1.0) * 100.0
        tiers_raw = []
        try:
            import json as _json
            tiers_raw = _json.loads(r.get("redeem_tiers") or "[]")
        except Exception:
            tiers_raw = []
        lag_days = None
        if r.get("price_date") and r.get("nav_date"):
            try:
                import datetime as _dt
                lag_days = (_dt.date.fromisoformat(r["price_date"]) - _dt.date.fromisoformat(r["nav_date"])).days
            except Exception:
                lag_days = None
        lag_bars = int(r.get("lag_bars") or 0)     # 相对最新价格日落后几个交易日（对齐口径）
        item = {
            "code": r["code"], "name": r["name"], "exchange": r["exchange"], "ftype": r.get("ftype"),
            "price": round(price, 4), "price_date": r.get("price_date"),
            "nav": round(nav, 4), "nav_date": r.get("nav_date"), "nav_lag_days": lag_days,
            "lag_bars": lag_bars, "aligned": bool(r.get("aligned")),
            "price_latest_date": r.get("price_latest_date"),
            "premium_pct": round(prem, 3),
            "direction": "premium" if prem > 0 else "discount",
            "amount": r.get("amount"),
            "liquidity_ok": (r.get("amount") or 0) >= cfg["min_liquidity"],
            "purchase_status": r.get("purchase_status"), "redeem_status": r.get("redeem_status"),
            "min_amount": r.get("min_amount"), "daily_limit": r.get("daily_limit"),
            "fee_rate_pct": r.get("fee_rate"),
            "is_qdii": "QDII" in str(r.get("ftype") or ""),
            "tags": [],
        }
        ps = str(r.get("purchase_status") or "")
        if "暂停" in ps:
            item["tags"].append("暂停申购")
        elif "限" in ps:
            item["tags"].append("限大额")
        if item["is_qdii"]:
            item["tags"].append("QDII")
        if lag_bars >= 1:
            item["tags"].append(f"净值未出·回退{lag_bars}日")
        if not item["liquidity_ok"]:
            item["tags"].append("流动性弱")
        if (r.get("daily_limit") or 0) < 1e6 and (r.get("daily_limit") or 0) > 0:
            item["tags"].append("有日限额")

        item["executable"] = (("暂停" not in ps) and item["direction"] == "premium") or                              (("暂停" not in str(r.get("redeem_status") or "")) and item["direction"] == "discount")

        item["premium"] = premium_plan(price, nav, cfg, r.get("fee_rate"))
        item["discount"] = discount_plan(price, nav, cfg, tiers_raw)
        item["discount_best"] = best_discount_plan(price, nav, cfg, tiers_raw)
        # 保本金额（覆盖 5 元最低佣金等固定成本）与本金上限提示
        item["premium"]["breakeven"] = _breakeven(
            lambda a: premium_plan(price, nav, {**cfg, "amount": a}, r.get("fee_rate")))
        item["discount"]["breakeven"] = _breakeven(
            lambda a: discount_plan(price, nav, {**cfg, "amount": a}, tiers_raw))
        item["max_amount"] = max_amount_hint(r.get("daily_limit"), r.get("amount"))

        # 方向过滤 + 空间过滤（取该方向的主方案）
        if direction in ("premium", "discount") and item["direction"] != direction:
            continue
        space = item["premium"]["space_pct"] if item["direction"] == "premium" else item["discount"]["space_pct"]
        item["space_pct"] = space
        item["profit_per_10k"] = round((item["premium"]["profit"] if item["direction"] == "premium"
                                        else item["discount"]["profit"]) / cfg["amount"] * 10000, 1)
        item["space_best_pct"] = item["discount_best"]["space_pct"] if item["direction"] == "discount" else None
        if space < min_space:
            continue
        if (only_open or executable_only) and not item.get("executable"):
            continue
        if liquid_only and not item.get("liquidity_ok"):
            continue
        out.append(item)
    out.sort(key=lambda x: -(x.get("space_pct") or 0))
    return {"total": len(out), "cfg": cfg, "items": out[:limit]}


def fund_hist_arb(code: str, cfg_over: Optional[Dict] = None, hold: int = 3,
                  thresholds=(0.5, 1.0, 2.0, 3.0, 5.0)) -> List[Dict]:
    """该基金历史上「溢价 ≥ 阈值」信号的 T+hold 实现收益（按本项目成本模型扣费）。

    注意：这是**该基金自身**的历史统计（样本重叠、无历史申购状态/限额约束），
    只作"这类信号大概能拿到多少"的参照，不是对未来收益的承诺。
    """
    cfg = _merge_cfg(**(cfg_over or {}))
    px = store.daily_series(code, 5000)
    nvs = store.nav_series(code, 5000)
    if len(px) < 80 or len(nvs) < 80:
        return []
    import bisect
    nav_dates = [x["date"] for x in nvs]
    nav_vals = [x["nav"] for x in nvs]
    fee_pct = None
    snap = [r for r in store.latest_snapshot() if r["code"] == code]
    if snap:
        fee_pct = snap[0].get("fee_rate")
    f = (fee_pct if fee_pct is not None else 1.5) / 100.0
    out = []
    for thr in thresholds:
        rs, prems_t, prems_f = [], [], []
        for i in range(len(px) - hold):
            d = px[i]["date"]
            j = bisect.bisect_right(nav_dates, d) - 1
            if j < 0:
                continue
            nav_t = nav_vals[j]
            if not nav_t or not px[i]["close"]:
                continue
            prem = px[i]["close"] / nav_t - 1
            if prem * 100 < thr:
                continue
            k = bisect.bisect_right(nav_dates, px[i + hold]["date"]) - 1
            nav_f = nav_vals[k] if k >= 0 else None
            plan = premium_plan(px[i + hold]["close"], nav_t, cfg, (fee_pct if fee_pct is not None else 1.5))
            rs.append(plan["space_pct"] / 100.0)
            prems_t.append(prem * 100)
            if nav_f:
                prems_f.append((px[i + hold]["close"] / nav_f - 1) * 100)
        if len(rs) >= 5:
            import numpy as _np
            r = np_clip(rs)
            out.append({"threshold": thr, "n": len(r),
                        "mean_pct": round(float(_np.mean(r)) * 100, 3),
                        "median_pct": round(float(_np.median(r)) * 100, 3),
                        "win_pct": round(float((_np.array(r) > 0).mean()) * 100, 1),
                        "premium_t": round(float(_np.mean(prems_t)), 2),
                        "premium_t3": round(float(_np.mean(prems_f)), 2) if prems_f else None})
    return out


def np_clip(arr, w: float = 0.20):
    import numpy as _np
    return _np.clip(_np.array(arr, dtype=float), -w, w)


def fund_detail(code: str, cfg_over: Optional[Dict] = None, hist_days: int = 250) -> Optional[Dict]:
    """单只明细：快照 + 两条腿成本拆解 + 费率表 + 历史折溢价序列。"""
    cfg = _merge_cfg(**(cfg_over or {}))
    snap = None
    for r in store.latest_snapshot():
        if r["code"] == code:
            snap = r
            break
    if not snap:
        return None
    import json as _json
    try:
        tiers_raw = _json.loads(snap.get("redeem_tiers") or "[]")
    except Exception:
        tiers_raw = []
    try:
        buy_raw = _json.loads(snap.get("buy_tiers") or "[]")
    except Exception:
        buy_raw = []
    tiers = parse_redeem_tiers(tiers_raw)
    price, nav = snap.get("price"), snap.get("nav")
    detail = {
        "code": code, "name": snap.get("name"), "exchange": snap.get("exchange"), "ftype": snap.get("ftype"),
        "price": price, "price_date": snap.get("price_date"), "nav": nav, "nav_date": snap.get("nav_date"),
        "premium_pct": round((price / nav - 1) * 100, 3) if (price and nav) else None,
        "amount": snap.get("amount"),
        "purchase_status": snap.get("purchase_status"), "redeem_status": snap.get("redeem_status"),
        "min_amount": snap.get("min_amount"), "daily_limit": snap.get("daily_limit"),
        "fee_rate_pct": snap.get("fee_rate"),
        "redeem_tiers": tiers, "buy_tiers": buy_raw,
        "cfg": cfg,
        "history": store.premium_series(code, hist_days),
        "nav_history": store.nav_series(code, hist_days),
        "price_history": store.daily_series(code, hist_days),
        # 历史实测固定按 1 万元本金（否则 5 元最低佣金会随用户输入本金漂移，统计口径不稳定）
        "hist_arb": fund_hist_arb(code, {**cfg, "amount": 10000}),
        "sizing": sizing_table(price, nav, tiers_raw, snap.get("fee_rate"), cfg) if (price and nav) else [],
        "curve": ({"premium": sizing_curve(price, nav, tiers_raw, snap.get("fee_rate"), cfg, "premium"),
                   "discount": sizing_curve(price, nav, tiers_raw, snap.get("fee_rate"), cfg, "discount")}
                  if (price and nav) else {}),
        "plans": {},
    }
    if price and nav:
        detail["plans"]["premium"] = premium_plan(price, nav, cfg, snap.get("fee_rate"))
        detail["plans"]["discount"] = discount_plan(price, nav, cfg, tiers_raw)
        detail["plans"]["discount_best"] = best_discount_plan(price, nav, cfg, tiers_raw)
        detail["plans"]["premium"]["breakeven"] = _breakeven(
            lambda a: premium_plan(price, nav, {**cfg, "amount": a}, snap.get("fee_rate")))
        detail["plans"]["discount"]["breakeven"] = _breakeven(
            lambda a: discount_plan(price, nav, {**cfg, "amount": a}, tiers_raw))
    detail["max_amount"] = max_amount_hint(snap.get("daily_limit"), snap.get("amount"))
    hist = detail["history"]
    if hist:
        ps = sorted(x["premium_pct"] for x in hist)
        n = len(ps)
        detail["stats"] = {
            "n": n,
            "median_pct": round(ps[n // 2], 3),
            "p90_pct": round(ps[min(n - 1, int(n * 0.9))], 3),
            "p10_pct": round(ps[max(0, int(n * 0.1))], 3),
            "max_pct": round(ps[-1], 3), "min_pct": round(ps[0], 3),
            "days_above_1pct": int(sum(1 for x in ps if x > 1.0)),
            "days_above_2pct": int(sum(1 for x in ps if x > 2.0)),
        }
    return detail


def overview() -> Dict:
    """概览：机会数量与最大空间（扣费后）。"""
    res = opportunities(min_space=-100, limit=10000)
    items = res["items"]
    prem = [i for i in items if i["direction"] == "premium"]
    disc = [i for i in items if i["direction"] == "discount"]
    top_prem = sorted(prem, key=lambda x: -(x["premium"]["space_pct"]))[:5]
    top_disc = sorted(disc, key=lambda x: -(x["discount"]["space_pct"]))[:5]
    return {
        "stats": store.stats(),
        "count": {"all": len(items), "premium": len(prem), "discount": len(disc),
                  "premium_profitable": sum(1 for i in prem if i["premium"]["space_pct"] > 0),
                  "discount_profitable": sum(1 for i in disc if i["discount"]["space_pct"] > 0)},
        "top_premium": [{"code": i["code"], "name": i["name"], "premium_pct": i["premium_pct"],
                         "space_pct": i["premium"]["space_pct"], "days": i["premium"]["days"],
                         "purchase_status": i["purchase_status"], "tags": i["tags"]} for i in top_prem],
        "top_discount": [{"code": i["code"], "name": i["name"], "premium_pct": i["premium_pct"],
                          "space_pct": i["discount"]["space_pct"], "days": i["discount"]["days"],
                          "tags": i["tags"]} for i in top_disc],
    }
