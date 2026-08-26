# -*- coding: utf-8 -*-
"""M1 研究代理主循环 — LLM 消费 gateway 完成"生成→回测→复盘→修订→择优→paper"闭环。

架构(对齐 QuantDinger 的 P5 自主策略 AI)：
- 后端(backend): 真正的 LLM(LLMBackend, 读 settings.json) 或 确定性 Stub(无 key 验证)。
  只产出 **声明式 JSON 策略契约**(复用 StrategySpec + DSL 因子词表)，绝不写任意代码——安全红线。
- 网关网关(gw): GatewayClient(HTTP, 真实外部代理) 或 InProcessGw(进程内复用 services/jobs, 自包含验证)。
  两者实现同一接口，ResearchLoop 逻辑一致。
- 闭环: 读宏观(regime) → 选标的域(catalog) → 生成策略(JSON) → 建策略 → 异步回测 →
  复盘(LLM 依据指标修订) → 再回测 → 多轮择优(评分) → 上 paper 盘(求当前信号, 有则下单)。

用法(见 verify_research_loop.py)。无 LLM key 时用 StubBackend 也能跑通全流程。
"""
from __future__ import annotations

import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import gateway as gw_mod, services as svc, jobs as jobs_mod
from .decision_gate import BaseDecisionGate  # noqa: F401
from ..strategy.spec import StrategySpec
from ..strategy import factors as fac_mod
from ..factor_engine.dsl import evaluate as eval_dsl


# ────────────────────────── 后端(LLM) ────────────────────────────────
class BaseBackend:
    name = "base"

    def generate(self, context: dict) -> dict:
        raise NotImplementedError

    def review(self, prev: dict, metrics: dict, context: dict) -> dict:
        raise NotImplementedError


class LLMBackend(BaseBackend):
    """真实 LLM：构建严格提示 → 只允许输出声明式 JSON 契约(用给定因子词表)。"""

    name = "llm"

    def __init__(self):
        from .llm_client import LLMClient, extract_json, LLMError
        self._client = LLMClient()
        self._extract = extract_json

    # 系统提示: 强约束, 禁止写代码/越界因子
    _SYSTEM = (
        "你是 A 股量化策略研究员。只能输出一个符合给定 JSON Schema 的策略契约，"
        "这是一个声明式 JSON，不是 Python 代码。禁止输出任何可执行代码、禁止使用因子词表之外的键。"
        "A 股约束: T+1 禁做空(allow_short 必须 False)；entry/exit 是 factor_engine/dsl 条件树；"
        "position_sizing.mode ∈ {percent_of_equity, fixed_qty, fixed_capital}；"
        "risk.intrabar_mode ∈ {conservative, balanced, aggressive}；"
        "risk.stop_loss_pct/take_profit_pct 为小数(如 0.05=5%)；risk.trailing_stop_pct>0 启用移动止损。"
        "直接输出 JSON 对象，不要 markdown 围栏，不要解释。"
    )

    def _prompt(self, context: dict) -> str:
        macro = context.get("macro", {})
        uni = context.get("universe", {})
        factors = context.get("factors", [])
        fkeys = ", ".join(f["key"] for f in factors)
        fdesc = "; ".join(f"{f['key']}={f['desc']}" for f in factors[:20])
        # 研究论证的优先因子(截面 IC/ICIR 验证过)
        rec = context.get("recommended_factor")
        rec_block = ""
        if rec:
            rec_block = (
                "\n【研究论证的优先因子】(已在标的池用截面 IC/ICIR 验证)\n"
                f"factor={rec['dsl_key']} "
                f"方向={'高(越高越好) ' if rec.get('direction') == 1 else '低(越低越好) '}"
                f"IC={rec.get('ic', 0):.3f} ICIR={rec.get('icir', 0):.2f} "
                f"置信度={rec.get('confidence')} 覆盖={rec.get('coverage', 0):.0%}\n"
                "建议优先用该因子(或同族邻窗口因子)构建 entry/exit；若你有充分理由，也可换其他因子。\n"
            )
        # 价值/质量研究证据(基本面 EP/BP/ROE, 截面点时间) —— 供价值选股/低估择时参考
        vrec = context.get("recommended_value_factor")
        vblock = ""
        if vrec:
            vblock = (
                "\n【研究论证的价值因子】(截面基本面, 点时间无前视)\n"
                f"factor={vrec['dsl_key']} "
                f"方向={'高(越便宜越好) ' if vrec.get('direction') == 1 else '低(越低越好) '}"
                f"IC={vrec.get('ic', 0):.3f} ICIR={vrec.get('icir', 0):.2f} "
                f"置信度={vrec.get('confidence')} 覆盖={vrec.get('coverage', 0):.0%}\n"
                "做价值/低估择时优先用该因子(可结合价格因子)。\n"
            )
        return (
            "【全球宏观 regime】\n" + str(macro.get("overall", "")) +
            "\n(风险偏好/利率/商品/波动见 categories)\n\n"
            f"【选定标的域】code={uni.get('code')} name={uni.get('name')} 说明={uni.get('desc','')}\n\n"
            f"【可用因子词表】{fkeys}\n说明: {fdesc}\n\n"
            + rec_block + vblock +
            "【策略契约 Schema】\n"
            '{"name": str, "description": str, "universe": {"code": str, "name": str},\n'
            ' "entry": {DSL树}, "exit": {DSL树|null},\n'
            ' "position_sizing": {"mode": str, "value": float},\n'
            ' "risk": {"stop_loss_pct": float|null, "take_profit_pct": float|null,\n'
            '          "trailing_stop_pct": float, "trailing_activation_pct": float,\n'
            '          "intrabar_mode": str, "time_limit_bars": int, "allow_short": false},\n'
            ' "params": {"initial_balance": float}}\n'
            "DSL 树示例: {\"type\":\"and\",\"args\":[{\"type\":\"gt\",\"args\":[\"CLOSE\",\"MA20\"]}]}\n"
            "请基于宏观与标的语境生成一个你认为稳健的长线做多策略。"
        )

    def generate(self, context: dict) -> dict:
        text = self._client.complete(self._SYSTEM, self._prompt(context))
        return self._validate(self._extract(text), context)

    def review(self, prev: dict, metrics: dict, context: dict) -> dict:
        prompt = (
            "上一版策略回测指标如下:\n" + str(metrics) +
            "\n请复盘(为何亏/是否标定不足/风控是否合适)，并基于宏观语境生成**改进版**策略契约，"
            "输出严格的声明式 JSON(同 Schema)。可调整 entry/exit 阈值、止盈止损、加移动止损。"
        )
        text = self._client.complete(self._SYSTEM, prompt + "\n\n原策略:\n" + str(prev))
        return self._validate(self._extract(text), context)

    def _validate(self, contract: dict, context: dict) -> dict:
        if not contract.get("universe", {}).get("code"):
            contract["universe"] = context["universe"]
        spec = StrategySpec.from_dict(contract)
        spec.validate()
        return spec.to_dict()


# ── 稳健趋势样本(已验证 600036 正收益 +7.14%)，作为研究因子失效时的回退/复盘切换 ──
_PROVEN_ENTRY = {"type": "and", "args": [
    {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
    {"type": "gt", "args": ["CLOSE", "MA20"]},
    {"type": "between", "args": ["RSI14", 40, 70]},
]}
_PROVEN_EXIT = {"type": "or", "args": [
    {"type": "gt", "args": ["RSI14", 75]},
    {"type": "eq", "args": ["MACD_CROSS_DOWN", 1]},
]}


class StubBackend(BaseBackend):
    """确定性后端(无 LLM key 时验证全流程)：生成模板策略，复盘按指标微调风控。"""

    name = "stub"

    def generate(self, context: dict) -> dict:
        uni = context["universe"]
        rec = context.get("recommended_factor")
        initial = context.get("initial_balance", 100000.0)
        # 若研究给出被 IC 支撑的因子 → 用它构建进出场(方向感知)；否则回退到已验证样例
        if rec:
            key = rec["dsl_key"]
            direction = rec["direction"]
            thresh = rec.get("threshold", 0.0)
            op = "gt" if direction == 1 else "lt"
            revop = "lt" if op == "gt" else "gt"
            entry = {"type": op, "args": [key, thresh]}
            exit = {"type": revop, "args": [key, thresh]}
            # 自动选参: ICIR 置信度弱/中 → 附加趋势过滤(收盘>MA20)收紧; 高 → 纯因子
            confidence = rec.get("confidence", "weak")
            if confidence != "high":
                entry = {"type": "and", "args": [entry, {"type": "gt", "args": ["CLOSE", "MA20"]}]}
            name = f"stub-研究因子[{key}]"
            desc = (f"IC={rec['ic']:.3f} ICIR={rec['icir']:.2f} conf={confidence} "
                    f"方向={'高' if direction==1 else '低'} 入场; 反向离场")
        else:
            entry, exit = _PROVEN_ENTRY, _PROVEN_EXIT
            name = "stub-均线金叉+回调(round1)"
            desc = "MA5上穿MA10 且 收盘>MA20 且 RSI14 40~70 买入；RSI>75 或 MACD死叉 卖出；止盈12% 止损5%"
        return {
            "name": name, "description": desc,
            "universe": {"code": uni["code"], "name": uni.get("name", uni["code"])},
            "entry": entry, "exit": exit,
            "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
            "risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12,
                     "trailing_stop_pct": 0.0, "trailing_activation_pct": 0.0,
                     "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
            "params": {"initial_balance": initial},
        }

    def review(self, prev: dict, metrics: dict, context: dict) -> dict:
        """规则式复盘：单标的用研究因子承压(负收益)→切换稳健趋势样本；正收益→微调风控。"""
        import copy
        c = copy.deepcopy(prev)
        risk = c["risk"]
        tr = metrics.get("total_return", 0.0)
        mdd = metrics.get("max_drawdown", 0.0)
        sharpe = metrics.get("sharpe", 0.0)
        if tr < 0 or mdd < -20:
            # 复盘：研究因子在单票上失效 → 切换稳健趋势样本 + 收紧止损
            c["entry"] = copy.deepcopy(_PROVEN_ENTRY)
            c["exit"] = copy.deepcopy(_PROVEN_EXIT)
            c["name"] = "stub-复盘切换稳健趋势"
            c["description"] = "研究因子单票失效，复盘切换为 MA5金叉+回调 稳健趋势"
            risk["stop_loss_pct"] = 0.04
            risk["take_profit_pct"] = 0.15
            risk["trailing_stop_pct"] = 0.0
            risk["trailing_activation_pct"] = 0.0
        else:
            if sharpe < 0.3:
                risk["take_profit_pct"] = round((risk.get("take_profit_pct") or 0.12) + 0.03, 4)
            if c.get("name"):
                c["name"] = c["name"].rsplit("(", 1)[0] + f"(round_{int(time.time())})"
        return c


# ────────────────────────── 网关表面 ─────────────────────────────────
class InProcessGw:
    """进程内网关表面：复用 services + jobs，自包含(无需启动服务器)。"""

    def __init__(self, agent_id: str = "research-loop"):
        self.agent_id = agent_id
        tok = gw_mod.issue_token(agent_id, "R,W,B,T", paper_only=True)
        self.token_id = tok["id"]

    def macro_regime(self) -> dict:
        return svc.macro_regime()

    def catalog_select(self, **kw) -> dict:
        items = svc.catalog_select(**kw)
        return {"items": items, "count": len(items)}

    def factors(self, category: Optional[str] = None) -> list:
        return svc.factors_list(category)

    def create_strategy(self, contract: dict) -> dict:
        return svc.create_strategy(self.token_id, self.agent_id, contract)

    def update_strategy(self, sid: int, contract: dict) -> dict:
        return svc.update_strategy(self.agent_id, sid, contract)

    def get_strategy(self, sid: int) -> dict:
        return svc.get_strategy(self.agent_id, sid)

    def backtest(self, sid: int, params: Optional[dict] = None) -> dict:
        runner = svc.build_backtest_runner(self.agent_id, sid)
        job = jobs_mod.submit_job("backtest", {"strategy_id": sid, "params": params or {}},
                                  runner, self.token_id, self.agent_id)
        for _ in range(120):
            j = jobs_mod.get_job(job["job_id"])
            if j and j.get("status") in ("succeeded", "failed", "cancelled"):
                return j
            time.sleep(0.5)
        return None

    def paper_order(self, payload: dict) -> dict:
        return svc.paper_order(self.token_id, self.agent_id, payload)


# ────────────────────────── 闭环 Runner ──────────────────────────────
def score(metrics: dict) -> float:
    """评分择优：要求正收益+回撤可控，偏爱夏普。返回 -inf 表示不合格。

    metrics 口径: total_return/max_drawdown 为小数(0.05=5%)。
    """
    if not metrics:
        return float("-inf")
    tr = metrics.get("total_return", 0.0)
    mdd = metrics.get("max_drawdown", 0.0) or 0.0
    sharpe = metrics.get("sharpe", 0.0) or 0.0
    if tr <= 0:
        return float("-inf")
    if mdd <= -0.30:
        return float("-inf")
    return round(tr * 0.4 + sharpe * 10 * 0.3 - abs(mdd) * 0.3, 4)


def eval_entry_signal(code: str, contract: dict) -> tuple[bool, float]:
    """在最新一根 bar 上评估策略 entry 信号(用于"上 paper 盘")。返回 (信号, 现价)。"""
    kd, _ = svc.load_klines(code, limit=200)
    if not kd:
        return False, 0.0
    from ..fundamental import attach_kline_fundamentals
    kd = attach_kline_fundamentals(code, kd)
    series = fac_mod.compute_factor_series(kd)
    vals = series[-1] if series else {}
    condition = contract.get("entry")
    signal = bool(eval_dsl(condition, vals)) if condition else False
    return signal, float(kd[-1]["close"])


def _recent_closes(code: str, n: int = 5) -> list:
    """取最近 n 根收盘价(供决策门近端走势上下文)。"""
    kd, _ = svc.load_klines(code, limit=n)
    return [float(k["close"]) for k in kd] if kd else []


@dataclass
class RoundResult:
    round_id: int
    contract: dict
    strategy_id: int
    metrics: dict
    score: float


@dataclass
class LoopResult:
    macro: dict
    universe: dict
    rounds: list = field(default_factory=list)
    best: Optional[RoundResult] = None
    paper: Optional[dict] = None


def build_operate_loop(gw=None, use_llm: bool = True) -> "ResearchLoop":
    """构造"AI操盘"闭环: 有 LLM key → 真 LLM 后端(模型真正决定策略); 无 key → Stub 后端(可验证).

    这是"模拟账户交给模型 agent 操作"的接线点 —— 用户只旁观 ResearchLoop 的逐步推理与下单。
    """
    backend = None
    if use_llm:
        try:
            from .llm_client import LLMError
            backend = LLMBackend()
        except LLMError:
            backend = None
    if backend is None:
        backend = StubBackend()
    return ResearchLoop(backend, gw or InProcessGw())


class ResearchLoop:
    def __init__(self, backend: BaseBackend, gw: Any):
        self.backend = backend
        self.gw = gw

    def run(self, *, rounds: int = 3, universe_code: Optional[str] = None,
            universe_selector: Optional[dict] = None, initial_balance: float = 100000.0,
            paper: bool = False, paper_account_id: Optional[int] = None,
            gate: Optional["BaseDecisionGate"] = None,
            use_factor_research: bool = True, progress: Optional[Callable] = None) -> LoopResult:
        def _emit(msg):   # 进度流: 给"AI操盘"台实时展示 agent 推理/动作
            if progress:
                try:
                    progress(msg)
                except Exception:
                    pass
        # 1) 宏观
        macro = self.gw.macro_regime()
        _emit(f"读取宏观 regime → {macro.get('overall', '')}")
        # 2) 标的域
        universe = self._pick_universe(universe_code, universe_selector, macro)
        _emit(f"选定标的域 → {universe.get('code')} {universe.get('name', '')}")
        factors = self.gw.factors()
        context = {"macro": macro, "universe": universe, "factors": factors,
                   "initial_balance": initial_balance}
        # 2b) 研究→论证→生成: 在标的域池上跑 IC/ICIR, 选出被支撑因子
        if use_factor_research:
            rec = self._recommend_factor(universe, macro)
            context["recommended_factor"] = rec
            if rec:
                _emit(f"因子研究 → 最优 {rec['dsl_key']} IC={rec['ic']:.3f} ICIR={rec['icir']:.2f} "
                      f"方向={'高' if rec['direction']==1 else '低'} 覆盖={rec['coverage']:.0%}")
            else:
                _emit("因子研究 → 未选出显著因子, 回退样例策略")
            # 2c) 价值/质量研究维度(基本面 EP/BP/ROE, 点时间无前视) —— 扩展单日K线之外
            try:
                from ..strategy.factor_selector import study_value_factors, classify_value_records
                pool = self._universe_pool(universe)
                vres = study_value_factors(pool, "2024-01-01", datetime.now().strftime("%Y%m%d"))
                if vres:
                    tagged, vbest = classify_value_records(vres)
                    context["value_research"] = tagged
                    context["recommended_value_factor"] = vbest
                    if vbest:
                        _emit(f"价值/质量研究 → 最强 {vbest['dsl_key']} "
                              f"IC={vbest['ic']:.3f} ICIR={vbest['icir']:.2f} "
                              f"方向={'高' if vbest['direction']==1 else '低'} conf={vbest['confidence']}")
                    else:
                        _emit(f"价值/质量研究 → {len(vres)}因子 | 无显著(全被拒)")
            except Exception as e:
                _emit(f"价值/质量研究跳过 → {type(e).__name__}")
        result = LoopResult(macro=macro, universe=universe)

        # 3) 生成 → 回测 → 复盘修订 多轮
        try:
            _emit("LLM 生成策略契约...")
            contract = self.backend.generate(context)
            _emit(f"策略生成 → {contract.get('name','')} | {contract.get('description','')[:60]}")
        except Exception as e:
            _emit(f"生成失败({type(e).__name__}) → 回退样本策略")
            contract = self._proven_contract(universe, initial_balance)
        for rnd in range(1, rounds + 1):
            sid = self._safe_create(contract)
            if sid is None:
                continue
            _emit(f"回测 第{rnd}轮...")
            job = self.gw.backtest(sid, {"initial_balance": initial_balance})
            job = job or {}
            data = job.get("decoded_result") or job.get("result") or {}
            metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
            rr = RoundResult(rnd, contract, sid, metrics, score(metrics))
            result.rounds.append(rr)
            _emit(f"  第{rnd}轮: 收益 {metrics.get('total_return', 0)*100:+.2f}% "
                  f"回撤 {metrics.get('max_drawdown', 0)*100:.1f}% "
                  f"夏普 {metrics.get('sharpe', 0):.2f} → 评分 {rr.score}")
            if rnd < rounds:
                # 复盘 → 为下一轮准备修订契约(下一轮迭代再创建/回测)
                try:
                    _emit("复盘修订策略...")
                    contract = self.backend.review(contract, metrics, context)
                    _emit(f"  修订 → {contract.get('name','')} | {contract.get('description','')[:60]}")
                except Exception as e:
                    _emit(f"复盘失败({type(e).__name__}) → 保持原策略")
        result.rounds = [r for r in result.rounds if r.metrics]

        # 4) 择优(取评分最高的一轮)
        valid = [r for r in result.rounds if r.score != float("-inf")]
        if valid:
            result.best = max(valid, key=lambda r: r.score)
            _emit(f"择优 → 第{result.best.round_id}轮 (评分 {result.best.score})")

        # 5) 上 paper 盘: 用最优策略的最新 entry 信号 → 先过 AI 决策门(若有)
        if paper and result.best:
            code = result.best.contract["universe"]["code"]
            sig, price = eval_entry_signal(code, result.best.contract)
            payload = {"code": code, "side": "buy", "order_type": "market", "current_price": price}
            if paper_account_id is not None:
                payload["account_id"] = paper_account_id
            entry = sig
            decision = None
            if gate is not None:
                from .decision_gate import value_tilt_state
                dec_ctx = {"macro": macro, "signal": sig, "strategy": result.best.contract,
                           "recent_klines": _recent_closes(code, 5), "price": price,
                           "value_tilt": value_tilt_state()}
                decision = gate.decide(dec_ctx)
                entry = (decision.action == "enter")
            if entry:
                qty = int((initial_balance * 0.95) / price // 100) * 100 if price > 0 else 100
                payload["qty"] = max(qty, 100)
                _emit(f"入场信号触发 → 市价买入 {code} {payload['qty']} 股 @ {price}")
                result.paper = self.gw.paper_order(payload)
                result.paper["signal"] = "long"
                po = result.paper
                _emit(f"下单 → 账户#{po.get('account_id')} {po.get('side')} {po.get('code')} "
                      f"{po.get('code')} {po.get('qty')}股 @ {po.get('filled_price')} "
                      f"状态 {po.get('status')}")
            else:
                result.paper = {"signal": "none",
                                "note": "当前无 entry 信号或决策门暂缓" if not sig else "决策门裁决 hold/exit，暂缓下单"}
                _emit(f"入场检查 → 信号={'有' if sig else '无'}"
                      f"{'但决策门暂缓' if sig else ', 不下单'}")
            if decision is not None:
                result.paper["decision"] = decision.to_dict()
        return result

    def portfolio_paper(self, gw=None, pool=None, contract=None, account_id=None,
                        as_of=None, max_pool: int = 300) -> dict:
        """组合级 paper 盘 —— 把组合重平衡选股器(接 portfolio_value_alloc)挂进主闭环。

        与 run() 的"单票 paper"(一次一票)不同: 这里在账户**当前现金/持仓**上, 用 RebalancePlanner
        算出目标组合(价值层权重 w_value 随 portfolio_value_alloc 三路信号多数决), reconcile 出
        调仓交易, 逐笔走 gw.paper_order 真实下到 paper 账户。即"研究→组合纸面"的一步。
        幂等/保守: 不新建账户(用 account_id 或活跃账户), 不强制买入空信号, 由目标组合决定。
        """
        from ..strategy.portfolio_rebalance import SelectionContract, RebalancePlanner, _xs_z
        from ..strategy.factor_data import load_universe_frames
        from ..strategy.factor_research import FactorResearchEngine
        from ..strategy.factor_selector import build_wide_pool
        from ..strategy.data import load_klines
        from ..trade_engine.engine import TradeEngine
        import math
        import pandas as pd

        gw = gw or self.gw
        contract = contract or SelectionContract()
        # ① 池 + 帧(带 warmup, 让 reversal/vol 预热)
        pool = (pool or build_wide_pool())[:max_pool]
        end = datetime.now().strftime("%Y%m%d")
        frames = load_universe_frames(pool, start="2023-06-01", end=end,
                                      with_fundamentals=True, fetch_missing=False)
        if not frames:
            return {"error": "无池数据", "code": "empty_pool"}

        # ② 面板 + 三路信号源
        eng = FactorResearchEngine()
        close = eng._panel(frames, "close")
        open_ = eng._panel(frames, "open")
        bp = eng._factor_panel(frames, "bp", close)
        rev = eng._factor_panel(frames, "reversal_20", close)
        vol = eng._factor_panel(frames, "volatility_20", close)
        ma = close.rolling(250, min_periods=120).mean()
        breadth_ser = (close > ma).mean(axis=1)

        idx, _ = load_klines("sh000001", limit=4500)
        idx_close = pd.Series([float(k["close"]) for k in idx],
                              index=pd.to_datetime([str(k["date"]) for k in idx],
                                                   format="%Y%m%d", errors="coerce"))
        idx_close = idx_close[idx_close.index.notna()].sort_index()

        def _index_tilt(dt):
            hist = idx_close.loc[idx_close.index <= dt]
            if hist.empty or len(hist) < 30:
                return "value_neutral"
            last = float(hist.iloc[-1]); ma120 = float(hist.rolling(120, min_periods=30).mean().iloc[-1])
            dd = last / max(hist.tail(60)) - 1.0
            if last < ma120 or dd < -0.08:
                return "value_favorable"
            if last > ma120 and dd > -0.05:
                return "value_headwind"
            return "value_neutral"

        def _breadth_tilt(dt):
            b = breadth_ser.get(dt, pd.NA)
            if pd.isna(b) or not math.isfinite(float(b)):
                return "value_neutral"
            if float(b) < 0.5:
                return "value_favorable"
            if float(b) > 0.6:
                return "value_headwind"
            return "value_neutral"

        rb = contract.rebalance_bars
        r = eng.run(frames=frames, factor_id="BP", start_date="2023-01-01", end_date=end,
                    groups=5, holding_period=rb, compute_correlation=False)
        ls_map = {pd.Timestamp(p["time"]): float(p["net"]) for p in r.get("longShortCurve", [])}
        ls_dates = [pd.Timestamp(p["time"]) for p in r.get("longShortCurve", [])]

        def _value_spread(dt):
            hist = [d for d in ls_dates if d <= dt]
            if len(hist) < 4:
                return None
            c, p = ls_map[hist[-1]], ls_map[hist[-4]]
            if c is None or p is None or p <= 0:
                return None
            return 1.0 if c / p - 1.0 > 0 else 0.0

        def signal_fn(date):
            return {"index_tilt": {"value_tilt": _index_tilt(date)},
                    "breadth": {"tilt": _breadth_tilt(date)},
                    "value_spread": _value_spread(date)}

        # ③ 账户现金 + 持仓
        engine = TradeEngine()
        if account_id is None or account_id == 0:
            act = [a for a in engine.list_accounts() if a.get("is_active")]
            account_id = act[0]["id"] if act else engine.create_account("paper-portfolio", contract.initial_balance)
        acc = engine.get_account(account_id)
        cash = float(acc["balance"]) if acc else contract.initial_balance
        holdings = {}
        if acc:
            for p in engine.get_positions(account_id):
                holdings[p["code"]] = int(p["qty"])

        # ④ 重平衡目标(选一个基本面覆盖足够的最新日期, 避免落在最新日覆盖稀薄→退化单只)
        # 找一个 BP 截面有效数 >= max(30, 池10%) 的最近日期
        need = max(30, int(len(pool) * 0.1))
        as_of = None
        for d in reversed(list(close.index)):
            zb = _xs_z(bp, d)
            if zb is not None and len(zb) >= need:
                as_of = d
                break
        if as_of is None:
            as_of = frames[next(iter(frames))].index[-1]
        planner = RebalancePlanner(contract, signal_fn=signal_fn)
        plan = planner.plan_at(pd.Timestamp(as_of), frames, holdings, cash)

        # ⑤ 逐笔下 paper 单
        orders = []
        for t in plan.get("trades", []):
            try:
                o = gw.paper_order({"code": t["code"], "side": t["side"], "order_type": "market",
                                    "qty": t["qty"], "current_price": t["price"],
                                    "account_id": account_id})
                orders.append({"trade": t, "order": o})
            except Exception as ex:
                orders.append({"trade": t, "error": f"{type(ex).__name__}: {str(ex)[:60]}"})
        return {"account_id": account_id, "as_of": str(plan["date"]), "cash": cash,
                "holdings": holdings, "tilt": plan.get("tilt"), "w_value": plan.get("w_value"),
                "target": plan.get("target"), "n_trades": len(plan.get("trades", [])),
                "trades": plan.get("trades", []), "orders": orders}

    def _recommend_factor(self, universe, macro) -> Optional[dict]:
        """在标的域所属板块的股票池上跑截面 IC/ICIR, 选出被研究支撑的因子。"""
        from ..strategy.factor_selector import recommend as _recommend
        codes = self._universe_pool(universe)
        if not codes:
            return None
        end = datetime.now().strftime("%Y%m%d")
        try:
            return _recommend(codes, "2024-01-01", end)
        except Exception:
            return None

    def _universe_pool(self, universe) -> list:
        """标的域所属板块的活跃股池代码(最多25只) + 标的本身。"""
        code = universe.get("code", "")
        sector = universe.get("sector")
        if not sector:
            d = svc.catalog_describe(code) or {}
            secs = d.get("sectors") or []
            sector = secs[0] if secs else None
        codes = []
        if sector:
            try:
                items = svc.catalog_select(sector=sector, status="active")
                codes = [i["code"] for i in items][:25]
            except Exception:
                codes = []
        if code and code not in codes:
            codes = [code] + codes[:24]
        return codes

    def _pick_universe(self, code, selector, macro) -> dict:
        if code:
            d = svc.catalog_describe(code)
            return {"id": code, "code": code, "name": d.get("name", code) if d else code,
                    "desc": f"选定 {code}", "universe_selector": False}
        if selector:
            res = self.gw.catalog_select(**selector)
            items = res.get("items", [])
            if items:
                top = items[0]
                return {"code": top["code"], "name": top["name"],
                        "desc": f"{selector} 板块首只({len(items)}只候选中)", "universe_selector": True}
        # 默认: 宏观条件化选板块(把宏观 regime 喂给标的域)
        from .macro_sector import pick_universe as _macro_universe
        u = _macro_universe(macro)
        print(f"  [宏观选板块] {u.get('sector')} — {u.get('reason')} → {u.get('code')} {u.get('name')}")
        return u

    def _safe_create(self, contract: dict) -> Optional[int]:
        try:
            s = self.gw.create_strategy(contract)
            return s.get("id") if isinstance(s, dict) else s
        except Exception as e:
            print(f"  [策略创建失败] {e}")
            return None

    def _proven_contract(self, universe, initial_balance) -> dict:
        """生成/复盘失败时的稳健回退契约(已验证 600036 正收益)。"""
        code = universe.get("code", "600036")
        return {
            "name": "fallback-稳健趋势", "description": "LLM 失败回退: MA5金叉+回调 稳健趋势",
            "universe": {"code": code, "name": universe.get("name", code)},
            "entry": {"type": "and", "args": [
                {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
                {"type": "gt", "args": ["CLOSE", "MA20"]},
                {"type": "between", "args": ["RSI14", 40, 70]},
            ]},
            "exit": {"type": "or", "args": [
                {"type": "gt", "args": ["RSI14", 75]},
                {"type": "eq", "args": ["MACD_CROSS_DOWN", 1]},
            ]},
            "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
            "risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12,
                     "trailing_stop_pct": 0.0, "trailing_activation_pct": 0.0,
                     "intrabar_mode": "conservative", "time_limit_bars": 0, "allow_short": False},
            "params": {"initial_balance": initial_balance},
        }
