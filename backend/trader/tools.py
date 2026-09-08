# -*- coding: utf-8 -*-
"""操盘手工具集 —— 只读查询 + 下单预览 + 决策提交。

与聊天工具 backend/agent/toolkit.py 的区别：
- 所有交易相关操作绑定「AI操盘手」专属账户（不是聊天用的「AI账户」）。
- 不提供写策略/回测类工具（那是策略进化闭环的事）。
- 决策通过 submit_decision 一次性提交，由 daily.py 统一校验执行，便于审计与记忆。
"""
from __future__ import annotations

from typing import Any, Optional

from ..trade_engine.engine import TradeEngine
from . import news as news_mod

MAX_ROUNDS_HINT = 8


class TraderTools:
    """一次决策会话内的工具执行器。"""

    def __init__(self, account_id: int, profile_id: int,
                 risk_rules: Optional[dict] = None):
        self.account_id = int(account_id)
        self.profile_id = int(profile_id)
        self.risk_rules = risk_rules or {}
        self.decision: Optional[dict] = None   # submit_decision 捕获
        self.notes: list = []                  # remember 捕获
        self.log: list = []                    # 工具调用轨迹(供页面展示)

    # ── 内部 ──
    def _engine(self) -> TradeEngine:
        return TradeEngine()

    def _price(self, code: str) -> Optional[float]:
        from .context import refresh_prices
        px = refresh_prices([code]).get(str(code)) or {}
        p = px.get("price")
        return float(p) if p else None

    # ── 只读 ──
    def get_account_summary(self) -> dict:
        s = self._engine().get_summary(self.account_id) or {}
        return {
            "总资产": round(float(s.get("total_assets", 0)), 2),
            "可用资金": round(float(s.get("balance", 0)), 2),
            "冻结资金": round(float(s.get("frozen", 0)), 2),
            "持仓市值": round(float(s.get("market_value", 0)), 2),
            "浮动盈亏": round(float(s.get("float_pnl", 0)), 2),
            "累计盈亏": round(float(s.get("total_profit", 0)), 2),
            "盈亏百分比": f"{float(s.get('total_profit_pct', 0)):.2f}%",
            "持仓数": s.get("positions", 0),
            "待成交委托数": s.get("pending_orders", 0),
        }

    def get_positions(self) -> Any:
        ps = self._engine().get_positions(self.account_id)
        if not ps:
            return {"message": "当前空仓"}
        return [{
            "代码": p["code"], "名称": p["name"], "持仓量": p["qty"],
            "成本价": round(float(p["cost_price"]), 3),
            "现价": round(float(p["current_price"]), 3),
            "市值": round(float(p["market_value"]), 2),
            "浮动盈亏": round(float(p["float_pnl"]), 2),
            "最近买入日": p.get("last_buy_date") or "",
        } for p in ps]

    def get_stock_price(self, code: str) -> dict:
        px = self._price(code)
        if px is None:
            return {"error": f"无法获取 {code} 价格"}
        return {"代码": str(code), "现价": round(px, 3)}

    def search_stock(self, keyword: str) -> Any:
        import sqlite3
        from ..api.paths import KLINE_DB
        try:
            con = sqlite3.connect(KLINE_DB)
            rows = con.execute(
                "SELECT code, name FROM stock_list WHERE code LIKE ? OR name LIKE ? LIMIT 10",
                (f"%{keyword}%", f"%{keyword}%")).fetchall()
            con.close()
        except Exception as e:
            return {"error": str(e)}
        if not rows:
            return {"message": f"未找到匹配 '{keyword}' 的股票"}
        return [{"代码": r[0], "名称": r[1]} for r in rows]

    def get_market_news(self, limit: int = 15) -> Any:
        rows = news_mod.market_news(limit=int(limit or 15))
        return rows or {"message": "暂无市场快讯"}

    def get_stock_news(self, code: str, name: str = "") -> Any:
        rows = news_mod.stock_news(str(code), name, limit=5)
        return rows or {"message": f"{code} 暂无新闻"}

    def get_regime(self) -> dict:
        from .context import build_market_block
        return build_market_block()

    def get_candidates(self, top: int = 10) -> dict:
        from .context import build_candidates_block
        return build_candidates_block(top_n=int(top or 10))

    # ── 下单预览（只读，不成交） ──
    def preview_order(self, code: str, side: str, order_type: str = "market",
                      price: float = 0, qty: int = 0) -> dict:
        engine = self._engine()
        side = str(side).lower()
        order_type = str(order_type or "market").lower()
        code = str(code)
        try:
            qty = int(qty)
        except Exception:
            return {"可执行": False, "原因": "数量非法"}
        if qty <= 0 or qty % engine.LOT_SIZE != 0:
            return {"可执行": False, "原因": f"数量必须是 {engine.LOT_SIZE} 的整数倍"}
        ref_price = float(price) if order_type == "limit" and price else self._price(code)
        if not ref_price or ref_price <= 0:
            return {"可执行": False, "原因": f"无法确定 {code} 价格"}
        acc = engine.get_account(self.account_id) or {}
        pos = {p["code"]: p for p in engine.get_positions(self.account_id)}
        if side == "buy":
            cost = ref_price * qty * (1 + engine.COMMISSION_RATE)
            if float(acc.get("balance", 0)) < cost:
                return {"可执行": False, "原因": f"资金不足：需 {cost:,.2f}，可用 {float(acc.get('balance',0)):,.2f}"}
            holdings = sum(float(p["qty"]) * float(p["cost_price"]) for p in pos.values())
            total = float(acc.get("balance", 0)) + float(acc.get("frozen", 0)) + holdings
            after = ref_price * qty + (float(pos[code]["qty"]) * float(pos[code]["cost_price"]) if code in pos else 0)
            ratio = after / (total + ref_price * qty) if total > 0 else 1
            if ratio > engine.POSITION_LIMIT:
                return {"可执行": False,
                        "原因": f"单票仓位将达 {ratio*100:.1f}%，超过 {engine.POSITION_LIMIT*100:.0f}% 上限"}
            return {"可执行": True, "参考价": round(ref_price, 3), "预计成本": round(cost, 2),
                    "下单后单票占比": f"{ratio*100:.1f}%"}
        elif side == "sell":
            p = pos.get(code)
            if not p or p["qty"] <= 0:
                return {"可执行": False, "原因": "没有该股票持仓"}
            available = p["qty"] - p["frozen_qty"]
            if available < qty:
                return {"可执行": False, "原因": f"可卖不足：持仓 {p['qty']}，冻结 {p['frozen_qty']}"}
            today = __import__("datetime").date.today().isoformat()
            if p.get("last_buy_date") and p["last_buy_date"] == today:
                return {"可执行": False, "原因": "T+1：今日买入不可卖出"}
            proceeds = ref_price * qty * (1 - engine.COMMISSION_RATE - engine.STAMP_TAX_RATE)
            return {"可执行": True, "参考价": round(ref_price, 3), "预计到账": round(proceeds, 2)}
        return {"可执行": False, "原因": "方向必须是 buy 或 sell"}

    # ── 写入 ──
    def remember(self, content: str, kind: str = "note", code: str = "") -> dict:
        content = str(content or "").strip()
        if not content:
            return {"error": "内容为空"}
        self.notes.append({"kind": kind if kind in ("thesis", "lesson", "note", "market") else "note",
                           "code": str(code or ""), "content": content[:1000]})
        return {"状态": "已记入长期记忆"}

    def submit_decision(self, thinking: str, orders: Optional[list] = None,
                        reflection: str = "") -> dict:
        self.decision = {
            "thinking": str(thinking or "").strip(),
            "orders": orders or [],
            "reflection": str(reflection or "").strip(),
        }
        n = len(self.decision["orders"])
        return {"状态": "决策已提交", "委托数": n,
                "说明": "保持现状" if n == 0 else "将按计划执行并记录"}

    # ── 调度 ──
    def execute(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_") or name in ("execute", "decision", "notes", "log"):
            return {"error": f"未知工具: {name}"}
        try:
            result = fn(**(args or {}))
            self.log.append({"tool": name, "args": args or {}})
            return result
        except Exception as e:
            self.log.append({"tool": name, "args": args or {}, "error": str(e)})
            return {"error": str(e)}


# ───────────────────────── 工具 schema ─────────────────────────

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_account_summary",
        "description": "查看你自己账户的最新摘要：总资产、可用资金、持仓市值、浮动/累计盈亏、持仓数。"}},
    {"type": "function", "function": {
        "name": "get_positions",
        "description": "查看当前全部持仓明细：代码、名称、持仓量、成本价、现价、市值、浮动盈亏。"}},
    {"type": "function", "function": {
        "name": "get_stock_price",
        "description": "查询指定股票的最新价格。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "股票代码，如 600519"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "search_stock",
        "description": "按名称或代码关键词搜索股票。",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "名称或代码关键词"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "get_market_news",
        "description": "获取今日市场/宏观财经快讯（东财全球财经，标题+摘要+时间）。",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "条数，默认15"}}}}},
    {"type": "function", "function": {
        "name": "get_stock_news",
        "description": "获取指定个股的最新新闻/公告标题。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"}, "name": {"type": "string"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "get_regime",
        "description": "获取当前 A 股市场环境（牛/熊/震荡、系统性风险、建议策略）与三大指数涨跌。"}},
    {"type": "function", "function": {
        "name": "get_candidates",
        "description": "获取多因子评分候选股 Top N 与事件驱动池（热点板块）。",
        "parameters": {"type": "object", "properties": {
            "top": {"type": "integer", "description": "条数，默认10"}}}}},
    {"type": "function", "function": {
        "name": "preview_order",
        "description": ("校验一笔计划委托能否执行（只读，不成交）：资金是否够、单票占比是否超限、"
                        "T+1/可卖数量是否满足。下单前建议先预览。"),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "price": {"type": "number", "description": "限价单价格；市价单填0"},
            "qty": {"type": "integer", "description": "数量，100 的整数倍"}},
            "required": ["code", "side", "qty"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": ("写入长期记忆。kind=thesis 记录某持仓的买入逻辑（买入时必须写）；"
                        "kind=lesson 记录经验教训；kind=note 一般观察；kind=market 市场判断。"),
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "记忆内容，简洁具体"},
            "kind": {"type": "string", "enum": ["thesis", "lesson", "note", "market"]},
            "code": {"type": "string", "description": "相关股票代码（thesis 必填）"}},
            "required": ["content"]}}},
    {"type": "function", "function": {
        "name": "submit_decision",
        "description": ("提交今日最终决策并结束。orders 为空表示保持现状(不操作)。"
                        "买入请在对应 order 的 reason 里写清逻辑，系统会自动记为该持仓的长期逻辑。"),
        "parameters": {"type": "object", "properties": {
            "thinking": {"type": "string", "description": "今日完整分析（市场/持仓/候选/新闻如何影响你的判断）"},
            "orders": {"type": "array", "description": "计划委托，可为多笔", "items": {
                "type": "object", "properties": {
                    "code": {"type": "string"}, "name": {"type": "string"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "order_type": {"type": "string", "enum": ["market", "limit"]},
                    "price": {"type": "number"}, "qty": {"type": "integer"},
                    "reason": {"type": "string", "description": "这笔操作的理由"}},
                "required": ["code", "side", "qty"]}},
            "reflection": {"type": "string", "description": "对上一交易日的复盘与经验（首次可为空）"}},
            "required": ["thinking"]}}},
]

WRITE_TOOLS = {"submit_decision", "remember", "preview_order"}
