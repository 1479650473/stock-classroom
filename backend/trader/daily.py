# -*- coding: utf-8 -*-
"""每日决策编排 —— 构建上下文 → LLM 操盘手直接操作交易系统 → 落长期记忆。

入口：run_daily_decision()。被两条路径调用：
  ① update_daily.py 末尾（数据更新后自动跑，非交易日跳过）
  ② /api/trader/run（页面手动补跑 / 调试）

下单由 TraderTools.place_order 直接调用交易引擎完成（模拟券商软件），
交易系统自行校验资金与规则并返回结果；本模块只负责上下文、记录与净值快照。

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

    # 挂单超时：先把挂了太久没成交的限价单撤掉，再让模型看到"干净的委托本"
    # （借鉴 PA_Agent 的 pending 过期；陈旧挂单会占额度、也会让模型误以为已经在下单）
    if not dry_run:
        try:
            from .discipline import expire_pending_orders
            expired = expire_pending_orders(TradeEngine(), pid, int(profile["account_id"]), trade_date)
        except Exception as e:
            expired = []
            _emit(progress, f"挂单超时检查跳过：{e}")
        if expired:
            store.upsert_decision(pid, trade_date, expired=expired)
            _emit(progress, f"挂单超时：系统撤销 {len(expired)} 笔陈旧挂单", 12)

    _emit(progress, "构建决策上下文（账户/持仓/市场/候选/新闻/记忆）…", 14)

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
                        risk_rules=profile.get("risk_rules"),
                        decision_id=decision_id, dry_run=dry_run,
                        model=profile.get("model") or None,
                        weights=(profile.get("meta") or {}).get("weights"))
    result = agent.decide(ctx, progress=lambda m: _emit(progress, m))

    # 委托与执行由工具直接产生（大模型操作交易系统的真实结果）
    plan = agent.tools.plan
    executions = agent.tools.executions

    if result.get("error") and not (result.get("thinking") or agent.tools.plan):
        store.upsert_decision(
            pid, trade_date, status="error", error=result["error"],
            thinking=result.get("thinking") or "", reflection=result.get("reflection") or "",
            context=ctx, news=(ctx.get("news") or {}), plan=plan, executions=executions,
            finished_at=datetime.now().isoformat(timespec="seconds"))
        _emit(progress, f"决策失败：{result['error']}")
        return store.get_decision(pid, trade_date) or {}

    filled = sum(1 for e in executions if e.get("ok") and "已成交" in str(e.get("detail") or ""))
    _emit(progress, f"决策完成：{len(plan)} 笔委托，成交 {filled} 笔", 75)

    # 记录操盘手主动写入的长期记忆
    for n in result.get("notes") or []:
        if n.get("content"):
            store.add_memory(pid, n["content"], kind=n.get("kind", "note"),
                             code=n.get("code") or "", decision_id=decision_id)

    # 收盘兜底保护：模型不卖的，系统按纪律规则强制卖（止损/移动止损）
    if not dry_run:
        forced: list = []
        try:
            from .discipline import enforce_protection
            from .replay import _close_asof
            forced = enforce_protection(
                TradeEngine(), pid, int(profile["account_id"]), trade_date,
                price_fn=lambda c: _close_asof(c, trade_date),
                trade_date=trade_date, emit=lambda m: _emit(progress, m))
        except Exception as e:
            _emit(progress, f"持仓保护跳过：{e}")
        if forced:
            plan = list(plan) + forced
            executions = list(executions) + forced
            _emit(progress, f"系统保护卖出 {sum(1 for f in forced if f.get('ok'))} 笔")

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
        context=ctx, candidates=(ctx.get("candidates") or {}),
        news=(ctx.get("news") or {}), plan=plan, executions=executions,
        rejections=agent.tools.rejections, trace=result.get("trace") or [],
        nav_before=nav_before, nav_after=nav_after,
        total_assets_before=ta_before, total_assets_after=ta_after,
        error="", finished_at=datetime.now().isoformat(timespec="seconds"))
    _emit(progress, f"✓ 决策完成，净值 {nav_before} → {nav_after}", 100)

    # 绩效自省（周五 / 每隔 N 日 / 回撤超阈值 / 单笔亏损超阈值）：产出 lesson/style/纪律规则
    try:
        _maybe_review(pid, trade_date, profile, progress, ctx=ctx, execs=executions)
    except Exception as e:
        _emit(progress, f"绩效自省跳过：{e}")
    return store.get_decision(pid, trade_date) or {}


def _maybe_review(pid: int, trade_date: str, profile: dict,
                  progress: Optional[Callable] = None,
                  dd_threshold: float = 8.0, every_days: int = 3,
                  ctx: Optional[dict] = None, execs: Optional[list] = None) -> dict:
    """自我提升闭环：定期（或回撤超阈值、单笔亏损超阈值）把真实战绩交给 LLM 自省。

    自省产出三样东西：lesson（教训）、style（风格）、**rules（纪律规则，引擎强制执行）**。
    """
    from ..agent.llm_client import LLMClient
    from .performance import performance_block, review_trader

    perf = performance_block(pid, int(profile["account_id"]))
    dd = abs(float(((perf.get("nav") or {}).get("max_drawdown_pct")) or 0))
    days = int(perf.get("decision_days") or 0)
    weekly = datetime.strptime(trade_date, "%Y-%m-%d").isoweekday() == 5
    bad = _loss_trades(ctx or {}, execs or [])
    if not (weekly or dd >= dd_threshold or bad or (every_days and days % every_days == 0)):
        return {}
    if not (perf.get("trading") or perf.get("nav")):
        return {}
    why = ("单笔亏损触发" if bad else ("回撤触发" if dd >= dd_threshold
           else ("周五复盘" if weekly else f"每 {every_days} 日定期")))
    _emit(progress, f"绩效自省中（{why} → 教训/风格/纪律规则）…", 90)
    llm = LLMClient(model=profile.get("model") or None)
    rev = review_trader(llm, perf, list(reversed(store.list_decisions(pid, limit=every_days))))
    if rev.get("error"):
        _emit(progress, rev["error"])
        return rev
    for lesson in rev.get("lessons") or []:
        store.add_memory(pid, lesson, kind="lesson")
    if rev.get("style"):
        store.add_memory(pid, rev["style"], kind="style")
    rules = rev.get("rules") or []
    if rules:
        try:
            from .discipline import save_rules
            save_rules(pid, rules)
        except Exception as e:
            _emit(progress, f"纪律规则写入失败：{e}")
    store.upsert_decision(pid, trade_date, review=rev)
    _emit(progress, f"已写入自省：{len(rev.get('lessons') or [])} 条教训、{len(rules)} 条纪律规则")
    return rev


def _loss_trades(ctx: dict, execs: list) -> list:
    """今日平仓且单笔亏损 ≥5% 的交易（触发立即自省）。"""
    costs = {str(p.get("code")): float(p.get("cost_price") or 0)
             for p in (ctx.get("positions") or [])}
    out = []
    for e in execs or []:
        if not isinstance(e, dict) or not e.get("ok"):
            continue
        if str(e.get("side")).lower() != "sell":
            continue
        cost = costs.get(str(e.get("code")))
        px = float(e.get("price") or 0)
        if not cost or not px:
            continue
        pct = (px / cost - 1) * 100
        if pct <= -5.0:
            out.append({"code": e.get("code"), "name": e.get("name"), "pnl_pct": round(pct, 2)})
    return out


def run_all_daily_decisions(trigger: str = "manual", force: bool = False,
                            dry_run: bool = False, with_candidates: bool = True,
                            with_news: bool = True,
                            progress: Optional[Callable] = None) -> list:
    """对所有启用的交易员逐个跑一次决策（同日已 done 且非 force 则跳过）。"""
    store.ensure_schema()
    profiles = [p for p in store.list_profiles() if p.get("enabled")]
    if not profiles:
        _emit(progress, "没有启用的交易员")
        return []
    results = []
    for i, p in enumerate(profiles, 1):
        _emit(progress, f"[{i}/{len(profiles)}] {p.get('name')} 决策中…")
        r = run_daily_decision(
            profile_id=int(p["id"]), trigger=trigger, force=force, dry_run=dry_run,
            with_candidates=with_candidates, with_news=with_news,
            progress=lambda m: _emit(progress, f"[{p.get('name')}] " + (m.get("msg") if isinstance(m, dict) else str(m))))
        results.append({"profile": p.get("name"), "profile_id": p.get("id"),
                        "status": r.get("status"), "error": r.get("error")})
        _emit(progress, f"[{i}/{len(profiles)}] {p.get('name')} → {r.get('status')}")
    return results
