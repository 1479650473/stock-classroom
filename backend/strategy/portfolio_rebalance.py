# -*- coding: utf-8 -*-
"""组合级重平衡选股器 — 把 portfolio_value_alloc(价值tilt) 接进真正的重平衡决策。

当前闭环(ResearchLoop)是"单票下单", 没有"重平衡组合"这一步. 本模块补齐这一步:
给定选股契约(因子权重 / top_k / 调仓周期 / 成本) + 每日截面信号(含价值tilt),
在每个调仓日:
  ① compute composite score —— 价值层权重 w_value 由 portfolio_value_alloc()(三路信号多数决)决定
     (收缩/顺风增配价值层, 扩张/逆风减配) —— 这就是价值从"单票硬裁决"到"组合层权重"的生产接线点;
  ② 选 top-K 目标组合(等权);
  ③ reconcile(卖先买后, A股整数手, 受现金/可交易现金约束) → 产出调仓交易列表.

与 verify_portfolio_framework/optimize 的"组合回测"不同: 这里产出的是**可下单的调仓计划**,
可接到 paper 账户逐笔下单. 信号源 signal_fn(date)->dict 可插拔(默认真实: 指数regime+宽度+价值价差).

契约: The composite = w_value*w_bp*z(BP) + w_rev*z(REVERSAL_20) + w_low*z(-VOLATILITY_20),
其中 w_value 来自 portfolio_value_alloc (fav/neu/head → 1.5/1.0/0.3), 可由契约覆盖.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd


# 价值层权重档(组合层分配器默认) —— 与 decision_gate.PORTFOLIO_W_* 对齐
W_FAV, W_NEU, W_HEAD = 1.5, 1.0, 0.3


@dataclass
class SelectionContract:
    """组合选股契约(声明式, 与 validate_value_selection 同族但扩展为多因子)."""
    factors: list = field(default_factory=lambda: ["BP", "REVERSAL_20", "VOLATILITY_20"])
    base_weights: dict = field(default_factory=lambda: {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0})
    top_k_pct: float = 0.2
    rebalance_bars: int = 20
    fee: float = 0.0005
    slippage: float = 0.0005
    min_lot: int = 100
    use_tilt: bool = True
    tilt_weights: dict = field(default_factory=lambda: {"fav": W_FAV, "neu": W_NEU, "head": W_HEAD})
    initial_balance: float = 100000.0

    @property
    def start(self) -> str:
        return "2018-01-01"

    def for_regime(self, regime_cn: str) -> "SelectionContract":
        """按市场环境(牛/熊/震荡)返回调整了权重的新契约副本.

        蓝图: 权重计算受大盘周期 + 策略周期控制. 相同的因子集合, 但基础权重随
        regime 动态(牛市重动量/反转, 熊市重价值/低波, 震荡均衡). 多因子契约才有意义;
        单因子契约(如纯BP)不动.
        """
        from .regime import regime_base_weights
        import copy
        new = copy.deepcopy(self)
        new.base_weights = regime_base_weights(regime_cn, self.base_weights)
        return new


def _xs_z(panel: pd.DataFrame, date: pd.Timestamp):
    x = pd.to_numeric(panel.loc[date], errors="coerce")
    x = x.replace([math.inf, -math.inf], pd.NA).dropna()
    if len(x) < 5:
        return None
    sd = float(x.std())
    if not math.isfinite(sd) or sd == 0.0:
        return pd.Series(1.0 / max(1.0, len(x)), index=x.index)  # 平手权重(无区分度→近等权)
    return (x - x.mean()) / sd


def composite_score(factor_z: dict, contract: SelectionContract, w_value: float) -> Optional[pd.Series]:
    """拼价值tilt后的综合分(并集对齐, 缺失因子补0=中性).

    factor_z: {FACTOR: z-Series}. 用**并集**对齐(而非严格交集): 某股缺某因子 → 该因子贡献0(z-score中性=无信号),
    让截面**遍及全池**, 避免交集过小(top-K塌到1只). 价值层权重 w_value 仅作用于 BP(use_tilt=True)."""
    if not factor_z:
        return None
    idx = None
    for s in factor_z.values():
        if s is None:
            continue
        idx = s.index if idx is None else idx.union(s.index)
    if idx is None or len(idx) < 5:
        return None
    total = {}
    for f, s in factor_z.items():
        if s is None:
            continue
        w = contract.base_weights.get(f, 1.0)
        if f == "BP" and contract.use_tilt:
            w *= w_value   # 价值层权重随 tilt 调节(任务①生产接线)
        total[f] = w * s.reindex(idx).fillna(0.0)
    if not total:
        return None
    out = sum(total.values())
    return out.fillna(0.0)


def select_top_k(score: pd.Series, k_pct: float) -> list:
    n = max(1, int(len(score) * k_pct))
    return list(score.nlargest(n).index)


def reconcile_holdings(holdings: dict, target: dict, prices: dict, cash: float,
                       min_lot: int = 100, fee: float = 0.0005) -> list:
    """产出从 holdings → target 的调仓交易(卖先买后, A股整数手, 受现金约束).

    holdings: {code: qty}; target: {code: weight(0~1)}; prices: {code: 现价};
    cash: 可动现金. 返回 [{'code','side','qty','price','value','est_fee'}, ...]."""
    codes = set(holdings) | set(target)
    trades = []
    # 卖出超配/清仓仓位(先卖, 释放现金)
    for c in codes:
        if c not in holdings:
            continue
        w = target.get(c, 0.0)
        p = prices.get(c)
        if p is None or p <= 0:
            continue
        want = w * (cash + sum(holdings.get(x, 0) * prices.get(x, 0) for x in codes)) if w > 0 else 0.0
        want_qty = int((want / p) / min_lot) * min_lot if want > 0 else 0
        cur_qty = holdings[c]
        if want_qty <= cur_qty:
            sell = cur_qty - want_qty
            sell = int(sell / min_lot) * min_lot
            if sell >= min_lot:
                trades.append({"code": c, "side": "sell", "qty": sell, "price": p,
                               "value": sell * p, "est_fee": sell * p * fee})
    buys = {c: 0 for c in codes}
    for c in codes:
        w = target.get(c, 0.0)
        p = prices.get(c)
        if p is None or p <= 0:
            continue
        want_equity = w * (cash + sum(holdings.get(x, 0) * prices.get(x, 0) for x in codes))
        want_qty = int((want_equity / p) / min_lot) * min_lot
        cur = holdings.get(c, 0)
        if want_qty > cur:
            buys[c] = want_qty - cur
    # 买入(受现金约束, 按价值降序优先)
    spend = 0.0
    for c, qty in sorted(buys.items(), key=lambda kv: -kv[1] * prices.get(kv[0], 0)):
        p = prices.get(c)
        if p is None or p <= 0:
            continue
        qty = int(qty / min_lot) * min_lot
        if qty < min_lot:
            continue
        cost = qty * p * (1.0 + fee)
        if cash - spend < cost:
            # 现金不足 → 降手数
            aff = int((cash - spend) / (p * (1.0 + fee)) / min_lot) * min_lot
            qty = min(qty, aff)
            if qty < min_lot:
                continue
            cost = qty * p * (1.0 + fee)
        trades.append({"code": c, "side": "buy", "qty": qty, "price": p,
                       "value": qty * p, "est_fee": qty * p * fee})
        spend += cost
    return trades


class RebalancePlanner:
    """真实重平衡选股器: 每调仓日算目标组合 + 调仓计划.

    signal_fn(date)->dict: 返回 {index_tilt, breadth, value_spread} (可插拔, 便于确定性测试).
    tilt 接线: portfolio_value_alloc(index_tilt, breadth, value_spread) → w_value(价值层权重)."""

    def __init__(self, contract: SelectionContract, signal_fn: Optional[Callable] = None):
        self.c = contract
        self.signal_fn = signal_fn or self._real_signals
        self._engine = None

    def _engine_arg(self):
        if self._engine is None:
            from .factor_research import FactorResearchEngine
            self._engine = FactorResearchEngine()
        return self._engine

    def _real_signals(self, date: pd.Timestamp):
        """真实三路信号: 指数regime(value_tilt_state) / 市场宽度(market_breadth) / 价值价差(BP多空动量)."""
        from ..agent.decision_gate import value_tilt_state, market_breadth
        it = value_tilt_state()
        br = market_breadth()
        # 价值价差: 用本池 BP 多空(懒加载)
        # (真实场景常批量; 这里置 None → 分配器按中性处理)
        return {"index_tilt": it, "breadth": br, "value_spread": None}

    def plan_at(self, date: pd.Timestamp, frames: dict, holdings: dict,
                cash: float) -> dict:
        """在 date 计算目标组合 + 相对 holdings 的调仓计划."""
        from ..agent.decision_gate import portfolio_value_alloc
        eng = self._engine_arg()
        close = eng._panel(frames, "close")
        factor_z = {}
        for f in self.c.factors:
            panel = eng._factor_panel(frames, f, close)
            z = _xs_z(panel, date)
            if z is None:
                continue
            factor_z[f] = z
        sig = self.signal_fn(date)
        alloc = portfolio_value_alloc(index_tilt=sig.get("index_tilt"),
                                      breadth=sig.get("breadth"),
                                      value_spread=sig.get("value_spread"))
        w_value = alloc["w_value"] if self.c.use_tilt else 1.0
        score = composite_score(factor_z, self.c, w_value)
        if score is None:
            return {"date": date, "tilt": alloc, "top": [], "target": {}, "trades": [], "score": None}
        top = select_top_k(score, self.c.top_k_pct)
        # 取**调仓日当日 close** 给"目标 ∪ 当前持仓"全部计价(否则 reconcile 对不在目标的持仓没价→卖不掉/低估权益)
        need = set(top) | set(holdings.keys())
        prices = {}
        if date in close.index:
            row = close.loc[date]
            for c in need:
                v = row.get(c, pd.NA)
                if v is not None and not pd.isna(v):
                    prices[c] = float(v)
        for c in need:
            if c not in prices:
                df = frames.get(c)
                if df is not None and len(df):
                    prices[c] = float(df["close"].iloc[-1])
        target = {c: 1.0 / len(top) for c in top} if top else {}
        trades = reconcile_holdings(holdings, target, prices, cash,
                                    self.c.min_lot, self.c.fee)
        return {"date": date, "tilt": alloc, "w_value": w_value, "top": top,
                "target": target, "trades": trades, "score": score}

    def run_window(self, frames: dict, start: str, end: str):
        """跑一个调仓窗口: 逐调仓日 plan, 返回 plan list."""
        eng = self._engine_arg()
        close = eng._panel(frames, "close")
        loc = close.loc[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
        rebal = list(loc.index[:: self.c.rebalance_bars])
        plans = []
        for d in rebal:
            plans.append(self.plan_at(d, frames, holdings={}, cash=self.c.initial_balance))
        return plans


# ── ① 按持有期自适应组合配置器(非人工判断) ─────────────────────────────
# 实证(verify_hp5_mechanism): 多因子分层(z(BP)+z(REV20)-z(VOL20)) 的 GROSS 在所有持有期都优于单因子,
# 但**短持有(HP<20)下分层高换手被成本吞噬**(HP=5 成本拖累 +33.13%, 分层 NET 2.381<价值 2.466);
# 而价值(BP) rank自相关≈0.99, 短持有几乎不换手(0.086). 故按持有期自适应:
#   HP >= HP_LAYER_MIN → 多因子分层(价值+反转+低波动);
#   HP <  HP_LAYER_MIN → 降为低换手价值层(BP)防成本吞噬.
HP_LAYER_MIN = 20


def adaptive_config_for_hp(rebalance_bars: int, top_k_pct: float = 0.2,
                           initial_balance: float = 100000.0) -> SelectionContract:
    """按持有期自动选组合配置(把"分层用HP≥20/短持有降价值层"从人工判断变成规则).

    rebalance_bars>=HP_LAYER_MIN(20) → 多因子分层(价值+反转+低波动等权);
    否则(短持有如5) → 低换手价值层(BP) —— 单因子, 少换手, 防成本吞噬.
    """
    bars = max(1, int(rebalance_bars))
    if bars >= HP_LAYER_MIN:
        return SelectionContract(
            factors=["BP", "REVERSAL_20", "VOLATILITY_20"],
            base_weights={"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0},
            top_k_pct=top_k_pct, rebalance_bars=bars, initial_balance=initial_balance)
    return SelectionContract(
        factors=["BP"],
        base_weights={"BP": 1.0},
        top_k_pct=top_k_pct, rebalance_bars=bars, initial_balance=initial_balance)


# 5 策略家族的因子/权重(数据驱动轮换用; 与 _strategy_contracts 同构)
STRATEGY_FACTORS = {
    "F价值Tilt": (["BP", "REVERSAL_20", "VOLATILITY_20"], {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}, True),
    "D多因子": (["BP", "REVERSAL_20", "VOLATILITY_20"], {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}, False),
    "A价值": (["BP"], {"BP": 1.0}, True),
    "B反转": (["REVERSAL_20"], {"REVERSAL_20": 1.0}, False),
    "C低波动": (["VOLATILITY_20"], {"VOLATILITY_20": -1.0}, False),
}


def rotated_contract(hp: int = 20, top_k_pct: float = 0.2, initial_balance: float = 100000.0,
                     regime_cn: str = None) -> SelectionContract:
    """判断器驱动的**轮换契约**(数据驱动): 按当前市场环境主策略构造 SelectionContract.

    读 data/regime.json 的 rotation.primary(当前环境主策略), 用对应因子/权重构造契约;
    读不到/环境不明/策略未知名 → 回退 adaptive_config_for_hp(现有规则).
    供 portfolio_paper/agentops 在无显式 contract 时自动用当前环境主策略做组合重平衡
    (架构图"周期性策略轮换"落地: 牛→B反转进攻 / 震荡→F价值Tilt / 熊→C低波动防守).

    若显式传 regime_cn 则忽略文件(供测试/强制轮换).
    """
    if regime_cn is None:
        try:
            import os as _os, json as _json
            _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                               "data", "regime.json")
            if _os.path.exists(_p):
                with open(_p, encoding="utf-8") as f:
                    _j = _json.load(f)
                regime_cn = _j.get("regime_cn")
        except Exception:
            regime_cn = None
    if regime_cn:
        from ..strategy.regime import rotate_strategy
        primary = rotate_strategy(regime_cn).get("primary")
        if primary and primary in STRATEGY_FACTORS:
            factors, weights, use_tilt = STRATEGY_FACTORS[primary]
            return SelectionContract(factors=factors, base_weights=dict(weights),
                                     use_tilt=use_tilt, top_k_pct=top_k_pct,
                                     rebalance_bars=max(1, int(hp)),
                                     initial_balance=initial_balance)
    # 回退: 现有规则(HP分层)
    return adaptive_config_for_hp(hp, top_k_pct=top_k_pct, initial_balance=initial_balance)


# ── ② 多期组合 forward paper(真调仓循环, paper-only) ──────────────────
def forward_paper_run(frames: dict, contract: SelectionContract, start: str, end: str,
                      signal_fn: Optional[Callable] = None,
                      initial_balance: Optional[float] = None,
                      as_of_price: bool = True) -> dict:
    """多期组合 forward paper(paper-only): 每个调仓日读账户现金/持仓 → 算目标 → 调仓 → mark-to-market.

    与 run_window(只算计划)不同: 这里**真实追踪现金与持仓**, 每期 reconcile+apply 交易, 逐期 mark-to-market,
    返回 {dates, nav_g, nav_n, final_holdings, final_cash, turnover_avg, cost_total, rebalances}.
    paper-only(本部署无实盘), 无前视(信号用≤date close, 成交用下一日/当日, 价取自调仓日 close).
    """
    import pandas as _pd
    from .factor_research import FactorResearchEngine
    eng = FactorResearchEngine()
    close = eng._panel(frames, "close")
    loc = close.loc[(close.index >= _pd.Timestamp(start)) & (close.index <= _pd.Timestamp(end))]
    rebal = list(loc.index[:: contract.rebalance_bars])
    cash = float(initial_balance if initial_balance is not None else contract.initial_balance)
    holdings: dict = {}
    planner = RebalancePlanner(contract, signal_fn=signal_fn)
    dates, nav_g, nav_n = [], [], []
    turnovers, cost_total = [], 0.0
    rebalances = 0
    daily_holdings = []   # 每调仓日持仓快照 {date, holdings, cash, nav}
    rebalance_log = []    # 每调仓日买卖明细 {date, trades:[{code,side,qty,price,pnl}]}
    prev_set = set()
    cost_basis = {}       # code -> 持仓成本单价(加权) 供卖出 pnl 计算

    def _mark(date):
        row = close.loc[date] if date in close.index else None
        val = cash if row is None else 0.0
        if row is not None:
            for c, q in holdings.items():
                v = row.get(c, _pd.NA)
                if q > 0 and v is not None and not _pd.isna(v):
                    val += q * float(v)
            val += cash
        return val

    for dt in rebal:
        plan = planner.plan_at(dt, frames, holdings, cash)
        trades = plan.get("trades", [])
        # apply trades(真实现金/持仓更新) + 记录每笔(含正确 pnl)
        _all_t = []
        for t in trades:
            q, p, side = int(t["qty"]), float(t["price"]), t["side"]
            if side == "buy":
                cost = q * p * (1.0 + contract.fee)
                cash -= cost
                old_q = holdings.get(t["code"], 0)
                new_q = old_q + q
                # 加权成本单价(含已持仓)
                if new_q > 0:
                    cost_basis[t["code"]] = ((cost_basis.get(t["code"], 0.0) * old_q) + (q * p)) / new_q
                holdings[t["code"]] = new_q
                _all_t.append({"code": t["code"], "side": "buy", "qty": q, "price": p, "pnl": None})
            else:
                cash += q * p * (1.0 - contract.fee)
                cb = cost_basis.get(t["code"], p)
                pnl = (p - cb) * q   # 卖出盈亏(不含费用)
                _all_t.append({"code": t["code"], "side": "sell", "qty": q, "price": p,
                               "pnl": round(pnl, 2)})
                holdings[t["code"]] = holdings.get(t["code"], 0) - q
                if holdings[t["code"]] <= 0:
                    holdings.pop(t["code"], None)
                    cost_basis.pop(t["code"], None)
                else:
                    pass  # 减仓后成本单价维持(加权已反映)
            cost_total += q * p * contract.fee
        rebalance_log.append({"date": str(dt), "trades": _all_t})
        # mark-to-market(用调仓日 close 定价); GROSS≈净(已计fee现金), NET 另计换手成本
        nv = _mark(dt)
        dates.append(str(dt))
        nav_n.append(nv)
        cur = set(holdings.keys())
        turn = 0.0 if not prev_set else 1.0 - len(prev_set & cur) / max(len(prev_set | cur), 1)
        turnovers.append(turn)
        cost_total += turn * len(cur) * 0.0  # 换手成本已在 fee 内
        rebalances += 1
        prev_set = cur
        # 记录每调仓日持仓快照(供持仓面板/收益曲线)
        daily_holdings.append({"date": str(dt), "holdings": dict(holdings), "cash": cash, "nav": nv})
    return {"dates": dates, "nav_n": nav_n, "final_holdings": holdings, "final_cash": cash,
            "turnover_avg": (sum(turnovers) / len(turnovers)) if turnovers else 0.0,
            "cost_total": cost_total, "rebalances": rebalances,
            "daily_holdings": daily_holdings, "rebalance_log": rebalance_log}
