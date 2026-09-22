# -*- coding: utf-8 -*-
"""操盘手工具集 —— 只读查询 + 直接下单/撤单 + 记录决策。

模拟券商软件：大模型像普通股民一样通过工具操作账户，所有规则（资金、T+1、
100 股、费用）由交易引擎强制执行，违规直接返回错误，模型根据返回调整。

与聊天工具 backend/agent/toolkit.py 的区别：
- 所有交易操作绑定「AI操盘手」专属账户（不是聊天用的「AI账户」）。
- 不提供写策略/回测类工具（那是策略进化闭环的事）。
- 下单即成交/挂单，submit_decision 只用于结束今日决策并记录思考与复盘。
"""
from __future__ import annotations

from typing import Any, Optional

from ..trade_engine.engine import TradeEngine
from . import news as news_mod
from . import store

MAX_ROUNDS_HINT = 8


class TraderTools:
    """一次决策会话内的工具执行器。"""

    def __init__(self, account_id: int, profile_id: int,
                 risk_rules: Optional[dict] = None,
                 decision_id: Optional[int] = None, dry_run: bool = False,
                 trade_date: Optional[str] = None,
                 price_fn: Optional[Any] = None,
                 weights: Optional[Any] = None):
        self.account_id = int(account_id)
        self.profile_id = int(profile_id)
        self.risk_rules = risk_rules or {}
        self.decision_id = decision_id
        self.dry_run = bool(dry_run)
        self.trade_date = trade_date or None   # 回放: 历史交易日 YYYY-MM-DD
        self.price_fn = price_fn               # 回放: 返回该日收盘价的函数; 为 None 时用实时
        self.weights = weights                 # 评分口径（预设名或 {组id:满分}）
        self.decision: Optional[dict] = None   # submit_decision 捕获
        self.notes: list = []                  # remember 捕获
        self.log: list = []                    # 工具调用轨迹(供页面展示)
        self.plan: list = []                   # 已尝试的委托（含成交/拒绝）
        self.executions: list = []             # 与 plan 同结构的执行结果
        self.rejections: list = []             # 被纪律规则拒绝的委托（可审计）
        self.new_buys_today = 0                # 今日已成交的买入笔数（纪律规则用）

    # ── 纪律规则 ──
    def _discipline_buy(self, code: str, qty: int, price: float) -> Optional[dict]:
        """买入前的纪律检查（自省结论 → 系统强制执行）。"""
        try:
            from . import discipline
        except Exception:
            return None
        as_of = self.trade_date or None
        engine = self._engine()
        acc = engine.get_account(self.account_id) or {}
        pos = {p["code"]: p for p in engine.get_positions(self.account_id)}
        holdings = sum(float(p["qty"]) * float(p["cost_price"]) for p in pos.values())
        total = float(acc.get("balance", 0)) + float(acc.get("frozen", 0)) + holdings
        cost_now = (float(pos[code]["qty"]) * float(pos[code]["cost_price"])) if code in pos else 0.0
        ratio_after = (price * qty + cost_now) / (total + price * qty) if total > 0 else 1.0
        regime = ""
        try:
            rg = self.get_regime()
            regime = str((rg or {}).get("regime") or (rg or {}).get("regime_cn") or "")
        except Exception:
            regime = ""
        v = discipline.check_buy(self.profile_id, code, ratio_after=ratio_after,
                                 regime=regime, new_buys_today=self.new_buys_today,
                                 as_of=as_of)
        if v:
            self.rejections.append({"code": code, "side": "buy", "qty": qty,
                                    "rule": v["rule"], "message": v["message"]})
        return v

    # ── 内部 ──
    def _engine(self) -> TradeEngine:
        from .account import trader_engine
        return trader_engine()

    def _price(self, code: str) -> Optional[float]:
        if self.price_fn is not None:
            try:
                return self.price_fn(str(code))
            except Exception:
                return None
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
        if self.trade_date:
            return {"note": "回放模式：历史新闻不可回溯，本日无新闻输入（仅凭行情/候选/宏观决策）"}
        rows = news_mod.market_news(limit=int(limit or 15))
        return rows or {"message": "暂无市场快讯"}

    def get_stock_news(self, code: str, name: str = "") -> Any:
        if self.trade_date:
            return {"note": f"回放模式：{code} 的历史新闻不可回溯"}
        rows = news_mod.stock_news(str(code), name, limit=5)
        return rows or {"message": f"{code} 暂无新闻"}

    def get_regime(self) -> dict:
        if self.trade_date:
            from .replay import _regime_asof, _hs300_trend_asof
            return {"regime": _regime_asof(self.trade_date),
                    "hs300": _hs300_trend_asof(self.trade_date)}
        from .context import build_market_block
        return build_market_block()

    # ── 自主选股：检索市场（不再依赖固定候选池） ──
    def screen_stocks(self, filters: dict = None, sort_by: str = "circ_mv",
                      ascending: bool = True, limit: int = 20) -> dict:
        """按条件筛选全市场并排序取前 N（as-of 安全，回放里也按当天截断）。

        filters 例：{"circ_mv_min":5,"circ_mv_max":30,"amount_min":0.5,"ret60_min":0}
        维度见返回里的 dimensions。
        """
        from . import screen as _s
        return _s.screen(self.trade_date, filters, sort_by, ascending, limit)

    def get_stock_factors(self, code: str) -> dict:
        """单只股票的可用指标（市值/涨跌幅/换手/振幅/波动/位置/ST代理）+ **价格结构特征**。

        结构特征（区间位置、波段结构、突破质量、回撤×ATR、粘滞度）由程序按 as-of 计算，
        属于"客观事实"——你直接引用即可，不需要自己数 K 线。
        """
        from . import screen as _s
        out = _s.factors_of(code, self.trade_date)
        if out.get("name") == "" and not out.get("error"):
            try:
                from .context import _name_of  # type: ignore
                out["name"] = _name_of(code)
            except Exception:
                pass
        try:
            from . import routing as _routing
            import datetime as _dt3
            rc = _routing.classify_code(code, self.trade_date or _dt3.date.today().isoformat())
            if rc.get("ok"):
                out["结构分类"] = rc.get("label")
                out["结构分类提示"] = rc.get("note")
        except Exception:
            pass
        try:
            from . import bars as _bars
            import datetime as _dt2
            as_of2 = self.trade_date or _dt2.date.today().isoformat()
            bd = _bars.compute(code, as_of2)
            if bd.get("ok"):
                out["棒级"] = {"last": bd.get("last"), "follow_through": bd.get("follow_through"),
                              "streak": bd.get("streak")}
                out["棒级说明"] = _bars.render(bd, "")
        except Exception:
            pass
        try:
            from . import structure as _st
            import datetime as _dt
            as_of = self.trade_date or _dt.date.today().isoformat()
            d = _st.compute_cached(code, as_of)
            if d.get("ok"):
                out["结构"] = {k: d.get(k) for k in
                              ("position", "zone", "range_high", "range_low", "range_width_atr",
                               "dist_high_atr", "dist_low_atr", "swing_structure", "pullback_atr",
                               "breakout_quality", "overlap_mean_10", "barbwire_score", "barbwire",
                               "gap_ma20_atr")}
                out["结构说明"] = _st.render(d, "")
        except Exception:
            pass
        return out

    def get_sys1_view(self, codes: list = None) -> dict:
        """小模型（System 1 横截面）对指定股票的"未来 N 日跑赢等权池"**校准概率**。

        它的定位是**参考，不是指令**：样本外 Top10% 的 5 日平均超额 +0.195%（固定因子组合 +0.148%），
        且分位数分层单调（p≤10% 组 -0.601%）—— 说明它有排序能力，但**没有择时能力**
        （见 /api/trader/sys1：预测"明日大盘方向"命中 35% vs 多数类基线 38.9%）。
        信号口径是**截面分位**：它内部只对"这批票里谁更强"负责。
        """
        from . import sys1_xsec as X
        import datetime as _dt
        cs = [str(c).strip() for c in (codes or []) if str(c).strip()]
        if not cs:
            return {"error": "请给出 codes（如 [\"600036\",\"000001\"]）"}
        out = X.predict(cs, as_of=self.trade_date or _dt.date.today().isoformat())
        if out.get("error"):
            return out
        meta = {}
        try:
            import json as _json, os as _os
            from ..api.paths import DATA_DIR as _DD
            _p = _os.path.join(str(_DD), "sys1_xsec.json")
            if _os.path.exists(_p):
                _d = _json.load(open(_p, encoding="utf-8"))
                meta = {"样本外Top10%超额": (_d.get("deciles") or {}).get("top10%", {}).get("mean_excess_pct"),
                        "分位单调性": {k: v.get("mean_excess_pct") for k, v in
                                       ((_d.get("signal_rule") or {}).get("bands") or {}).items()},
                        "AUC": (_d.get("test") or {}).get("auc_calibrated"),
                        "说明": "看多=当日这批里前 10%；中间 80% 无信号；它是统计参考不是指令"}
        except Exception:
            pass
        return {"as_of": out.get("as_of"), "小模型": out.get("rows"),
                "参照系": out.get("reference"), "样本外成绩": meta, "note": out.get("note")}

    def sys1_candidates(self, top: int = 20) -> dict:
        """让小模型从**当前流动性池**里挑出它最看好的 top 只（可按需当起点，再自己核实）。"""
        from . import sys1_xsec as X
        from ..alpha import panel as P
        import datetime as _dt
        as_of = self.trade_date or _dt.date.today().isoformat()
        try:
            uni = P.pick_universe(limit=400, as_of=as_of)
        except Exception as e:
            return {"error": f"取池失败: {str(e)[:80]}"}
        out = X.predict(uni, as_of=as_of)
        if out.get("error"):
            return out
        rows = [r for r in (out.get("rows") or []) if r.get("signal") == "看多"][: int(top or 20)]
        return {"as_of": out.get("as_of"), "池": f"流动性前 {len(uni)} 只", "数量": len(rows),
                "候选": rows,
                "note": "这是小模型的**横截面排序**结果（不是买入清单）："
                        "它只回答'这批里谁相对强'，买不买、买多少仍由你决定并说明理由。"}

    def get_candidates(self, top: int = 10) -> dict:
        src = str(getattr(self, "scoring", "scorecard") or "scorecard")
        if self.trade_date:
            from .replay import _candidates_block
            return _candidates_block(self.trade_date, top_n=int(top or 10),
                                    weights=self.weights, source=src)
        from .context import build_candidates_block
        return build_candidates_block(top_n=int(top or 10), weights=self.weights, source=src)

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
            v = self._discipline_buy(code, qty, ref_price)
            if v:
                return {"可执行": False, "原因": v["message"], "规则": v["rule"].get("kind")}
            return {"可执行": True, "参考价": round(ref_price, 3), "预计成本": round(cost, 2),
                    "下单后单票占比": f"{ratio*100:.1f}%"}
        elif side == "sell":
            p = pos.get(code)
            if not p or p["qty"] <= 0:
                return {"可执行": False, "原因": "没有该股票持仓"}
            available = p["qty"] - p["frozen_qty"]
            if available < qty:
                return {"可执行": False, "原因": f"可卖不足：持仓 {p['qty']}，冻结 {p['frozen_qty']}"}
            today = self.trade_date or __import__("datetime").date.today().isoformat()
            if p.get("last_buy_date") and p["last_buy_date"] == today:
                return {"可执行": False, "原因": "T+1：今日买入不可卖出"}
            proceeds = ref_price * qty * (1 - engine.COMMISSION_RATE - engine.STAMP_TAX_RATE)
            return {"可执行": True, "参考价": round(ref_price, 3), "预计到账": round(proceeds, 2)}
        return {"可执行": False, "原因": "方向必须是 buy 或 sell"}

    # ── 写入 ──
    def place_order(self, code: str, side: str, qty: int, order_type: str = "market",
                    price: float = 0, name: str = "", reason: str = "") -> dict:
        """直接下单（市价立即成交 / 限价挂单），返回交易系统的真实结果。"""
        code = str(code or "").strip()
        side = str(side or "").lower()
        order_type = str(order_type or "market").lower()
        name = str(name or "").strip()
        reason = str(reason or "").strip()
        try:
            qty = int(qty)
        except Exception:
            return {"error": "数量非法"}
        if self.dry_run:
            return {"error": "演练模式：未实际下单"}

        if side == "buy":
            ref_try = float(price) if order_type == "limit" and price else self._price(code)
            if ref_try:
                v = self._discipline_buy(code, qty, float(ref_try))
                if v:
                    rec = {"code": code, "name": name, "side": "buy", "qty": qty,
                           "reason": reason, "ok": False, "detail": v["message"],
                           "rule": v["rule"].get("kind")}
                    self.plan.append(rec)
                    self.executions.append(dict(rec))
                    return {"error": v["message"], "提示": "这是交易系统的纪律规则（自省结论已生效），请按拒绝原因调整，不要重复下单。"}

        engine = self._engine()
        ref = (float(price) if order_type == "limit" and price else self._price(code))
        if not ref or ref <= 0:
            return {"error": f"无法获取 {code} 的当前价格"}

        order, trade = engine.place_order(
            self.account_id, code, name or code, side, order_type,
            ref if order_type == "limit" else 0, qty, current_price=ref,
            trade_date=self.trade_date)
        rec = {"code": code, "name": name, "side": side, "order_type": order_type,
               "qty": qty, "reason": reason, "ok": False, "detail": ""}

        if order is None:
            rec["detail"] = str(trade)
            self.plan.append(rec)
            self.executions.append(dict(rec))
            return {"error": str(trade)}

        # 限价单挂单后立即以当前价尝试撮合（否则可能长期冻结资金）
        if trade is None:
            try:
                filled = engine.check_orders(self.account_id, code, ref,
                                             trade_date=self.trade_date)
            except Exception:
                filled = []
            if filled:
                trade = filled[0]
                order = None

        if trade:
            rec.update({"ok": True, "price": round(float(trade["price"]), 3),
                        "qty": int(trade["qty"]),
                        "commission": round(float(trade.get("commission") or 0), 2),
                        "stamp_tax": round(float(trade.get("stamp_tax") or 0), 2),
                        "detail": "已成交" if order_type == "market" else "已成交(限价撮合)"})
            if side == "buy":
                self.new_buys_today += 1
            self.plan.append(rec)
            self.executions.append(dict(rec))
            self._after_fill(engine, side, code, reason)
            return {"状态": "已成交", "代码": code, "方向": side,
                    "成交价": rec["price"], "数量": rec["qty"],
                    "手续费": rec["commission"], "印花税": rec["stamp_tax"]}

        rec.update({"ok": True, "price": round(float(order["price"]), 3),
                    "qty": int(order["qty"]), "order_id": order["id"],
                    "detail": "已挂限价单，未成交"})
        self.plan.append(rec)
        self.executions.append(dict(rec))
        return {"状态": "已挂单未成交", "代码": code, "委托价": rec["price"],
                "数量": rec["qty"], "委托单ID": order["id"],
                "提示": "未成交的委托会冻结资金，可调用 cancel_order 撤销"}

    def _after_fill(self, engine: TradeEngine, side: str, code: str, reason: str) -> None:
        """成交后的长期记忆维护。"""
        if side == "buy":
            if reason:
                store.add_memory(self.profile_id, reason, kind="thesis",
                                 code=code, decision_id=self.decision_id)
        else:
            still = [p for p in engine.get_positions(self.account_id) if p["code"] == code]
            if not still:
                store.resolve_memory_by_code(self.profile_id, code, kind="thesis")

    def cancel_order(self, order_id: int) -> dict:
        ok, msg = self._engine().cancel_order(int(order_id))
        return {"状态": "已撤单"} if ok else {"error": str(msg)}

    def remember(self, content: str, kind: str = "note", code: str = "") -> dict:
        content = str(content or "").strip()
        if not content:
            return {"error": "内容为空"}
        self.notes.append({"kind": kind if kind in ("thesis", "style", "lesson", "note", "market") else "note",
                           "code": str(code or ""), "content": content[:1000]})
        return {"状态": "已记入长期记忆"}

    def submit_decision(self, thinking: str, reflection: str = "",
                        outlook: Optional[dict] = None) -> dict:
        """结束今日决策。outlook = 对**次一交易日**自己账户净值方向的预测：
        {"direction": "up|down|flat", "confidence": 0-100, "target": "...", "reason": "..."}
        （系统次日用真实净值自动打分，长期统计校准度。）"""
        from . import outlook as outlook_mod
        self.decision = {
            "thinking": str(thinking or "").strip(),
            "reflection": str(reflection or "").strip(),
        }
        norm = outlook_mod.normalize_outlook(outlook) if outlook else {}
        if norm:
            self.decision["outlook"] = norm

        # 校验（schema + 取值 + 一致性）：不过就把问题作为工具结果返回，模型可补齐后重新提交
        from . import protocol as protocol_mod
        problems = protocol_mod.validate_decision(self.decision)
        if problems:
            return {"error": "决策未通过校验，请补齐后重新调用 submit_decision",
                    "问题": problems}
        tip = (outlook_mod.CN.get(norm.get("direction"), "") + f" {norm.get('confidence'):g}%")
        # 自洽性检查（说法 vs 动作）：提示而非拒绝，但会在同一次决策里回给模型，便于它当场解释或修正
        issues = []
        try:
            from . import coherence as coh_mod
            acct = {}
            try:
                acct = self.engine.get_summary(self.account_id) or {}
            except Exception:
                acct = {}
            issues = coh_mod.check(self.decision, self.plan, acct)
            if issues:
                self.decision["coherence"] = issues
        except Exception:
            issues = []
        out = {"状态": "今日决策已记录", "委托数": len(self.plan), "预测": tip,
               "闸门": "已完成 M4/M7 的说明" if len(self.decision.get("thinking") or "") >= 200 else "建议更详细"}
        if issues:
            out["一致性问题（提示，不阻塞）"] = [x["msg"] for x in issues]
        return out

    # ── 调度 ──
    _RESERVED = ("execute", "decision", "notes", "log", "plan", "executions",
                 "account_id", "profile_id", "risk_rules", "decision_id", "dry_run",
                 "weights", "rejections", "new_buys_today")

    def execute(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_") or name in self._RESERVED:
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
        "description": ("获取系统按配置口径（评分卡/因子组合）算好的候选股。"
                        "注意：若你的档案是「自主选股」模式，这里会返回空，请改用 screen_stocks 自行检索。"),
        "parameters": {"type": "object", "properties": {
            "top": {"type": "integer", "description": "条数，默认10"}}}}},
    {"type": "function", "function": {
        "name": "screen_stocks",
        "description": ("**自主选股主力工具**：按条件筛选全市场并按某维度排序，返回前 N 只及其全部指标。"
                        "可用维度：close 收盘价(元)、circ_mv 流通市值(亿元，=成交量÷换手率×收盘价)、"
                        "amount_ma20 20日均额(亿)、turnover_ma5 5日均换手(%)、ret20/ret60/ret250 涨跌幅(%)、"
                        "amp 20日平均振幅(%)、vol20 年化波动(%)、pos60 60日区间位置(0~1)、amount_ratio 量比。"
                        "条件写法：<维度>_min / <维度>_max（如 circ_mv_max=50、ret60_min=0），"
                        "另支持 exclude_st（默认 true，剔除 ST 代理）。"),
        "parameters": {"type": "object", "properties": {
            "filters": {"type": "object", "description": "筛选条件，如 circ_mv_max=50 与 ret60_min=0（写成对象）"},
            "sort_by": {"type": "string", "description": "排序维度，默认 circ_mv"},
            "ascending": {"type": "boolean", "description": "true=升序（如按市值最小排）"},
            "limit": {"type": "integer", "description": "返回条数，默认 20，最多 100"}}}}},
    {"type": "function", "function": {
        "name": "get_stock_factors",
        "description": "单只股票的全部可用指标（流通市值/各周期涨跌幅/换手/振幅/波动/60日位置/ST代理），用于验证候选。",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "股票代码"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "preview_order",
        "description": ("下单前让交易系统预检一笔委托能否被接受（只读，不成交），返回结果与原因。"),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "price": {"type": "number", "description": "限价单价格；市价单填0"},
            "qty": {"type": "integer", "description": "数量，100 的整数倍"}},
            "required": ["code", "side", "qty"]}}},
    {"type": "function", "function": {
        "name": "place_order",
        "description": ("直接下单（真实操作，不是模拟）。市价单立即成交；限价单若价格可立即成交则立即成交，"
                        "否则进入待成交并冻结资金。交易系统会校验资金与规则，不符合则拒绝并返回原因。"
                        "买入的 reason 会记为该持仓的长期逻辑。"),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "股票代码"},
            "name": {"type": "string", "description": "股票名称"},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "qty": {"type": "integer", "description": "数量"},
            "order_type": {"type": "string", "enum": ["market", "limit"], "description": "默认 market"},
            "price": {"type": "number", "description": "限价单价格；市价单填0"},
            "reason": {"type": "string", "description": "这笔操作的理由"}},
            "required": ["code", "side", "qty"]}}},
    {"type": "function", "function": {
        "name": "cancel_order",
        "description": ("撤销一笔未成交的限价委托（order_id 见上下文中的「待成交委托」）。"
                        "长期未成交的委托会冻结资金，如需重新决策请先撤销。"),
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer", "description": "委托单 ID"}},
            "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": ("写入长期记忆。kind=style 记录你对自己的风格/方法论的认识（会作为下次决策的自我认知回给你）；"
                        "kind=thesis 记录某持仓的买入逻辑；kind=lesson 经验教训；kind=note 一般观察；kind=market 市场判断。"),
        "parameters": {"type": "object", "properties": {
            "content": {"type": "string", "description": "记忆内容，简洁具体"},
            "kind": {"type": "string", "enum": ["thesis", "style", "lesson", "note", "market"]},
            "code": {"type": "string", "description": "相关股票代码（thesis 填）"}},
            "required": ["content"]}}},
    {"type": "function", "function": {
        "name": "get_sys1_view",
        "description": ("小模型（System 1 横截面模型）对指定股票给出的「未来 5 日跑赢等权池」**校准概率**"
                        "与截面分位信号。样本外：Top10% 组 5 日平均超额 +0.195%（固定因子组合 +0.148%），"
                        "分位分层单调（后 10% 组 -0.601%）。它是**统计参考不是指令**，"
                        "信号口径为截面分位（看多=这批前 10%，中间 80% 无信号）。"),
        "parameters": {"type": "object", "properties": {
            "codes": {"type": "array", "items": {"type": "string"},
                      "description": "要评估的股票代码列表，如 [\"600036\", \"000001\"]"}},
            "required": ["codes"]}}},
    {"type": "function", "function": {
        "name": "sys1_candidates",
        "description": ("让小模型从当前**流动性池**（约 400 只）里按其横截面概率挑出最看好的若干只。"
                        "适合在你自己没有思路时当**起点**：拿到名单后仍需你用结构/基本面核实并说明理由。"
                        "注意它不择时（预测大盘方向的能力已被证伪），只做横截面排序。"),
        "parameters": {"type": "object", "properties": {
            "top": {"type": "integer", "description": "取前几只（默认 20）"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "submit_decision",
        "description": ("结束今日决策并记录你的思考与复盘。交易已通过 place_order 完成，"
                        "这里只写文字总结；不操作时也要调用以结束。"),
        "parameters": {"type": "object", "properties": {
            "thinking": {"type": "string", "description": "今日完整分析（市场/持仓/候选/新闻如何影响你的判断）"},
            "reflection": {"type": "string", "description": "对上一交易日的复盘与经验（首次可为空）"},
            "outlook": {
                "type": "object",
                "description": ("对**次一交易日自己账户净值**方向的预测；系统次日用真实净值自动打分，"
                                "长期统计命中率与 Brier 分数（请如实给，别一律高置信）"),
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "flat", "abstain"],
                                  "description": "看涨/看跌/看平（±0.3% 以内算平）；真的看不清就填 abstain"
                                                 "（弃权，不计命中、不污染校准）"},
                    "confidence": {"type": "number", "description": "置信度 0-100（50 ≈ 掷硬币）"},
                    "target": {"type": "string", "description": "预测主要依据的标的或指数，可空"},
                    "reason": {"type": "string", "description": "一句话依据"}},
                "required": ["direction", "confidence"]}},
            "required": ["thinking"]}}},
]

WRITE_TOOLS = {"place_order", "cancel_order", "remember", "submit_decision"}
