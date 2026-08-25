# -*- coding: utf-8 -*-
"""AI trading tools — function schemas + ToolExecutor."""

import json, sys, os

_BD = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))
if _BD not in sys.path:
    sys.path.insert(0, _BD)

from trade_engine.engine import TradeEngine


_engine = TradeEngine()

def _ai_account():
    accs = _engine.list_accounts()
    for a in accs:
        if a['name'] == 'AI账户':
            return a['id']
    return _engine.create_account('AI账户', 100000)


def _do_get_account_summary():
    s = _engine.get_summary(_ai_account())
    if s is None:
        return {"error": "账户不存在"}
    return {
        "总资产": round(s['total_assets'], 2),
        "可用资金": round(s['balance'], 2),
        "冻结资金": round(s['frozen'], 2),
        "持仓市值": round(s['market_value'], 2),
        "浮动盈亏": round(s['float_pnl'], 2),
        "累计盈亏": round(s['total_profit'], 2),
        "盈亏百分比": f"{s['total_profit_pct']:.2f}%",
        "持仓数": s['positions'],
        "待成交委托数": s['pending_orders'],
    }


def _do_get_positions():
    positions = _engine.get_positions(_ai_account())
    if not positions:
        return {"message": "当前无持仓"}
    result = []
    for p in positions:
        result.append({
            "代码": p['code'],
            "名称": p['name'],
            "持仓量": p['qty'],
            "成本价": round(p['cost_price'], 2),
            "现价": round(p['current_price'], 2),
            "市值": round(p['market_value'], 2),
            "浮动盈亏": round(p['float_pnl'], 2),
        })
    return result


def _do_get_stock_price(code):
    from data_manager import fetch_realtime_prices
    try:
        results = fetch_realtime_prices([code])
        if results:
            r = results[0]
            return {
                "代码": r['code'],
                "名称": r.get('name', ''),
                "现价": r['price'],
                "涨跌幅(%)": round(r.get('change_pct', 0), 2),
            }
        return {"error": f"未找到股票 {code}"}
    except Exception as e:
        return {"error": str(e)}


def _do_search_stock(keyword):
    import sqlite3
    proj = os.path.dirname(_BD)
    kline_db = os.path.join(proj, "data", "kline.db")
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
    current_price = None
    if order_type == 'market':
        from data_manager import fetch_realtime_prices
        results = fetch_realtime_prices([code])
        if results:
            current_price = results[0]['price']
        else:
            return {"error": f"无法获取 {code} 实时价格，无法下市价单"}

    order, result = _engine.place_order(
        _ai_account(), code, name, side, order_type,
        price, qty, current_price=current_price,
    )
    if order is None:
        return {"error": result}
    if isinstance(result, dict):
        return {
            "状态": "已成交",
            "方向": "买入" if side == 'buy' else "卖出",
            "代码": code,
            "名称": name,
            "价格": result['price'],
            "数量": result['qty'],
            "手续费": round(result['commission'], 2),
            "印花税": round(result['stamp_tax'], 2) if result['stamp_tax'] else 0.0,
        }
    return {
        "状态": "已挂单",
        "方向": "买入" if side == 'buy' else "卖出",
        "代码": code,
        "委托价": order['price'],
        "数量": order['qty'],
    }


def _do_cancel_order(order_id):
    ok, err = _engine.cancel_order(order_id)
    if ok:
        return {"状态": "已撤单"}
    return {"error": err}


# ── 研究工具(研究→回测→纸面盘; 后台计算, 可能耗时) ──
_PROJ = os.path.dirname(_BD)
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)


def _research_worker(name, *a, **kw):
    try:
        import importlib
        mod = importlib.import_module("frontend.plugins.research.worker")
        return getattr(mod, name)(*a, **kw)
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
    """组合纸面盘: 多因子重平衡(接组合价值权重)净值 vs 基准, 返回收益/目标持仓."""
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
            "成本合计": round(p.get("cost_total", 0), 2),
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_account_summary",
            "description": "查看AI账户摘要：总资产、可用资金、冻结资金、持仓市值、浮动盈亏、累计盈亏、盈亏百分比、持仓数和待成交委托数",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": "获取当前全部持仓明细：每只股票的代码、名称、持仓量、成本价、现价、市值、浮动盈亏",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "获取指定股票的实时现价和涨跌幅",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "股票代码，例如 000001, 600519"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock",
            "description": "根据名称或代码关键词模糊搜索股票，返回匹配列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "股票名称或代码关键词"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": (
                "下单交易。市价单(market)立即成交；限价单(limit)等价格到达后成交。"
                "A股规则：最小100股，T+1不可当日卖出，单票仓位不超过总资产30%。"
                "务必先查价格和资金，再下单。不要等待用户确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "股票代码"},
                    "name": {"type": "string", "description": "股票名称"},
                    "side": {"type": "string", "enum": ["buy", "sell"], "description": "buy买入 sell卖出"},
                    "order_type": {"type": "string", "enum": ["market", "limit"], "description": "market市价 limit限价"},
                    "price": {"type": "number", "description": "限价单的委托价格（市价单填0）"},
                    "qty": {"type": "integer", "description": "数量，100的整数倍"},
                },
                "required": ["code", "name", "side", "order_type", "price", "qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "撤销待成交的限价委托单",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "integer", "description": "委托单ID，可从get_account_summary获知"},
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_value_factors",
            "description": "研究价值因子BP/EP/ROE的截面IC/ICIR，返回推荐因子。这是'研究'环节（可能耗时数十秒，后台计算）。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_factor_backtest",
            "description": "单因子截面回测（跨板块池，板块中性化）：传入因子与持有期，返回IC/ICIR/IC正率/单调性/多空净收益/分组净值。这是'回测'环节（可能耗时数十秒）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string", "description": "因子，如 BP/EP/ROE/MOMENTUM_20/REVERSAL_20/VOLATILITY_20"},
                    "holding_period": {"type": "integer", "description": "持有期(bar)，如 5/10/20"},
                },
                "required": ["factor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_paper",
            "description": "组合纸面盘：多因子重平衡(接组合价值权重)净值 vs 等权买持，返回收益/调仓/目标持仓。这是'纸面盘'环节（可能耗时数十秒）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hp": {"type": "integer", "description": "持有期，如 5/10/20/40，默认 20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_research_snapshot",
            "description": "一键研究快照：市场信号(价值tilt/宽度/组合权重/决策门)+价值因子研究+多因子选股前5+组合纸面盘收益。研究→回测→纸面盘整链路（可能耗时较长）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hp": {"type": "integer", "description": "持有期，如 5/10/20/40，默认 20"},
                },
                "required": [],
            },
        },
    },
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
}


def execute_tool(name, args):
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"未知工具: {name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"error": str(e)}
