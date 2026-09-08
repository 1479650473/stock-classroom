# -*- coding: utf-8 -*-
"""每日决策编排 —— 构建上下文 → LLM 操盘手决策 → 校验执行 → 落长期记忆。

入口：run_daily_decision()。被两条路径调用：
  ① update_daily.py 末尾（数据更新后自动跑，非交易日跳过）
  ② /api/trader/run（页面手动补跑 / 调试）

幂等：同一交易日已 done 则默认跳过（force=True 重跑会覆盖当天记录）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional

from ..trade_engine.engine import TradeEngine
from . import account as acct_mod
from . import context as ctx_mod
from . import store
from .agent import TraderAgent


def _emit(progress, msg: str, pct: Optional[int] = None):
    if not progress:
        return
    try:
        progress({"msg": msg, "pct": pct} if pct is not None else {"msg": msg})
    except Exception:
        pass


def _resolve_price(code: str, order_type: str, price) -> Optional[float]:
    if str(order_type).lower() == "limit" and price:
        try:
            p = float(price)
            return p if p > 0 else None
        except Exception:
            return None
    px = ctx_mod.refresh_prices([code]).get(str(code)) or {}
    p = px.get("price")
    return float(p) if p else None


def _execute_orders(profile: dict, plan: list, progress=None,
                    decision_id: Optional[int] = None) -> list:
    """按风险约束执行委托，返回每笔结果。"""
    engine = TradeEngine()
    account_id = int(profile["account_id"])
    rules = profile.get("risk_rules") or {}
    max_new_buys = int(rules.get("max_new_buys_per_day", 2) or 2)
    max_positions = int(rules.get("max_positions", 8) or 8)
    min_cash_pct = float(rules.get("min_cash_pct", 5) or 0) / 100.0

    results = []
    buys_done = 0
    for i, o in enumerate(plan or [], 1):
        if not isinstance(o, dict):
            continue
        code = str(o.get("code") or "").strip()
        name = str(o.get("name") or "").strip()
        side = str(o.get("side") or "").lower()
        otype = str(o.get("order_type") or "market").lower()
        try:
            qty = int(o.get("qty") or 0)
        except Exception:
            qty = 0
        reason = str(o.get("reason") or "").strip()
        rec = {"code": code, "name": name, "side": side, "order_type": otype,
               "qty": qty, "reason": reason, "ok": False, "detail": ""}

        if not code or side not in ("buy", "sell") or qty <= 0:
            rec["detail"] = "参数非法"
            results.append(rec)
            continue

        positions = engine.get_positions(account_id)
        held_codes = {p["code"] for p in positions}
        summary = engine.get_summary(account_id) or {}
        total_assets = float(summary.get("total_assets", 0))

        # 风险约束（买入）
        if side == "buy":
            if buys_done >= max_new_buys:
                rec["detail"] = f"超过单日新开仓上限 {max_new_buys} 笔"
                results.append(rec)
                continue
            if code not in held_codes and len(held_codes) >= max_positions:
                rec["detail"] = f"超过最大持仓数 {max_positions} 只"
                results.append(rec)
                continue

        price = _resolve_price(code, otype, o.get("price"))
        if not price:
            rec["detail"] = "无法确定价格"
            results.append(rec)
            continue

        # 现金下限（买入）
        if side == "buy":
            cost = price * qty * (1 + engine.COMMISSION_RATE)
            if total_assets > 0:
                after_cash = float(summary.get("balance", 0)) - cost
                if after_cash < total_assets * min_cash_pct:
                    rec["detail"] = f"会跌破现金下限 {min_cash_pct*100:.0f}%"
                    results.append(rec)
                    continue

        order, trade = engine.place_order(
            account_id, code, name or code, side, otype,
            price if otype == "limit" else 0, qty, current_price=price)
        if order is None:
            rec["detail"] = str(trade)
            results.append(rec)
            continue

        if trade:  # 市价成交
            rec.update({"ok": True, "price": round(float(trade["price"]), 3),
                        "qty": int(trade["qty"]),
                        "commission": round(float(trade.get("commission") or 0), 2),
                        "stamp_tax": round(float(trade.get("stamp_tax") or 0), 2),
                        "detail": "已成交"})
            if side == "buy":
                buys_done += 1
                if reason:
                    store.add_memory(int(profile["id"]), reason, kind="thesis",
                                     code=code, decision_id=decision_id)
            else:
                # 清仓 → 该股持仓逻辑失效
                still = [p for p in engine.get_positions(account_id) if p["code"] == code]
                if not still:
                    store.resolve_memory_by_code(int(profile["id"]), code, kind="thesis")
        else:  # 限价挂单
            rec.update({"ok": True, "price": round(float(order["price"]), 3),
                        "qty": int(order["qty"]), "order_id": order["id"],
                        "detail": "已挂限价单，未成交"})
        results.append(rec)
        _emit(progress, f"  委托 {i}/{len(plan)} {code} {side} {qty} → {rec['detail']}")
    return results


def run_daily_decision(profile_id: Optional[int] = None, trigger: str = "manual",
                       force: bool = False, dry_run: bool = False,
                       with_candidates: bool = True, with_news: bool = True,
                       progress: Optional[Callable] = None) -> dict:
    """跑一次操盘手决策。返回决策记录 dict（含 status/thinking/plan/executions）。"""
    store.ensure_schema()
    profile = acct_mod.ensure_profile() if profile_id is None else store.get_profile(profile_id)
    if profile is None:
        return {"status": "error", "error": "操盘手档案不存在"}
    pid = int(profile["id"])
    trade_date = date.today().isoformat()

    existing = store.get_decision(pid, trade_date)
    if existing and existing.get("status") == "done" and not force:
        _emit(progress, f"今日({trade_date})已完成决策，跳过")
        return existing

    nav_before = None
    ta_before = None
    try:
        s = TradeEngine().get_summary(int(profile["account_id"])) or {}
        ta_before = float(s.get("total_assets", 0))
        init = float(s.get("initial_capital") or 1)
        nav_before = round(ta_before / init, 5) if init else None
    except Exception:
        pass

    store.upsert_decision(pid, trade_date, status="running", trigger=trigger,
                          nav_before=nav_before, total_assets_before=ta_before,
                          error="", finished_at=None)
    dec_row = store.get_decision(pid, trade_date) or {}
    decision_id = dec_row.get("id")
    _emit(progress, "构建决策上下文（账户/持仓/市场/候选/新闻/记忆）…", 10)

    try:
        ctx = ctx_mod.build_daily_context(profile, with_candidates=with_candidates,
                                          with_news=with_news)
    except Exception as e:
        store.upsert_decision(pid, trade_date, status="error",
                              error=f"上下文构建失败: {e}",
                              finished_at=datetime.now().isoformat(timespec="seconds"))
        return store.get_decision(pid, trade_date) or {}

    _emit(progress, f"上下文就绪：持仓 {len(ctx.get('positions') or [])} 只 · "
                    f"快讯 {len((ctx.get('news') or {}).get('market') or [])} 条 · "
                    f"候选 {(ctx.get('candidates') or {}).get('picks') and len(ctx['candidates']['picks']) or 0} 只", 25)

    agent = TraderAgent(int(profile["account_id"]), pid,
                        risk_rules=profile.get("risk_rules"))
    result = agent.decide(ctx, progress=lambda m: _emit(progress, m))

    if result.get("error"):
        store.upsert_decision(
            pid, trade_date, status="error", error=result["error"],
            thinking=result.get("thinking") or "", reflection=result.get("reflection") or "",
            context=ctx, news=(ctx.get("news") or {}), plan=result.get("orders") or [],
            finished_at=datetime.now().isoformat(timespec="seconds"))
        _emit(progress, f"决策失败：{result['error']}")
        return store.get_decision(pid, trade_date) or {}

    plan = result.get("orders") or []
    _emit(progress, f"决策已生成：{'保持现状' if not plan else f'{len(plan)} 笔委托'}", 70)

    executions = []
    if dry_run:
        executions = [{"code": o.get("code"), "side": o.get("side"), "qty": o.get("qty"),
                       "ok": False, "detail": "dry_run 未执行"} for o in plan]
    else:
        executions = _execute_orders(profile, plan, progress, decision_id=decision_id)

    # 记录操盘手主动写入的长期记忆
    for n in result.get("notes") or []:
        if n.get("content"):
            store.add_memory(pid, n["content"], kind=n.get("kind", "note"),
                             code=n.get("code") or "", decision_id=decision_id)

    # 净值快照 + 变化
    nav_after = ta_after = None
    try:
        eng = TradeEngine()
        snap = eng.snapshot_nav(int(profile["account_id"]), trade_date)
        nav_after = (snap or {}).get("nav")
        s2 = eng.get_summary(int(profile["account_id"])) or {}
        ta_after = float(s2.get("total_assets", 0))
    except Exception:
        pass

    store.upsert_decision(
        pid, trade_date, status="done",
        thinking=result.get("thinking") or "", reflection=result.get("reflection") or "",
        context=ctx, news=(ctx.get("news") or {}), plan=plan, executions=executions,
        nav_before=nav_before, nav_after=nav_after,
        total_assets_before=ta_before, total_assets_after=ta_after,
        error="", finished_at=datetime.now().isoformat(timespec="seconds"))
    _emit(progress, f"✓ 决策完成，净值 {nav_before} → {nav_after}", 100)
    return store.get_decision(pid, trade_date) or {}
