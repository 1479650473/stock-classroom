# -*- coding: utf-8 -*-
"""纵向回放 —— 让交易员在过去的数据里逐日做模拟，无前视。

设计要点：
- **数据隔离**：所有输入都按 `as_of` 截断（K线 date<=D、regime 用截止D的沪深300、
  因子候选 score_batch(ref_date=D)、持仓价格取 D 收盘），回放期间绝不调用实时行情/当日新闻。
  历史新闻不可回溯，回放上下文明确标注「新闻不可用」。
- **逐日循环**：每个交易日给模型当天的账户/持仓/行情/候选/记忆 → 决策 → 按当日价成交
  → 结算净值 → 进入下一日。
- **上下文压缩**：只注入最近若干日决策 + 阶段总结（每 N 日由 LLM 生成一次，kind='stage'），
  长期记忆用 style/thesis/lesson/note，避免 prompt 随天数无限膨胀。
- **可续跑**：游标存 profile.meta.cursor，每次最多跑 30 个交易日。
- **经验回流**：回放产生的风格/教训/笔记可提炼写入源交易员，供实盘模拟盘使用。

说明：LLM 训练数据可能包含那段历史行情（模型"记得"），本模块保证不喂未来数据，
但无法消除模型自身记忆带来的前视，这是 LLM 回测的固有限制。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from ..api.paths import DATA_DIR, KLINE_DB
from ..trade_engine.engine import TradeEngine
from . import account as acct_mod
from . import store
from .agent import TraderAgent

CAL_FILE = os.path.join(DATA_DIR, "trade_calendar.json")
HS300_PATH = os.path.join(DATA_DIR, "hs300.json")
SUMMARY_EVERY = 20      # 每 N 个交易日生成一次阶段总结
REVIEW_EVERY = 3        # 每 N 个交易日强制做一次绩效自省（写入 lesson/style/rules）
REVIEW_DD_PCT = 8.0     # 累计回撤超过该值也强制自省
REVIEW_TRADE_LOSS_PCT = 5.0   # 单笔平仓亏损超过该比例立即自省
MAX_BATCH = 30          # 单次回放最多天数


def _emit(progress, msg, pct=None):
    if not progress:
        return
    try:
        progress({"msg": msg, "pct": pct} if pct is not None else {"msg": msg})
    except Exception:
        pass


def _event(progress, payload: dict):
    """直接推一个结构化事件给 SSE（jobman 会包成 {type:'progress', ts, **payload}）。"""
    if not progress:
        return
    try:
        progress(payload)
    except Exception:
        pass


# ───────────────────────── 交易日 / 历史数据 ─────────────────────────

def _calendar() -> list:
    try:
        with open(CAL_FILE, encoding="utf-8") as f:
            return [str(x) for x in json.load(f)]
    except Exception:
        return []


def _hs300() -> dict:
    try:
        with open(HS300_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {"dates": d.get("dates") or [], "closes": [float(x) for x in d.get("closes") or []]}
    except Exception:
        return {"dates": [], "closes": []}


def trading_days(start: str, end: Optional[str] = None, limit: int = MAX_BATCH) -> list:
    """start(含)之后、end(含)之前的前 limit 个交易日。无日历时用 hs300 日期兜底。"""
    cal = [d for d in _calendar() if d >= start and (not end or d <= end)]
    if not cal:
        cal = [d for d in _hs300()["dates"] if d >= start and (not end or d <= end)]
    return cal[:limit]


def _close_asof(code: str, as_of: str) -> Optional[float]:
    """某股票在 as_of（含）之前的最近收盘价。"""
    try:
        con = sqlite3.connect(KLINE_DB)
        row = con.execute(
            "SELECT close FROM kline_daily WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (str(code), str(as_of).replace("-", ""))).fetchone()
        con.close()
        return float(row[0]) if row and row[0] else None
    except Exception:
        return None


def _regime_asof(as_of: str) -> dict:
    hs = _hs300()
    dates = [d for d in hs["dates"] if d <= as_of]
    closes = hs["closes"][:len(dates)]
    if len(closes) < 60:
        return {}
    try:
        from ..strategy.regime import classify
        r = classify(closes)
        return {
            "as_of": as_of, "regime": r.get("regime_cn") or r.get("regime"),
            "sys_risk": r.get("sys_risk", {}),
            "score": {k: r.get("score", {}).get(k) for k in ("px", "ma20", "ma60", "drawdown")},
        }
    except Exception:
        return {}


def _hs300_trend_asof(as_of: str) -> dict:
    hs = _hs300()
    idx = [i for i, d in enumerate(hs["dates"]) if d <= as_of]
    if not idx:
        return {}
    i = idx[-1]
    closes = hs["closes"][:i + 1]
    last = closes[-1]

    def chg(n):
        return round((last / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None
    return {"code": "sh000300", "name": "沪深300", "date": hs["dates"][i],
            "close": round(last, 2), "chg_1d": chg(1), "chg_5d": chg(5), "chg_20d": chg(20)}


# ───────────────────────── as-of 上下文 ─────────────────────────

def _account_block(account_id: int, as_of: str) -> dict:
    engine = acct_mod.trader_engine()
    positions = engine.get_positions(account_id)
    prices = {}
    for p in positions:
        px = _close_asof(p["code"], as_of)
        if px:
            prices[p["code"]] = {"price": px, "src": "close", "date": as_of}
    if prices:
        engine.update_all_prices(account_id, {c: v["price"] for c, v in prices.items()})
    s = engine.get_summary(account_id) or {}
    pos_rows = []
    for p in engine.get_positions(account_id):
        px = prices.get(p["code"], {})
        pos_rows.append({
            "code": p["code"], "name": p["name"], "qty": p["qty"],
            "cost_price": round(float(p["cost_price"]), 3),
            "price": round(float(p["current_price"]), 3),
            "market_value": round(float(p["market_value"]), 2),
            "float_pnl": round(float(p["float_pnl"]), 2),
            "float_pnl_pct": round((float(p["current_price"]) / float(p["cost_price"]) - 1) * 100, 2)
            if p["cost_price"] else 0.0,
            "last_buy_date": p.get("last_buy_date") or "",
            "price_src": px.get("src", ""),
        })
    pos_rows.sort(key=lambda x: x["market_value"], reverse=True)
    pending = [{"order_id": o["id"], "code": o["code"], "name": o["name"], "side": o["side"],
                "price": round(float(o["price"]), 3), "qty": o["qty"]}
               for o in engine.get_orders(account_id, "pending")]
    nav = engine.get_nav_history(account_id) or {}
    nav_rows = [{"date": d, "nav": n, "total_assets": ta}
                for d, n, ta in zip(nav.get("dates", []), nav.get("nav", []), nav.get("total_assets", []))
                if d <= as_of]
    return {
        "summary": {
            "total_assets": round(float(s.get("total_assets", 0)), 2),
            "balance": round(float(s.get("balance", 0)), 2),
            "frozen": round(float(s.get("frozen", 0)), 2),
            "market_value": round(float(s.get("market_value", 0)), 2),
            "float_pnl": round(float(s.get("float_pnl", 0)), 2),
            "total_profit": round(float(s.get("total_profit", 0)), 2),
            "total_profit_pct": round(float(s.get("total_profit_pct", 0)), 2),
            "initial_capital": round(float(s.get("initial_capital", 0)), 2),
            "positions": s.get("positions", 0),
            "pending_orders": s.get("pending_orders", 0),
        },
        "positions": pos_rows,
        "pending_orders": pending,
        "nav_history": nav_rows[-15:],
    }


def _candidates_block(as_of: str, top_n: int = 12, weights=None, source: str = "scorecard") -> dict:
    """回放候选池：按当日 as-of 截断，不附事件池（历史新闻不可回溯）。"""
    from .selection import build_snapshot
    return build_snapshot(as_of, top_n=top_n, with_events=False, weights=weights, source=source)


def _memory_block(profile_id: int, positions: list, account_id: int = 0,
                  as_of: Optional[str] = None) -> dict:
    decisions = store.list_decisions(profile_id, limit=6)
    if as_of:
        decisions = [d for d in decisions if (d.get("trade_date") or "") <= as_of]
    history = [{"date": d["trade_date"], "thinking": (d.get("thinking") or "")[:500],
                "reflection": (d.get("reflection") or "")[:200],
                "orders": d.get("plan") or [], "executions": d.get("executions") or [],
                "nav_after": d.get("nav_after")}
               for d in decisions if d.get("status") == "done"]
    mem = store.list_memory(profile_id, active_only=True, limit=80)
    theses, style, stages, notes = {}, "", [], []
    for m in mem:
        if m["kind"] == "thesis" and m.get("code") and m["code"] not in theses:
            theses[m["code"]] = m["content"]
        elif m["kind"] == "style" and not style:
            style = m["content"]
        elif m["kind"] == "stage":
            stages.append({"content": m["content"], "at": m["created_at"]})
        elif m["kind"] not in ("thesis", "style"):
            notes.append({"kind": m["kind"], "code": m.get("code") or "",
                          "content": m["content"], "at": m["created_at"]})
    held = [{"code": p["code"], "name": p["name"], "thesis": theses.get(p["code"], "")}
            for p in positions]
    perf = {}
    if account_id:
        try:
            from .performance import performance_block
            perf = performance_block(int(profile_id), int(account_id), as_of=as_of)
        except Exception:
            perf = {}
    return {"self_style": style, "recent_decisions": history, "holding_theses": held,
            "your_performance": perf,
            "stage_summaries": stages[:3], "notes": notes[:20]}


def build_replay_context(profile: dict, as_of: str) -> dict:
    account_id = int(profile["account_id"])
    weights = (profile.get("meta") or {}).get("weights")
    acct = _account_block(account_id, as_of)
    sel = str((profile.get("meta") or {}).get("selection") or "self")
    if sel == "self":
        from .context import _screen_dimensions
        cands = {"picks": [], "events": [], "mode": "self", "source": "self",
                 "chain": "自主选股：用 screen_stocks / get_stock_factors 自行检索市场（as-of 截断）",
                 "scope_note": {"口径": "自主选股（无预置候选池）",
                                "可用维度": {k: f"{v[0]}（{v[1]}）" for k, v in _screen_dimensions().items()},
                                "说明": "screen_stocks 已按当天 as-of 截断，不会用到未来数据。"}}
    else:
        cands = _candidates_block(as_of, weights=weights, source=sel)
    return {
        "generated_at": as_of,
        "mode": "replay",
        "account": acct["summary"],
        "positions": acct["positions"],
        "pending_orders": acct["pending_orders"],
        "nav_history": acct["nav_history"],
        "market": {"regime": _regime_asof(as_of), "hs300": _hs300_trend_asof(as_of)},
        "candidates": cands,
        "news": {"market": [], "stocks": [],
                 "note": "回放模式：历史新闻不可回溯，本日无新闻输入，仅凭行情/候选/宏观决策。"},
        "memory": _memory_block(int(profile["id"]), acct["positions"],
                                 account_id=account_id, as_of=as_of),
    }


# ───────────────────────── 创建 / 运行 ─────────────────────────

def create_replay(source_profile_id: int, start_date: str, days: int = MAX_BATCH,
                  initial_capital: Optional[float] = None,
                  model: Optional[str] = None,
                  weights=None) -> dict:
    """创建一个回放档案（独立账户 + 空记忆），并返回它。

    weights: 评分口径覆盖（预设名或 {组id:满分}），用于对照实验；None=默认口径。
    """
    store.ensure_schema()
    src = store.get_profile(int(source_profile_id))
    if src is None or src.get("kind") == "replay":
        raise ValueError("源交易员不存在或本身是回放档案")
    cap = float(initial_capital or src.get("initial_capital") or 100000)
    dates = trading_days(start_date, limit=max(1, int(days or MAX_BATCH)))
    if not dates:
        raise ValueError(f"{start_date} 之后没有可用交易日")
    name = f"回放·{src['name']}·{dates[0]}"
    engine = TradeEngine()
    aid = int(engine.create_account(name, cap))
    meta = {
        "source_profile_id": int(src["id"]),
        "source_name": src["name"],
        "start_date": dates[0],
        "planned_days": int(days or MAX_BATCH),
        "cursor": dates[0],
        "done_days": 0,
        "status": "ready",
        "initial_capital": cap,
        "note": "回放档案：无前视逐日模拟，新闻不可用",
    }
    from ..factor_engine.config import resolve_weights
    wspec = weights if isinstance(weights, str) else None
    wover = resolve_weights(weights)
    if wover and wspec:
        meta["weights"] = wspec
    elif wover:
        meta["weights"] = wover
    if wover:
        name = f"回放[{wspec or '自定义权重'}]·{src['name']}·{dates[0]}"
        try:
            engine.rename_account(aid, name)
        except Exception:
            pass
    prof = store.create_profile(
        account_id=aid, name=name, initial_capital=cap, persona="",
        model=(model if model is not None else (src.get("model") or "")),
        risk_rules=src.get("risk_rules") or {}, kind="replay", meta=meta)
    store.update_profile(int(prof["id"]), enabled=0)
    return store.get_profile(int(prof["id"]))


def _today_loss_trades(ctx: dict, execs: list) -> list:
    """今日平仓且亏损超过阈值的交易（用于触发立即自省）。"""
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
        if pct <= -REVIEW_TRADE_LOSS_PCT:
            out.append({"code": e.get("code"), "name": e.get("name"), "pnl_pct": round(pct, 2)})
    return out


def _settle_pending(engine: TradeEngine, account_id: int, as_of: str) -> None:
    """当日开盘：用当日收盘价检查此前挂着的限价单能否成交。"""
    for o in engine.get_orders(account_id, "pending"):
        px = _close_asof(o["code"], as_of)
        if px:
            try:
                engine.check_orders(account_id, o["code"], px, trade_date=as_of)
            except Exception:
                pass


def _summarize(llm, decisions: list) -> str:
    """把一段回放决策压缩成阶段总结。"""
    lines = []
    for d in decisions:
        acts = "、".join(f"{o.get('side')}{o.get('code')}x{o.get('qty')}" for o in (d.get("plan") or [])) or "无操作"
        lines.append(f"{d.get('trade_date')} 净值{d.get('nav_after')} 操作:{acts} 复盘:{(d.get('reflection') or '')[:120]}")
    text = "\n".join(lines)
    try:
        return llm.complete(
            "你是交易复盘助手。把下面的逐日交易记录压缩成一段 200 字以内的阶段性总结，"
            "保留：风格演变、有效/无效的判断、需要记住的教训。只输出总结正文。",
            text, max_tokens=500, temperature=0.4)
    except Exception:
        return ""


def _active_rule_texts(pid: int, as_of: str) -> list:
    """当前生效的纪律规则（给前端/轨迹用）。"""
    try:
        from .discipline import active_rules, describe_rules
        return describe_rules(active_rules(int(pid), as_of))
    except Exception:
        return []


def _review_trader(llm, pid: int, perf: dict, decisions: list, as_of: str) -> dict:
    """强制自省：把战绩 + 最近决策原文交给模型，产出教训与风格并写入长期记忆。"""
    from .performance import review_trader
    return review_trader(llm, perf, decisions)


def run_replay_batch(run_id: int, days: int = MAX_BATCH,
                     progress: Optional[Callable] = None) -> dict:
    """执行一个回放批次（默认 30 个交易日），可反复调用来续跑。"""
    store.ensure_schema()
    profile = store.get_profile(int(run_id))
    if profile is None or profile.get("kind") != "replay":
        return {"status": "error", "error": "回放档案不存在"}
    pid = int(profile["id"])
    account_id = int(profile["account_id"])
    meta = dict(profile.get("meta") or {})
    cursor = meta.get("cursor") or meta.get("start_date")
    dates = trading_days(cursor, limit=max(1, int(days or MAX_BATCH)))
    if not dates:
        meta["status"] = "finished"
        store.update_profile(pid, meta=meta)
        return {"status": "finished", "done": 0, "message": "没有更多交易日"}

    engine = acct_mod.trader_engine()
    llm = None
    try:
        from ..agent.llm_client import LLMClient
        llm = LLMClient(model=profile.get("model") or None)
    except Exception:
        llm = None

    done = 0
    _emit(progress, f"回放 {dates[0]} → {dates[-1]}（{len(dates)} 个交易日）", 1)
    for i, d in enumerate(dates, 1):
        # 1) 先按当日价撮合历史挂单
        _settle_pending(engine, account_id, d)
        # 挂单超时：与实盘同一套规则（历史日 as-of）
        expired_today: list = []
        try:
            from .discipline import expire_pending_orders
            expired_today = expire_pending_orders(engine, pid, account_id, d)
        except Exception:
            expired_today = []
        # 2) 建决策记录
        store.upsert_decision(pid, d, status="running", trigger="replay",
                              error="", finished_at=None)
        row = store.get_decision(pid, d) or {}
        decision_id = row.get("id")
        # 3) as-of 上下文（无前视）
        try:
            ctx = build_replay_context(profile, d)
        except Exception as e:
            store.upsert_decision(pid, d, status="error", error=f"上下文构建失败: {e}",
                                  finished_at=datetime.now().isoformat(timespec="seconds"))
            continue
        _emit(progress, f"[{i}/{len(dates)}] {d} 决策中… 持仓{len(ctx.get('positions') or [])}只", 5 + int(90 * i / len(dates)))
        _event(progress, {"event": "day_start", "date": d, "index": i, "total": len(dates),
                          "account": ctx.get("account"), "positions": ctx.get("positions"),
                          "candidates": ctx.get("candidates"),
                          "performance": (ctx.get("memory") or {}).get("your_performance")})
        # 4) 模型决策（date-aware 工具，流式输出）
        agent = TraderAgent(
            account_id, pid, risk_rules=profile.get("risk_rules"),
            decision_id=decision_id, model=profile.get("model") or None,
            trade_date=d, price_fn=lambda c, _d=d: _close_asof(c, _d), llm=llm,
            weights=(profile.get("meta") or {}).get("weights"))
        result = agent.decide(ctx, on_event=lambda e: _event(progress, e))
        # 4b) 系统兜底保护：模型不卖的，系统按纪律规则强制卖（止损/移动止损）
        forced = []
        try:
            from .discipline import enforce_protection
            forced = enforce_protection(engine, pid, account_id, d,
                                        price_fn=lambda c, _d=d: _close_asof(c, _d),
                                        trade_date=d,
                                        emit=lambda m: _emit(progress, m))
        except Exception as e:
            _emit(progress, f"持仓保护跳过：{e}")
        decisions_today = agent.tools.executions or []
        if forced:
            agent.tools.plan = list(agent.tools.plan) + forced
            agent.tools.executions = list(agent.tools.executions) + forced
            _event(progress, {"event": "protection", "date": d, "orders": forced})
        # 5) 落库 + 净值结算
        try:
            snap = engine.snapshot_nav(account_id, d)
            nav_after = (snap or {}).get("nav")
            s2 = engine.get_summary(account_id) or {}
        except Exception:
            nav_after, s2 = None, {}
        store.upsert_decision(
            pid, d, status=("error" if (result.get("error") and not (result.get("thinking") or agent.tools.plan)) else "done"),
            thinking=result.get("thinking") or "", reflection=result.get("reflection") or "",
            outlook=result.get("outlook") or {},
            gates=(ctx.get("protocol") or {}),
            context=ctx, candidates=ctx.get("candidates") or {}, news=ctx.get("news") or {},
            plan=agent.tools.plan,
            executions=agent.tools.executions, trace=result.get("trace") or [],
            rejections=agent.tools.rejections,
            expired=expired_today,
            nav_after=nav_after, total_assets_after=float(s2.get("total_assets", 0) or 0),
            error=result.get("error") or "", finished_at=datetime.now().isoformat(timespec="seconds"))
        # 预测打分：把此前没结算的预测用"已发生的净值"补上（当日预测要等次日才算得出）
        try:
            from . import outlook as outlook_mod
            outlook_mod.score_pending(pid, limit=10)
        except Exception:
            pass
        for n in result.get("notes") or []:
            if n.get("content"):
                store.add_memory(pid, n["content"], kind=n.get("kind", "note"),
                                 code=n.get("code") or "", decision_id=decision_id)
        done += 1
        # 5b) 当日结算事件（前端据此刷新净值/持仓/曲线 + 渲染结算卡片）
        pos_rows = engine.get_positions(account_id)
        _event(progress, {
            "event": "settled", "date": d, "nav": nav_after,
            "assets_before": float((ctx.get("account") or {}).get("total_assets", 0) or 0),
            "total_assets": float(s2.get("total_assets", 0) or 0),
            "balance": float(s2.get("balance", 0) or 0),
            "positions": len(pos_rows),
            "positions_detail": [{
                "code": p.get("code"), "name": p.get("name") or "", "qty": p.get("qty"),
                "cost_price": p.get("cost_price"), "price": p.get("current_price"),
                "float_pnl": p.get("float_pnl"),
                "pnl_pct": (round((p.get("current_price") or 0) / p.get("cost_price") - 1, 4)
                            if p.get("cost_price") else None),
            } for p in pos_rows],
            "plan": agent.tools.plan, "executions": agent.tools.executions,
            "thinking": result.get("thinking") or "", "reflection": result.get("reflection") or "",
            "error": result.get("error") or "",
            "rejections": agent.tools.rejections,
            "rules": [x["text"] for x in _active_rule_texts(pid, d)],
        })
        # 6) 每 N 日压缩一次阶段总结 + 强制绩效自省（自我提升闭环：战绩 → 教训/风格/纪律规则）
        if llm is not None:
            perf = (ctx.get("memory") or {}).get("your_performance") or {}
            dd = abs(float(((perf.get("nav") or {}).get("max_drawdown_pct")) or 0))
            bad_trades = _today_loss_trades(ctx, agent.tools.executions)
            need_review = (done % REVIEW_EVERY == 0) or (dd >= REVIEW_DD_PCT) or bool(bad_trades)
            if need_review:
                why = ("单笔亏损触发" if bad_trades else
                       ("回撤触发" if dd >= REVIEW_DD_PCT else f"每 {REVIEW_EVERY} 日定期"))
                _emit(progress, f"{d} 绩效自省中（{why} → 教训/风格/纪律规则）…", 96)
                rev = _review_trader(llm, pid, perf,
                                     list(reversed(store.list_decisions(pid, limit=REVIEW_EVERY))),
                                     d)
                if rev.get("error"):
                    _event(progress, {"event": "warning", "date": d, "message": rev["error"]})
                else:
                    for lesson in rev.get("lessons") or []:
                        store.add_memory(pid, lesson, kind="lesson", decision_id=decision_id)
                    if rev.get("style"):
                        store.add_memory(pid, rev["style"], kind="style", decision_id=decision_id)
                    rules = rev.get("rules") or []
                    if rules:
                        from .discipline import save_rules
                        save_rules(pid, rules, decision_id=decision_id)
                        for r in rules:
                            _emit(progress, f"纪律规则生效：{r.get('kind')} {r.get('value') or ''} {r.get('regimes') or ''} 至 {r.get('until')}")
                    store.upsert_decision(pid, d, review=rev)
                    _event(progress, {"event": "review", "date": d, "trigger": why,
                                      "self_critique": rev.get("self_critique") or "",
                                      "lessons": rev.get("lessons") or [],
                                      "style": rev.get("style") or "",
                                      "rules": [x["text"] for x in _active_rule_texts(pid, d)],
                                      "performance": perf})
            if done % SUMMARY_EVERY == 0:
                recent = store.list_decisions(pid, limit=SUMMARY_EVERY)
                summary = _summarize(llm, list(reversed(recent)))
                if summary:
                    store.add_memory(pid, summary, kind="stage")
                    _emit(progress, f"已生成阶段总结（{d}）", 97)
        # 7) 推进游标
        nxt = trading_days(d, limit=2)
        meta["cursor"] = nxt[1] if len(nxt) > 1 else d
        meta["done_days"] = int(meta.get("done_days") or 0) + 1
        meta["status"] = "running"
        store.update_profile(pid, meta=meta)
        _event(progress, {"event": "day_end", "date": d,
                          "cursor": meta.get("cursor"), "done_days": meta.get("done_days")})

    meta["status"] = "ready"
    store.update_profile(pid, meta=meta)
    _event(progress, {"event": "run_state", "cursor": meta.get("cursor"),
                      "done_days": meta.get("done_days"), "status": "ready"})
    _emit(progress, f"✓ 回放批次完成，本批 {done} 天", 100)
    return {"status": "ok", "done": done, "from": dates[0], "to": dates[-1],
            "cursor": meta.get("cursor")}


# ───────────────────────── 经验回流 ─────────────────────────

def distill_to_live(run_id: int, target_profile_id: int,
                    kinds=("style", "lesson", "note", "market")) -> dict:
    """把回放产生的风格/教训/笔记提炼写入目标（实盘）交易员，带来源标记。"""
    run = store.get_profile(int(run_id))
    target = store.get_profile(int(target_profile_id))
    if run is None or run.get("kind") != "replay":
        return {"error": "回放档案不存在"}
    if target is None or target.get("kind") == "replay":
        return {"error": "目标交易员不存在或为回放档案"}
    mem = store.list_memory(int(run_id), active_only=True, limit=200)
    src_name = (run.get("meta") or {}).get("source_name") or run.get("name")
    copied = []
    for m in mem:
        if m["kind"] not in kinds or not m.get("content"):
            continue
        content = f"[回放经验·{src_name}] {m['content']}"
        store.add_memory(int(target_profile_id), content, kind=m["kind"],
                         code=m.get("code") or "")
        copied.append(m["kind"])
    return {"copied": len(copied), "target": target.get("name"), "kinds": sorted(set(copied))}
