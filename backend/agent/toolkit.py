# -*- coding: utf-8 -*-
"""AI agent toolkit — function schemas + ToolExecutor for the Web agent chat.

交易/研究工具基于原桌面版能力迁移而来（frontend/ 已归档），并新增 Web 专属:
  策略类: get_strategies / backtest_strategy / describe_strategy / get_picks / get_regime

所有重度导入都在函数体内执行(与 API blueprints 一致的启动纪律).
"""
from __future__ import annotations

import sys
import os

if getattr(sys, "frozen", False):
    _PROJ = os.path.dirname(sys.executable)
else:
    _PROJ = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)


def _ai_account():
    from trade_engine.engine import TradeEngine
    engine = TradeEngine()
    accs = engine.list_accounts()
    for a in accs:
        if a["name"] == "AI账户":
            return a["id"]
    return engine.create_account("AI账户", 100000)


# ══════════════════════════ 交易类 (5) ══════════════════════════

def _do_get_account_summary():
    from trade_engine.engine import TradeEngine
    engine = TradeEngine()
    aid = _ai_account()
    s = engine.get_summary(aid)
    if s is None:
        return {"error": "账户不存在"}
    return {
        "总资产": round(float(s["total_assets"]), 2),
        "可用资金": round(float(s["balance"]), 2),
        "冻结资金": round(float(s["frozen"]), 2),
        "持仓市值": round(float(s["market_value"]), 2),
        "浮动盈亏": round(float(s["float_pnl"]), 2),
        "累计盈亏": round(float(s["total_profit"]), 2),
        "盈亏百分比": f"{float(s['total_profit_pct']):.2f}%",
        "持仓数": s["positions"],
        "待成交委托数": s["pending_orders"],
    }


def _do_get_positions():
    from trade_engine.engine import TradeEngine
    engine = TradeEngine()
    positions = engine.get_positions(_ai_account())
    if not positions:
        return {"message": "当前无持仓"}
    result = []
    for p in positions:
        result.append({
            "代码": p["code"],
            "名称": p["name"],
            "持仓量": p["qty"],
            "成本价": round(float(p["cost_price"]), 2),
            "现价": round(float(p["current_price"]), 2),
            "市值": round(float(p["market_value"]), 2),
            "浮动盈亏": round(float(p["float_pnl"]), 2),
        })
    return result


def _do_get_stock_price(code):
    from data_manager import fetch_realtime_prices
    try:
        results = fetch_realtime_prices([code])
        if results:
            r = results[0]
            return {
                "代码": r["code"],
                "名称": r.get("name", ""),
                "现价": r["price"],
                "涨跌幅(%)": round(float(r.get("change_pct", 0)), 2),
            }
        return {"error": f"未找到股票 {code}"}
    except Exception as e:
        return {"error": str(e)}


def _do_search_stock(keyword):
    import sqlite3
    kline_db = os.path.join(_PROJ, "data", "kline.db")
    try:
        conn = sqlite3.connect(kline_db)
        rows = conn.execute(
            "SELECT code, name FROM stock_list WHERE code LIKE ? OR name LIKE ? LIMIT 10",
            (f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()
        conn.close()
        if not rows:
            return {"message": f"未找到匹配 '{keyword}' 的股票"}
        return [{"代码": r[0], "名称": r[1]} for r in rows]
    except Exception as e:
        return {"error": str(e)}


def _do_place_order(code, name, side, order_type, price, qty):
    from trade_engine.engine import TradeEngine
    engine = TradeEngine()
    current_price = None
    if order_type == "market":
        from data_manager import fetch_realtime_prices
        results = fetch_realtime_prices([code])
        if results:
            current_price = results[0]["price"]
        else:
            return {"error": f"无法获取 {code} 实时价格, 无法下市价单"}
    order, result = engine.place_order(
        _ai_account(), code, name, side, order_type,
        price, qty, current_price=current_price,
    )
    if order is None:
        return {"error": result}
    if isinstance(result, dict):
        return {
            "状态": "已成交",
            "方向": "买入" if side == "buy" else "卖出",
            "代码": code,
            "名称": name,
            "价格": result["price"],
            "数量": result["qty"],
            "手续费": round(float(result["commission"]), 2),
            "印花税": round(float(result["stamp_tax"]), 2) if result.get("stamp_tax") else 0.0,
        }
    return {
        "状态": "已挂单",
        "方向": "买入" if side == "buy" else "卖出",
        "代码": code,
        "委托价": order["price"],
        "数量": order["qty"],
    }


def _do_cancel_order(order_id):
    from trade_engine.engine import TradeEngine
    engine = TradeEngine()
    ok, err = engine.cancel_order(order_id)
    if ok:
        return {"状态": "已撤单"}
    return {"error": err}


# ══════════════════════════ 研究类 (4) ══════════════════════════

def _research_worker(name: str, *a, **kw) -> dict:
    try:
        import importlib
        mod = importlib.import_module("backend.paper_worker")
        res = getattr(mod, name)(*a, **kw)
        return res if isinstance(res, dict) else {"result": res}
    except Exception as e:
        return {"error": str(e)}


def _do_research_value_factors():
    """研究价值因子(BP/EP/ROE)截面IC/ICIR, 返回推荐因子."""
    r = _research_worker("study_factors")
    if "error" in r:
        return r
    out = {"数据截止": r.get("as_of", ""), "池": r.get("pool_size", 0)}
    rec = r.get("recommended")
    if rec:
        out["推荐因子"] = {"因子": rec.get("dsl_key"), "IC": rec.get("ic"), "ICIR": rec.get("icir")}
    for f in ("BP", "EP", "ROE"):
        v = r.get(f)
        if v and "icir" in v:
            out[f] = {"IC": v["ic"], "ICIR": v["icir"], "IC正率": v["ic_positive"],
                      "单调性": v["monotonicity"], "多空净": v["long_short_net"]}
    return out


def _do_run_factor_backtest(factor="BP", holding_period=20):
    """单因子截面回测(wide池, 板块中性化). factor: BP/EP/ROE/MOMENTUM_20/REVERSAL_20/VOLATILITY_20."""
    r = _research_worker("run_backtest", factor=str(factor or "BP"),
                         holding_period=int(holding_period or 20))
    if "error" in r:
        return r
    return {"因子": r.get("factor"), "IC": r.get("ic"), "ICIR": r.get("icir"),
            "IC正率": r.get("ic_positive"), "单调性": r.get("monotonicity"),
            "多空(净)": r.get("multi_long_short"), "覆盖": r.get("coverage"),
            "分组净净值(1~5)": r.get("groups")}


def _do_get_portfolio_paper(hp=20):
    """组合纸面盘: 多因子重平衡净值 vs 基准, 返回收益/目标持仓."""
    r = _research_worker("build_paper_only", hp=int(hp or 20))
    if "error" in r:
        return r
    p = r.get("paper") or {}
    nav = p.get("nav") or []
    ret = (nav[-1] / nav[0] - 1) * 100 if len(nav) > 1 and nav[0] else 0.0
    bh = p.get("buyhold_nav") or []
    bh_ret = (bh[-1] / bh[0] - 1) * 100 if len(bh) > 1 and bh[0] else 0.0
    targets = sorted((p.get("final_holdings") or {}).items(), key=lambda kv: -kv[1])[:10]
    return {"持有期": r.get("hp"), "数据截止": r.get("as_of"),
            "组合纸面盘收益": "{:+.2f}%".format(ret),
            "等权买持收益": "{:+.2f}%".format(bh_ret),
            "调仓次数": p.get("rebalances"), "平均换手": "{:.1%}".format(p.get("turnover_avg", 0)),
            "成本合计": round(float(p.get("cost_total", 0)), 2),
            "前10目标持仓": [{"代码": c, "数量": q} for c, q in targets]}


def _do_get_research_snapshot(hp=20):
    """研究快照: 市场信号 + 价值因子研究 + 多因子选股 + 组合纸面盘."""
    r = _research_worker("build_snapshot", hp=int(hp or 20))
    if r.get("frames_error"):
        return {"error": r["frames_error"]}
    sig = r.get("signals") or {}
    st = r.get("study") or {}
    p = r.get("paper") or {}
    nav = p.get("nav") or []
    return {"持有期": r.get("hp"), "数据截止": r.get("as_of"),
            "市场状态": (sig.get("value_tilt") or {}).get("value_tilt"),
            "市场宽度": (sig.get("breadth") or {}).get("breadth"),
            "组合价值权重": (sig.get("alloc") or {}).get("w_value"),
            "决策门": ((sig.get("hard_rule") or {}).get("action") if sig.get("hard_rule") else None),
            "BP IC/ICIR": {"IC": st.get("BP", {}).get("ic"), "ICIR": st.get("BP", {}).get("icir")},
            "多因子选股前5": [x.get("code") for x in (r.get("ranking") or [])[:5]],
            "纸面盘收益": "{:+.2f}%".format((nav[-1] / nav[0] - 1) * 100 if len(nav) > 1 and nav[0] else 0)}


# ══════════════════════════ 策略类 (Web 新增) ══════════════════════════

def _do_get_strategies():
    """列出全部可用策略契约(真实5家族, 含中文描述)."""
    try:
        from backend.paper_worker import _strategy_contracts
        from backend.strategy.describe import describe_contract
        out = []
        for name, c in _strategy_contracts(20).items():
            d = {}
            try:
                d = describe_contract(c)
            except Exception:
                pass
            facs = [str(x) for x in (getattr(c, "factors", None) or [])]
            out.append({
                "id": name, "name": name,
                "kind": "multi_factor" if len(facs) > 1 else "single",
                "factors": facs,
                "desc": str(d.get("summary") or d.get("desc") or " + ".join(facs)),
                "buy_condition": d.get("buy_condition", ""),
                "sell_condition": d.get("sell_condition", ""),
                "rebalance_bars": getattr(c, "rebalance_bars", 20),
                "top_k_pct": getattr(c, "top_k_pct", 0.2),
                "use_tilt": bool(getattr(c, "use_tilt", False)),
            })
        return {"策略数": len(out), "策略列表": [
            {"id": s["name"], "名称": s["name"], "因子": s["factors"],
             "持有期": s["rebalance_bars"], "top_k": s["top_k_pct"], "价值tilt": s["use_tilt"],
             "描述": s["desc"]} for s in out]}  # type: ignore[index]
    except Exception as e:
        return {"error": str(e)}


def _fval(v, default=0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _do_backtest_strategy(name=None, contract=None, start=None, end=None):
    """对指定策略(id)或自定义契约回测, 返回完整指标+净值摘要. 可能耗时数十秒."""
    from backend.strategy.portfolio_rebalance import SelectionContract, forward_paper_run
    from backend.strategy.metrics import compute_full_metrics
    from backend.paper_worker import _load_frames, _strategy_contracts, _flatten_rebalance_trades

    frames = _load_frames()
    c = None
    cname = name or "自定义"
    if name:
        c = _strategy_contracts(20).get(name)
        if c is None:
            return {"error": f"未知策略 '{name}', 可用: {list(_strategy_contracts(20).keys())}"}
    elif contract:
        c = SelectionContract(
            factors=contract.get("factors") or ["BP"],
            base_weights=contract.get("weights") or {"BP": 1.0},
            top_k_pct=contract.get("top_k_pct", 0.2),
            rebalance_bars=contract.get("rebalance_bars", 20),
            initial_balance=contract.get("initial_balance", 1_000_000.0),
        )
    else:
        return {"error": "需要 name 或 contract"}

    fw = forward_paper_run(frames, c, start or "2024-01-01", end or "2099-12-31", initial_balance=c.initial_balance)
    tr = _flatten_rebalance_trades(fw.get("rebalance_log") or [])
    m = compute_full_metrics(fw["nav_n"], freq_bars=c.rebalance_bars, trades=tr,
                             dates=fw.get("dates", []))
    nav = fw.get("nav_n") or []
    fh = sorted((fw.get("final_holdings") or {}).items(), key=lambda kv: -kv[1])[:10]
    return {
        "策略": cname,
        "区间": f"{fw.get('dates', [''])[0] if fw.get('dates') else start} ~ {fw.get('dates', [''])[-1] if fw.get('dates') else end}",
        "复权净值": "→".join([f"{x:.4f}" for x in nav[:5]]) + ("…" if len(nav) > 5 else ""),
        "总收益": f"{(_fval(m.get('total_return')) * 100):+.2f}%",
        "年化": f"{(_fval(m.get('cagr')) * 100):+.2f}%",
        "夏普": round(_fval(m.get('sharpe')), 2),
        "最大回撤": f"{(_fval(m.get('max_drawdown')) * 100):.2f}%",
        "阿尔法": f"{(_fval(m.get('alpha')) * 100):+.2f}%",
        "贝塔": round(_fval(m.get('beta')), 2),
        "胜率": f"{(_fval(m.get('win_rate')) * 100):.1f}%",
        "交易次数": m.get("num_trades"),
        "调仓次数": fw.get("rebalances"),
        "持有期": c.rebalance_bars,
        "final_holdings前10": [{"代码": k, "市值": f"{_fval(v):.0f}"} for k, v in fh],
    }


def _do_describe_strategy(name=None):
    """描述策略买入/持有/卖出条件(中文)."""
    if not name:
        got = _do_get_strategies()
        if "error" in got:
            return got
        names = "、".join(str(x.get("名称", "")) for x in got.get("策略列表", []) if isinstance(x, dict))
        return {"说明": "可用策略: " + names}
    from backend.paper_worker import _strategy_contracts
    from backend.strategy.describe import describe_contract
    c = _strategy_contracts(20).get(name)
    if c is None:
        return {"error": f"未知策略 '{name}'"}
    try:
        d = describe_contract(c)
        facs = [str(x) for x in (getattr(c, "factors", None) or [])]
        return {"策略": name, "因子": facs, "描述": d.get("summary", ""),
                "买入条件": d.get("buy_condition", ""), "持有条件": d.get("hold_condition", ""),
                "卖出条件": d.get("sell_condition", "")}
    except Exception as e:
        return {"error": str(e)}


def _do_get_picks(top=10):
    """当前多因子选股 Top N(读缓存, 无则提示先运行选股)."""
    from backend.api.blueprints import picks as picks_bp
    import time
    with picks_bp._lock:
        data, ts = picks_bp._cache["data"], picks_bp._cache["ts"]
    if data is None:
        return {"message": "选股缓存为空, 可先触发 run_picks"}
    return {"数据时间": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "总数": data.get("total"), "前N": [
                {"代码": x["code"], "名称": x.get("name", ""), "评分": round(float(x.get("score") or 0), 2),
                 "涨跌幅(%)": round(float(x.get("change_pct") or 0), 2)}
                for x in (data.get("items") or [])[:int(top or 10)]]}


def _do_get_regime():
    """当前市场环境(牛/熊/震荡) + 建议策略."""
    try:
        from backend.strategy.regime import run as regime_run
        r = regime_run()
        return {"环境": r.get("regime"), "中文": r.get("regime_cn"),
                "建议策略": r.get("suggest_strategy"), "数据至": r.get("as_of"),
                "旋转": r.get("rotation", {}).get("primary"),
                "系统风险触发": (r.get("sys_risk") or {}).get("triggered")}
    except Exception as e:
        return {"error": str(e)}


def _do_run_picks():
    """触发一次多因子全市场选股(异步job), 完成后返回Top结果. 可能耗时较长."""
    from backend.api.blueprints import picks as picks_bp
    from backend.api import jobman
    from backend.api.blueprints.picks import _run as _picks_run

    with picks_bp._lock:
        if picks_bp._cache["running"]:
            return {"message": "选股已在进行中"}
        picks_bp._cache["running"] = True

    def _wrapped(payload, on_progress):
        try:
            res = _picks_run(payload, on_progress)
            with picks_bp._lock:
                picks_bp._cache["data"] = res
                picks_bp._cache["ts"] = __import__("time").time()
            return res
        finally:
            with picks_bp._lock:
                picks_bp._cache["running"] = False

    job = jobman.submit("picks", _wrapped, {"kline_days": 60})
    return {"message": "选股任务已提交", "job_id": job["job_id"]}


# ══════════════════════════ 注册 ══════════════════════════

_TOOLS = [
    {"type": "function", "function": {
        "name": "get_account_summary",
        "description": "查看AI账户摘要：总资产、可用资金、冻结资金、持仓市值、浮动盈亏、累计盈亏、盈亏百分比、持仓数和待成交委托数"}},
    {"type": "function", "function": {
        "name": "get_positions",
        "description": "获取当前全部持仓明细：每只股票的代码、名称、持仓量、成本价、现价、市值、浮动盈亏"}},
    {"type": "function", "function": {
        "name": "get_stock_price",
        "description": "获取指定股票代码的实时现价和涨跌幅",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "股票代码，例如 000001, 600519"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "search_stock",
        "description": "根据名称或代码关键词模糊搜索股票，返回匹配列表",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "股票名称或代码关键词"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "place_order",
        "description": ("下单交易(AI账户模拟盘)。市价单(market)立即成交；限价单(limit)等价格到达后成交。"
                        "A股规则：最小100股，T+1不可当日卖出，单票仓位不超过总资产30%。"
                        "务必先查价格和资金，再下单。不要等待用户确认。"),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "股票代码"},
            "name": {"type": "string", "description": "股票名称"},
            "side": {"type": "string", "enum": ["buy", "sell"], "description": "buy买入 sell卖出"},
            "order_type": {"type": "string", "enum": ["market", "limit"], "description": "market市价 limit限价"},
            "price": {"type": "number", "description": "限价单的委托价格（市价单填0）"},
            "qty": {"type": "integer", "description": "数量，100的整数倍"}},
            "required": ["code", "name", "side", "order_type", "price", "qty"]}}},
    {"type": "function", "function": {
        "name": "cancel_order",
        "description": "撤销待成交的限价委托单",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer", "description": "委托单ID，可从get_account_summary获知"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "research_value_factors",
        "description": "研究价值因子BP/EP/ROE的截面IC/ICIR，返回推荐因子。这是'研究'环节（可能耗时数十秒，后台计算）。"}},
    {"type": "function", "function": {
        "name": "run_factor_backtest",
        "description": "单因子截面回测（跨板块池，板块中性化）：传入因子与持有期，返回IC/ICIR/IC正率/单调性/多空净收益/分组净值。这是'回测'环节（可能耗时数十秒）。",
        "parameters": {"type": "object", "properties": {
            "factor": {"type": "string", "description": "因子，如 BP/EP/ROE/MOMENTUM_20/REVERSAL_20/VOLATILITY_20"},
            "holding_period": {"type": "integer", "description": "持有期(bar)，如 5/10/20"}},
            "required": ["factor"]}}},
    {"type": "function", "function": {
        "name": "get_portfolio_paper",
        "description": "组合纸面盘：多因子重平衡(接组合价值权重)净值 vs 等权买持，返回收益/调仓/目标持仓。这是'纸面盘'环节（可能耗时数十秒）。",
        "parameters": {"type": "object", "properties": {
            "hp": {"type": "integer", "description": "持有期，如 5/10/20/40，默认 20"}}}}},
    {"type": "function", "function": {
        "name": "get_research_snapshot",
        "description": "一键研究快照：市场信号(价值tilt/宽度/组合权重/决策门)+价值因子研究+多因子选股前5+组合纸面盘收益。研究→回测→纸面盘整链路（可能耗时较长）。",
        "parameters": {"type": "object", "properties": {
            "hp": {"type": "integer", "description": "持有期，如 5/10/20/40，默认 20"}}}}},
    {"type": "function", "function": {
        "name": "get_strategies",
        "description": "列出全部可用策略契约(5个真实策略家族)：名称、因子、持有期、top_k、是否价值tilt、中文描述。"}},
    {"type": "function", "function": {
        "name": "backtest_strategy",
        "description": "对指定策略(id，如 'F价值Tilt'/'A价值'/'B反转'/'C低波动'/'D多因子')或自定义契约(Declaration JSON)执行回测，返回总收益/年化/夏普/回撤/α/β/胜率/交易次数等完整指标。这是'回测'环节（可能耗时数十秒）。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "策略id，如 F价值Tilt"},
            "contract": {"type": "object", "description": "自定义契约: {factors:[...], weights:{...}, top_k_pct:0.2, rebalance_bars:20, initial_balance:1000000}"},
            "start": {"type": "string", "description": "回测起始日期 YYYY-MM-DD，默认两年前"},
            "end": {"type": "string", "description": "回测结束日期 YYYY-MM-DD，默认今天"}}}}},
    {"type": "function", "function": {
        "name": "describe_strategy",
        "description": "描述策略的买入/持有/卖出条件(中文)。不传name则列出可选策略id。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "策略id，如 A价值"}}}}},
    {"type": "function", "function": {
        "name": "get_picks",
        "description": "当前多因子选股 Top N(读缓存)，返回代码/名称/评分/涨跌幅。若无缓存可先调 run_picks。",
        "parameters": {"type": "object", "properties": {
            "top": {"type": "integer", "description": "N，默认10"}}}}},
    {"type": "function", "function": {
        "name": "run_picks",
        "description": "触发一次全市场多因子选股(异步)，提交后请稍等再调 get_picks 读取结果。"}},
    {"type": "function", "function": {
        "name": "get_regime",
        "description": "A股当前市场环境(牛/熊/震荡)，含建议策略与系统风险触发状态。"}},
]

_DISPATCH = {
    "get_account_summary": _do_get_account_summary,
    "get_positions": _do_get_positions,
    "get_stock_price": _do_get_stock_price,
    "search_stock": _do_search_stock,
    "place_order": _do_place_order,
    "cancel_order": _do_cancel_order,
    "research_value_factors": _do_research_value_factors,
    "run_factor_backtest": _do_run_factor_backtest,
    "get_portfolio_paper": _do_get_portfolio_paper,
    "get_research_snapshot": _do_get_research_snapshot,
    "get_strategies": _do_get_strategies,
    "backtest_strategy": _do_backtest_strategy,
    "describe_strategy": _do_describe_strategy,
    "get_picks": _do_get_picks,
    "run_picks": _do_run_picks,
    "get_regime": _do_get_regime,
}

# 可能耗时数十秒的慢工具(LLM 循环里便于提示)
SLOW_TOOLS = {
    "research_value_factors", "run_factor_backtest", "get_portfolio_paper",
    "get_research_snapshot", "backtest_strategy", "run_picks",
}


def tool_names() -> list[str]:
    return sorted(_DISPATCH.keys())


def execute_tool(name, args):
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"未知工具: {name}"}
    try:
        return fn(**(args or {}))
    except Exception as e:
        return {"error": str(e)}
