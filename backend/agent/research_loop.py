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
from typing import Any, Optional

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


class ResearchLoop:
    def __init__(self, backend: BaseBackend, gw: Any):
        self.backend = backend
        self.gw = gw

    def run(self, *, rounds: int = 3, universe_code: Optional[str] = None,
            universe_selector: Optional[dict] = None, initial_balance: float = 100000.0,
            paper: bool = False, paper_account_id: Optional[int] = None,
            gate: Optional["BaseDecisionGate"] = None,
            use_factor_research: bool = True) -> LoopResult:
        # 1) 宏观
        macro = self.gw.macro_regime()
        # 2) 标的域
        universe = self._pick_universe(universe_code, universe_selector, macro)
        factors = self.gw.factors()
        context = {"macro": macro, "universe": universe, "factors": factors,
                   "initial_balance": initial_balance}
        # 2b) 研究→论证→生成: 在标的域池上跑 IC/ICIR, 选出被支撑因子
        if use_factor_research:
            rec = self._recommend_factor(universe, macro)
            context["recommended_factor"] = rec
            if rec:
                print(f"  [因子研究] 最优 {rec['dsl_key']} IC={rec['ic']:.3f} ICIR={rec['icir']:.2f} "
                      f"方向={'高' if rec['direction']==1 else '低'} 覆盖={rec['coverage']:.0%}")
            else:
                print("  [因子研究] 未选出显著因子 → 回退样例策略")
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
                        print(f"  [价值/质量研究] {len(vres)}因子 | 最强 {vbest['dsl_key']} "
                              f"IC={vbest['ic']:.3f} ICIR={vbest['icir']:.2f} "
                              f"方向={'高' if vbest['direction']==1 else '低'} conf={vbest['confidence']}")
                    else:
                        print(f"  [价值/质量研究] {len(vres)}因子 | 无显著(全被拒)")
            except Exception as e:
                print(f"  [价值/质量研究跳过] {type(e).__name__}: {str(e)[:50]}")
        result = LoopResult(macro=macro, universe=universe)

        # 3) 生成 → 回测 → 复盘修订 多轮
        try:
            contract = self.backend.generate(context)
        except Exception as e:
            print(f"  [生成失败, 回退样例策略] {type(e).__name__}: {str(e)[:60]}")
            contract = self._proven_contract(universe, initial_balance)
        for rnd in range(1, rounds + 1):
            sid = self._safe_create(contract)
            if sid is None:
                continue
            job = self.gw.backtest(sid, {"initial_balance": initial_balance})
            job = job or {}
            data = job.get("decoded_result") or job.get("result") or {}
            metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
            rr = RoundResult(rnd, contract, sid, metrics, score(metrics))
            result.rounds.append(rr)
            if rnd < rounds:
                # 复盘 → 为下一轮准备修订契约(下一轮迭代再创建/回测)
                try:
                    contract = self.backend.review(contract, metrics, context)
                except Exception as e:
                    print(f"  [复盘失败, 保持原策略不变] {type(e).__name__}: {str(e)[:60]}")
        result.rounds = [r for r in result.rounds if r.metrics]

        # 4) 择优(取评分最高的一轮)
        valid = [r for r in result.rounds if r.score != float("-inf")]
        if valid:
            result.best = max(valid, key=lambda r: r.score)

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
                dec_ctx = {"macro": macro, "signal": sig, "strategy": result.best.contract,
                           "recent_klines": _recent_closes(code, 5), "price": price}
                decision = gate.decide(dec_ctx)
                entry = (decision.action == "enter")
            if entry:
                qty = int((initial_balance * 0.95) / price // 100) * 100 if price > 0 else 100
                payload["qty"] = max(qty, 100)
                result.paper = self.gw.paper_order(payload)
                result.paper["signal"] = "long"
            else:
                result.paper = {"signal": "none",
                                "note": "当前无 entry 信号或决策门暂缓" if not sig else "决策门裁决 hold/exit，暂缓下单"}
            if decision is not None:
                result.paper["decision"] = decision.to_dict()
        return result

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
