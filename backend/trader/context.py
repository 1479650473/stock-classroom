# -*- coding: utf-8 -*-
"""每日决策上下文构建。

把操盘手做决策需要的一切(账户/持仓/净值/市场/候选/新闻/历史记忆)整理成
一个紧凑的 dict，既注入 LLM 提示，也原样存入 trader_decision.context 供页面回看。

外部依赖(实时行情/新闻/选股)全部短超时 + 失败降级，绝不阻塞决策。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from ..api.paths import DATA_DIR, KLINE_DB
from ..trade_engine.engine import TradeEngine
from . import news as news_mod
from . import store

REGIME_PATH = os.path.join(DATA_DIR, "regime.json")
NEWS_DRIVEN_PATH = os.path.join(DATA_DIR, "news_driven.json")
HS300_PATH = os.path.join(DATA_DIR, "hs300.json")


# ───────────────────────── 价格 ─────────────────────────

def _kline_latest_close(codes: List[str]) -> dict:
    out = {}
    try:
        con = sqlite3.connect(KLINE_DB)
        con.row_factory = sqlite3.Row
        for c in codes:
            row = con.execute(
                "SELECT date, close FROM kline_daily WHERE code=? ORDER BY date DESC LIMIT 1",
                (c,)).fetchone()
            if row:
                out[c] = {"price": float(row["close"]), "date": str(row["date"]), "src": "kline"}
        con.close()
    except Exception:
        pass
    return out


def refresh_prices(codes: List[str]) -> dict:
    """批量取价：优先实时(新浪)，失败回退 kline 最新收盘。返回 {code: {price,date,src}}。"""
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    out = {}
    try:
        from ..data_manager import fetch_realtime_prices
        for r in fetch_realtime_prices(codes) or []:
            p = r.get("price")
            if p:
                out[str(r.get("code"))] = {"price": float(p),
                                           "change_pct": float(r.get("change_pct") or 0),
                                           "src": "realtime"}
    except Exception:
        pass
    missing = [c for c in codes if c not in out]
    if missing:
        out.update(_kline_latest_close(missing))
    return out


def _days_since(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    s = str(date_str).replace("-", "")[:8]
    try:
        d = datetime.strptime(s, "%Y%m%d")
    except Exception:
        return None
    return (datetime.now() - d).days


# ───────────────────────── 账户/持仓 ─────────────────────────

def build_account_block(account_id: int) -> dict:
    engine = TradeEngine()
    positions = engine.get_positions(account_id)
    prices = refresh_prices([p["code"] for p in positions])
    if prices:
        engine.update_all_prices(
            account_id, {c: v["price"] for c, v in prices.items() if v.get("price")})
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
            "float_pnl_pct": round(
                (float(p["current_price"]) / float(p["cost_price"]) - 1) * 100, 2)
            if p["cost_price"] else 0.0,
            "last_buy_date": p.get("last_buy_date") or "",
            "holding_days": _days_since(p.get("last_buy_date")),
            "price_src": px.get("src", ""),
        })
    pos_rows.sort(key=lambda x: x["market_value"], reverse=True)
    pending = [{
        "order_id": o["id"], "code": o["code"], "name": o["name"],
        "side": o["side"], "price": round(float(o["price"]), 3),
        "qty": o["qty"], "created_at": o["created_at"],
    } for o in engine.get_orders(account_id, "pending")]
    nav = engine.get_nav_history(account_id) or {}
    nav_rows = [{"date": d, "nav": n, "total_assets": ta}
                for d, n, ta in zip(nav.get("dates", []), nav.get("nav", []),
                                    nav.get("total_assets", []))]
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
        "prices": prices,
    }


# ───────────────────────── 市场 ─────────────────────────

def _prices_for(codes: List[str]) -> dict:
    return refresh_prices(codes)


def _hs300_trend() -> dict:
    """沪深300 近端趋势（1/5/20 日涨跌）。"""
    try:
        with open(HS300_PATH, encoding="utf-8") as f:
            d = json.load(f)
        closes = [float(x) for x in d.get("closes") or []]
        dates = d.get("dates") or []
        if len(closes) < 2:
            return {}
        last = closes[-1]
        def chg(n):
            return round((last / closes[-1 - n] - 1) * 100, 2) if len(closes) > n else None
        return {"code": d.get("code"), "name": d.get("name"),
                "date": dates[-1] if dates else None, "close": round(last, 2),
                "chg_1d": chg(1), "chg_5d": chg(5), "chg_20d": chg(20)}
    except Exception:
        return {}


def build_market_block() -> dict:
    out = {}
    try:
        with open(REGIME_PATH, encoding="utf-8") as f:
            r = json.load(f)
        out["regime"] = {
            "as_of": r.get("as_of"), "regime": r.get("regime_cn") or r.get("regime"),
            "suggest_strategy": r.get("suggest_strategy"),
            "sys_risk": r.get("sys_risk", {}),
            "score": {k: r.get("score", {}).get(k) for k in ("px", "ma20", "ma60", "drawdown")},
        }
    except Exception:
        out["regime"] = {}
    out["hs300"] = _hs300_trend()
    return out


def _screen_dimensions() -> dict:
    try:
        from .screen import DIMENSIONS
        return DIMENSIONS
    except Exception:
        return {}


def build_candidates_block(top_n: int = 12, weights=None, source: str = "scorecard") -> dict:
    """候选池（实时）：多因子评分 Top N + 事件驱动池 + 完整选股链路口径。

    source='composite' 时改用固定权重因子组合（-1日反转/-5日反转/-远离60日高点/-小市值）。
    """
    from .selection import build_snapshot
    return build_snapshot(None, top_n=top_n, with_events=True, weights=weights, source=source)


# ───────────────────────── 新闻 ─────────────────────────

def build_news_block(positions: List[dict], picks: List[dict],
                     per_stock: int = 3, max_stocks: int = 6) -> dict:
    market = news_mod.market_news(limit=20)
    watch = []
    seen = set()
    for item in list(positions) + list(picks):
        c = str(item.get("code") or "")
        if not c or c in seen:
            continue
        seen.add(c)
        watch.append({"code": c, "name": item.get("name") or ""})
        if len(watch) >= max_stocks:
            break
    stock_items = []
    for w in watch:
        rows = news_mod.stock_news(w["code"], w["name"], limit=per_stock)
        if rows:
            stock_items.append({"code": w["code"], "name": w["name"], "news": rows})
    return {"market": market, "stocks": stock_items}


# ───────────────────────── 历史记忆 ─────────────────────────

def _ops_summary(plan: list, executions: list) -> str:
    """把当日委托压成一行（复用：历史日子不需要逐笔明细）。"""
    if not plan:
        return "无操作"
    parts = []
    for i, o in enumerate(plan[:6]):
        side = "买" if o.get("side") == "buy" else "卖"
        name = o.get("name") or o.get("code")
        res = ""
        try:
            e = (executions or [])[i] or {}
            res = "✓" if e.get("ok") else ("✗" if e.get("detail") else "")
        except Exception:
            res = ""
        parts.append(f"{side}{name}{res}")
    return "、".join(parts) + ("…" if len(plan) > 6 else "")


def build_memory_block(profile_id: int, positions: List[dict], limit: int = 10,
                       account_id: Optional[int] = None,
                       as_of: Optional[str] = None,
                       regime: str = "") -> dict:
    """历史决策：**近 3 日详细 + 更早压缩成一行**（增量复用思路）。

    每天都是一次全新对话，无法"只传增量"，所以省 token 的正确做法是压缩：
    近期保留思考/复盘/委托（模型需要延续判断），远期只留"日期 + 净值 + 操作 + 复盘一句"，
    该信息量足以让模型知道自己做过什么、结果如何，而 token 只占原来的 ~15%。
    """
    DETAIL_DAYS = 3
    decisions = [d for d in store.list_decisions(profile_id, limit=limit)
                 if d.get("status") == "done"]
    history = []
    for i, d in enumerate(decisions):
        if i < DETAIL_DAYS:
            history.append({
                "date": d["trade_date"],
                "thinking": (d.get("thinking") or "")[:520],
                "reflection": (d.get("reflection") or "")[:260],
                "orders": d.get("plan") or [],
                "executions": d.get("executions") or [],
                "nav_after": d.get("nav_after"),
                "outlook": (d.get("outlook") or {}).get("direction") if isinstance(d.get("outlook"), dict) else None,
                "outlook_hit": (d.get("outlook_score") or {}).get("hit") if isinstance(d.get("outlook_score"), dict) else None,
            })
        else:
            history.append({
                "date": d["trade_date"],
                "ops": _ops_summary(d.get("plan") or [], d.get("executions") or []),
                "nav_after": d.get("nav_after"),
                "reflection": (d.get("reflection") or "")[:90],
            })
    mem = store.list_memory(profile_id, active_only=True, limit=80)
    theses = {}
    style = ""
    for m in mem:
        if m["kind"] == "thesis" and m.get("code") and m["code"] not in theses:
            theses[m["code"]] = m["content"]
        elif m["kind"] == "style" and not style:
            style = m["content"]
    held = [{"code": p["code"], "name": p["name"], "thesis": theses.get(p["code"], "")}
            for p in positions]
    perf = {}
    if account_id:
        try:
            from .performance import performance_block
            perf = performance_block(int(profile_id), int(account_id), as_of=as_of)
        except Exception:
            perf = {}
    # 经验分桶：当前环境下的经验优先（熊市里最该看的是熊市教训，不是牛市心得）
    cur_regime = str(regime or "")[:20]
    notes_all = [{"kind": m["kind"], "code": m.get("code") or "",
                  "content": (m["content"] or "")[:220], "at": m["created_at"],
                  "regime": m.get("regime") or ""}
                 for m in mem if m["kind"] not in ("thesis", "style", "rule")]
    same = [n for n in notes_all if cur_regime and n["regime"] == cur_regime]
    other = [n for n in notes_all if not (cur_regime and n["regime"] == cur_regime)]
    notes_sorted = (same + other)[:12]
    # 上轮立场关系（首单/同向/反手/延续等待）：提示模型别来回横跳
    continuity = {}
    try:
        from . import continuity as cont_mod
        done = [d for d in store.list_decisions(profile_id, limit=4) if d.get("status") == "done"]
        if done:
            continuity = cont_mod.relation_of(done[0], done[1] if len(done) > 1 else None)
            continuity["上一轮操作"] = [f"{o.get('side')}{o.get('name') or o.get('code')}"
                                       for o in (done[0].get("plan") or [])][:6]
            continuity["上一轮净值"] = done[0].get("nav_after")
    except Exception:
        continuity = {}
    routing_block = {}
    try:
        from . import routing as routing_mod
        idx = routing_mod.classify_code("sh000300", str(as_of or __import__("datetime").date.today().isoformat()))
        holds = []
        for p in positions or []:
            c = str(p.get("code") or "")
            if not c:
                continue
            try:
                r = routing_mod.classify_code(c, str(as_of or __import__("datetime").date.today().isoformat()))
                holds.append({"code": c, "name": p.get("name") or c,
                              "分类": r.get("label"), "提示": (r.get("note") or "")[:120]})
            except Exception:
                continue
        routing_block = {"大盘分类": idx.get("label"), "大盘提示": (idx.get("note") or "")[:140],
                         "持仓分类": holds, "参考表": routing_mod.TABLE_TEXT}
    except Exception:
        routing_block = {}
    calib = {}
    try:
        from . import calibration as calib_mod
        rep = calib_mod.report(int(profile_id), days=180)
        if rep.get("n"):
            calib = {
                "样本": rep["n"],
                "原始ECE": rep.get("raw_ece"),
                "校准后ECE": rep.get("calibrated_ece"),
                "区分度": rep.get("discrimination"),
                "门槛建议": rep.get("gate"),
                "说明": "ECE 越低越好；校准后明显低于原始 = 你系统性过度自信。"
                        "置信度区分度弱时别拿它当行动门槛（Laya 的教训：模型读不懂输入时置信度不会报警）。",
            }
        # 小模型基线研究（sys1_market.json）：专门训练的小模型也预测不准明日方向 —— 用于约束自信
        try:
            import json as _json, os as _os
            from ..api.paths import DATA_DIR as _DD
            _p = _os.path.join(str(_DD), "sys1_market.json")
            if _os.path.exists(_p):
                _d = _json.load(open(_p, encoding="utf-8"))
                _h = (_d.get("models") or {}).get("hgb") or {}
                _lo = (_d.get("models") or {}).get("logistic") or {}
                calib["小模型基线"] = {
                    "说明": "我们专门训练的小模型（13 个指数/广度/北向特征）预测【次日大盘方向】的样本外成绩："
                            "它不是交易信号，而是校准你自己的参照 —— 连它都做不到的事，你的高置信同样可疑。",
                    "测试区间": f"{( _d.get('meta') or {}).get('test_from')}~{( _d.get('meta') or {}).get('test_to')}",
                    "逻辑回归命中": f"{_lo.get('hit_rate')}%",
                    "HGB命中": f"{_h.get('hit_rate')}%",
                    "多数类基线": f"{(_d.get('baselines') or {}).get('majority_class_share')}%",
                    "结论": "次日方向接近随机：小模型命中不如'永远猜多数类'；弃权门控也换不来命中率。"
                            "所以：别对明日方向给高置信，它的用途是校准你的判断力而非下注。",
                }
        except Exception:
            pass
    except Exception:
        calib = {}
    return {
        "self_style": style,
        "continuity": continuity,
        "your_calibration": calib,
        # 事件实证（2024+ 中小盘域样本外，裁尾口径）：给"追热点"提供负期望证据
        "event_evidence": _event_evidence(),
        "structure_routing": routing_block,
        "history_note": "近 3 个交易日逐条详细（含委托与结果）；更早的日子只给摘要"
                        "（日期/操作/净值/复盘一句）——需要细节用工具查或问自己写下的记忆。",
        "regime_bucket": {"当前环境": cur_regime or "未知",
                          "同环境经验条数": len(same),
                          "说明": "经验已按市场环境分桶：标 regime 的条目是写下时所处的环境，"
                                  "同环境经验排在最前，跨环境经验参考价值较低。"},
        "recent_decisions": history,
        "holding_theses": held,
        "your_performance": perf,
        "discipline_rules": _rules_block(int(profile_id), as_of),
        "notes": notes_sorted,
    }


def _event_evidence() -> dict:
    """事件研究结论（`data/experiments/event_study.json`，读不到就返回空）。

    为什么给模型看这个：它的风格偏动量/主题，而实证显示在该域该期间
    **所有"热点事件"后的 5 日都是负超额**。这是事实不是禁令 —— 模型仍可自主决定，
    但要基于事实，而不是"涨停说明很强"的直觉。
    """
    try:
        import json as _json
        import os as _os
        from ..api.paths import DATA_DIR as _DD
        p = _os.path.join(str(_DD), "experiments", "event_study.json")
        if not _os.path.exists(p):
            return {}
        d = _json.load(open(p, encoding="utf-8"))
        ev = d.get("events") or {}
        rows = {}
        for k in ("首板", "连板≥2", "跌停", "龙虎榜净买强"):
            v = ev.get(k)
            if not v:
                continue
            rows[k] = {
                "事件后5日超额": f"{v.get('exc_clip_pct')}%",
                "同分位对照": f"{v.get('ctrl_clip_pct')}%",
                "净效应": (f"{v.get('excess_over_matched_pct')}%" if v.get("excess_over_matched_pct") is not None else "n/a"),
                "样本": f"{v.get('n')} 例 / {v.get('days')} 天",
            }
        if not rows:
            return {}
        return {
            "口径": f"中小盘域（流动性排名 601~1800）、{d['meta']['range'][0]}~{d['meta']['range'][1]}、"
                    f"T+1 开盘买入持有 5 日、相对等权池超额（裁尾 ±20%）、已按同日 RET5 分位对照",
            "各事件": rows,
            "读法": "负的净效应 = 该事件后买入跑输同类（按动量匹配）的票。样本外只有两年多、"
                    "事件样本有限，别当成铁律；但「涨停=很强/跌停=超跌该反弹/龙虎榜净买=有资金」这类直觉"
                    "在这里**全都不成立**，追它之前请先想清楚理由。",
        }
    except Exception:
        return {}


def _rules_block(profile_id: int, as_of: Optional[str] = None) -> list:
    """当前生效的纪律规则（自省结论 → 系统强制执行，模型必须知道）。

    系统恒定规则也一并告诉模型（不是模型可改的），否则它会反复试探同一个被拒动作。
    """
    try:
        from .discipline import active_rules, describe_rules, protection_rules
        out = [x["text"] for x in describe_rules(active_rules(int(profile_id), as_of))]
        p = protection_rules(int(profile_id), as_of)
        out.append(f"系统恒定规则：卖出后 {int(p.get('sell_reentry_cooldown') or 0)} 个交易日内"
                   f"不得买回同一只；限价挂单 {int(p.get('pending_expiry_days') or 0)} 个交易日"
                   f"未成交将由系统撤销；浮亏 {float(p.get('stop_loss_pct') or 0):g}% 触发兜底止损")
        return out
    except Exception:
        return []


# ───────────────────────── 汇总 ─────────────────────────

def build_daily_context(profile: dict, with_candidates: bool = True,
                        with_news: bool = True) -> dict:
    """构建一次决策的完整上下文。"""
    account_id = int(profile["account_id"])
    weights = (profile.get("meta") or {}).get("weights")
    acct = build_account_block(account_id)
    market = build_market_block()
    meta = (profile or {}).get("meta", {}) if isinstance(profile, dict) else {}
    selection = str(meta.get("selection") or "self")          # self=模型自己选股（默认）
    scoring = str(meta.get("scoring") or "scorecard")
    if with_candidates and selection == "self":
        # 自主选股模式：不预先给候选池，避免"在别人选好的股里挑"；只给检索工具说明与市场概览。
        cands = {"picks": [], "events": [], "source": "self", "mode": "self",
                 "chain": "自主选股：模型用 screen_stocks / get_stock_factors 自行检索市场",
                 "scope_note": {
                     "口径": "自主选股（无预置候选池）",
                     "可用维度": {k: f"{v[0]}（{v[1]}）" for k, v in _screen_dimensions().items()},
                     "说明": "先想清楚你的选股标准，再用 screen_stocks 按维度筛选与排序；"
                             "对候选再用 get_stock_factors / get_stock_price / K线 验证后下单。",
                 }}
    else:
        cands = (build_candidates_block(weights=weights, source=scoring)
                 if with_candidates else {"picks": [], "events": []})
    news_block = (build_news_block(acct["positions"], cands.get("picks", []))
                  if with_news else {"market": [], "stocks": []})
    _reg = ""
    try:
        _r = (market or {}).get("regime") if isinstance(market, dict) else {}
        _reg = str((_r.get("regime_cn") or _r.get("regime")) if isinstance(_r, dict) else _r or "")[:20]
    except Exception:
        _reg = ""
    memory = build_memory_block(int(profile["id"]), acct["positions"],
                                account_id=int(profile["account_id"]), regime=_reg)
    # 编号决策协议（系统闸门已判定，模型只回答 [你] 的闸门）
    protocol_block = {}
    try:
        from . import protocol as protocol_mod
        latest = ""
        try:
            import sqlite3 as _sq
            from ..api.paths import KLINE_DB as _KDB
            _c = _sq.connect(str(_KDB))
            latest = str(_c.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0] or "")
            _c.close()
        except Exception:
            latest = ""
        protocol_block = protocol_mod.build_gates(
            int(profile["id"]), int(profile["account_id"]),
            str((profile.get("meta") or {}).get("as_of") or __import__("datetime").date.today().isoformat()),
            positions=acct["positions"], account=acct["summary"],
            regime=(market or {}).get("regime") if isinstance(market, dict) else {},
            data_latest=latest)
    except Exception as _e:
        protocol_block = {}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": {
            "name": profile.get("name"), "persona": profile.get("persona"),
            "risk_rules": profile.get("risk_rules") or {},
            "initial_capital": profile.get("initial_capital"),
        },
        "account": acct["summary"],
        "positions": acct["positions"],
        "pending_orders": acct["pending_orders"],
        "nav_history": acct["nav_history"],
        "market": market,
        "candidates": cands,
        "news": news_block,
        "memory": memory,
        "protocol": protocol_block,
        "prices": acct["prices"],
    }
