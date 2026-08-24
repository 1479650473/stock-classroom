# -*- coding: utf-8 -*-
"""AI 决策门 — 移植 QuantDinger ai_decision 思路：上 paper 前让 LLM 输出结构化决策。

决策动作 enter/hold/exit + score/confidence/horizon/risk_level + reason。
执行叠加层，不改变回测确定性(回测时不调用本门；仅"上 paper 盘"那一瞬调用)。

特性(对齐 ai_decision)：
- 结构化输出: {action, score, confidence, horizon, risk_level, reason}，action 白名单校验
- 缓存: 按输入 context 的 sha256 缓存，相同状态不重复调 LLM
- 输入上限: MAX_INPUT_BYTES
- 回测确定性: 回测轮次绝不调用(只有最终 paper 步骤调用)
- 无 LLM key → 确定性 fallback(按信号)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .llm_client import LLMClient, extract_json, LLMError

ALLOWED_ACTIONS = ("enter", "hold", "exit")
MAX_INPUT_BYTES = 16000


@dataclass
class Decision:
    action: str          # enter | hold | exit
    score: float = 0.0
    confidence: float = 0.0
    horizon: str = ""
    risk_level: str = ""
    reason: str = ""
    source: str = "llm"  # llm | fallback | cached
    cached: bool = False

    def to_dict(self) -> dict:
        return {"action": self.action, "score": self.score, "confidence": self.confidence,
                "horizon": self.horizon, "risk_level": self.risk_level, "reason": self.reason,
                "source": self.source, "cached": self.cached}


class _DecisionCache:
    """进程内缓存: 输入上下文哈希 → Decision。"""

    def __init__(self, max_entries: int = 256):
        self._store: dict[str, dict] = {}
        self._max = max_entries

    def get(self, key: str) -> Optional[Decision]:
        d = self._store.get(key)
        if not d:
            return None
        return Decision(**d)

    def put(self, key: str, decision: Decision) -> None:
        if len(self._store) >= self._max:
            self._store.clear()
        self._store[key] = decision.to_dict()


def _ctx_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize(raw: dict) -> Decision:
    """把 LLM 非结构化输出清洗成 Decision；action 若非白名单全部→hold(保守)。"""
    action = str(raw.get("action", "hold")).strip().lower()
    if action not in ALLOWED_ACTIONS:
        action = "hold"
    try:
        score = float(raw.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return Decision(
        action=action, score=score, confidence=max(0.0, min(1.0, conf)),
        horizon=str(raw.get("horizon", "")), risk_level=str(raw.get("risk_level", "")),
        reason=str(raw.get("reason", "")), source="llm",
    )


class BaseDecisionGate:
    name = "base"

    def decide(self, context: dict) -> Decision:
        raise NotImplementedError


_VALUE_FX = {"EP", "BP", "ROE"}


def _tree_uses_value(node) -> bool:
    """递归判断 DSL 条件树是否引用价值因子(EP/BP/ROE)。"""
    if isinstance(node, dict):
        args = node.get("args") or []
        if isinstance(args, list):
            for a in args:
                if isinstance(a, str) and a in _VALUE_FX:
                    return True
        return any(_tree_uses_value(a) for a in args)
    if isinstance(node, list):
        return any(_tree_uses_value(x) for x in node)
    return False


def _strategy_uses_value(contract) -> bool:
    """契约的 entry/exit 是否引用价值因子。"""
    if not isinstance(contract, dict):
        return False
    return bool(_tree_uses_value(contract.get("entry")) or
                _tree_uses_value(contract.get("exit")))


def value_hard_rule(context: dict) -> Optional[Decision]:
    """价值 tilt 硬裁决(防御/轮动语义): 策略引用价值因子 且 价值处于 headwind → 强制 hold。

    value_headwind = 成长领涨市, 价值(低PB)短期跑输 → 不进场价值多仓(强制暂缓)。
    value_favorable/neutral → 不强制(放行, 交回各 gate 决定)。
    """
    vt = context.get("value_tilt") or {}
    if vt.get("value_tilt") == "value_headwind" and _strategy_uses_value(context.get("strategy")):
        return Decision(action="hold", score=0.0, confidence=0.9, horizon="",
                        risk_level="medium",
                        reason=f"value_headwind 硬裁决: 价值(低PB)短期跑输成长({vt.get('reason','')}) → 强制暂缓",
                        source="value_rule")
    return None


def value_tilt_state(load_index=None) -> dict:
    """当前价值 factor tilt 所处的市场状态(用于决策门上下文)。

    跨周期实测(2023-2026): 价值(低PB)在**弱市/震荡**跑赢等权买持, 在**成长领涨 risk-on**跑输。
    故用宽基(上证指数)趋势/回撤近似市场状态 → value_tilt 方向。
    weak 市场 → value_favorable; 强 risk-on 市场 → value_headwind; 其余 → neutral。
    """
    kd = None
    if load_index is not None:
        kd = load_index()
    else:
        try:
            from ..strategy.data import load_klines
            kd, _ = load_klines("sh000001", limit=250)
        except Exception:
            kd = None
    base = {"state": "unknown", "value_tilt": "neutral", "reason": "无宽基数据"}
    if not kd:
        return base
    try:
        closes = [float(k["close"]) for k in kd]
    except Exception:
        return base
    last = closes[-1]
    n = len(closes)
    ma = sum(closes[-120:]) / min(120, n) if n else last
    high60 = max(closes[-60:]) if n >= 60 else max(closes)
    dd = last / high60 - 1.0 if high60 else 0.0
    weak = (last < ma) or (dd < -0.08)
    strong = (last > ma) and (dd > -0.05)
    if weak:
        return {"state": "weak_market", "value_tilt": "value_favorable",
                "reason": f"宽基跌破120日线或回撤{dd:.1%} → 弱市/震荡, 价值(低PB)通常跑赢, 可侧重价值",
                "index_close": last, "ma120": round(ma, 2), "drawdown": round(dd, 4)}
    if strong:
        return {"state": "risk_on", "value_tilt": "value_headwind",
                "reason": f"宽基站上120日线且回撤有限({dd:.1%}) → 成长领涨 risk-on, 价值(低PB)短期跑输, 应保守",
                "index_close": last, "ma120": round(ma, 2), "drawdown": round(dd, 4)}
    return {"state": "choppy", "value_tilt": "value_neutral",
            "reason": f"宽基中性(MA120附近, 回撤{dd:.1%}) → 价值中性",
            "index_close": last, "ma120": round(ma, 2), "drawdown": round(dd, 4)}


# ── 组合级价值tilt 分配器(任务①) + 市场宽度第三路开关(任务②) ──
# value_hard_rule 是**单票**'卖不卖'硬裁决. 这里升级到**组合层**: 整个重平衡/选股组合里
# 价值层的*权重*. 景气/收缩期增配价值层, 扩张/risk-on 减配价值层(weight-tilt 而非二值开关).
# 三路信号: ①宽基指数 regime(value_tilt_state) ②价值价差自指(价值是否在工作)
#          ③市场宽度(破年线占比, 新增第三路) —— 融合成 {tilt_label, w_value, evidence}.

# 价值层权重档(顺风增配 / 中性 / 逆风减配) —— 与 verify_portfolio_framework 口径一致
PORTFOLIO_W_FAV = 1.5
PORTFOLIO_W_NEU = 1.0
PORTFOLIO_W_HEAD = 0.3


def _fraction_gt_ma(close_panel, ma: int = 250) -> float:
    """破年线(MA={ma}日)占比: 逐股用*各自最新收盘* vs *自身年线*, 平均. 用于市场宽度信号.
    close_panel: {code: DataFrame(index=date, 列含close)} 或 {'close': DataFrame(code x date)}.
    (不用'公共index+dropna'避免公共日期卡在最早停更股的陈旧日, 造成误导性低/高值.)
    空 → 0.5(中性)."""
    import pandas as pd  # noqa: F401  (decision_gate 顶层不依赖 pandas)
    if close_panel is None:
        return 0.5
    above, has_ma = 0, 0
    for code, df in close_panel.items():
        if isinstance(df, dict) and "close" in df:
            df = df["close"]
        if df is None or df.empty:
            continue
        s = pd.to_numeric(df["close"], errors="coerce").dropna()
        s = s.sort_index()
        if len(s) < ma:
            continue
        ma_val = float(s.rolling(ma, min_periods=ma).mean().iloc[-1])
        if not pd.isna(ma_val) and ma_val > 0:
            has_ma += 1
            if float(s.iloc[-1]) > ma_val:
                above += 1
    if not has_ma:
        return 0.5
    return above / has_ma


def market_breadth(pool=None, close_panel=None, ma: int = 250) -> dict:
    """市场宽度(破年线占比) → 弱市/强市/中性 信号(第三路开关, 任务②).

    宽度=破 {ma} 日年线的股票占比. <50% → 弱市(价值顺风 value_favorable);
    >60% → 强市(价值逆风 value_headwind); 其余 → 中性. pool 给定则加载该池(有限样本),
    否则用跨板块均衡池(build_wide_pool ~287只)作宽度代理. 真实数据, 无前视(仅用≤当日K线)."""
    if close_panel is None:
        try:
            from ..strategy.factor_selector import build_wide_pool
            from ..strategy.factor_data import load_universe_frames
            codes = pool if pool else build_wide_pool()
            fp = load_universe_frames(codes, limit=ma + 60)
            close_panel = dict(fp)
        except Exception:
            return {"breadth": 0.5, "tilt": "value_neutral", "reason": "市场宽度数据不可用"}
    frac = _fraction_gt_ma(close_panel, ma)
    if frac < 0.5:
        return {"breadth": round(frac, 4), "tilt": "value_favorable",
                "reason": f"破年线占比 {frac:.0%} < 50% → 弱市, 价值(低PB)防御窗口"}
    if frac > 0.6:
        return {"breadth": round(frac, 4), "tilt": "value_headwind",
                "reason": f"破年线占比 {frac:.0%} > 60% → 强市, 价值(低PB)跑输成长"}
    return {"breadth": round(frac, 4), "tilt": "value_neutral",
            "reason": f"破年线占比 {frac:.0%} 在中性区间(50%~60%)"}


def portfolio_value_alloc(index_tilt: Optional[dict] = None, breadth: Optional[dict] = None,
                          value_spread: Optional[float] = None) -> dict:
    """组合级价值 tilt 分配器(任务①): 融合三路信号 → 价值层权重 w_value + tilt 标签.

    三路信号(每路指价值顺风/逆风/中性):
      index_tilt   — value_tilt_state() 返回(value_favorable/headwind/neutral)
      breadth      — market_breadth() 返回
      value_spread — 价值价差自指信号: 1=价值顺风(便宜跑赢) 0=逆风 0.5=中性
    融合(多数决, 平局取中性): 顺风 → PORTFOLIO_W_FAV(增配); 逆风 → PORTFOLIO_W_HEAD(减配);
      中性/无数据 → PORTFOLIO_W_NEU. 返回 {tilt_label, w_value, signal_parts, evidence, source}."""
    def _side(v: str) -> float:
        if v == "value_favorable":
            return 1.0
        if v == "value_headwind":
            return 0.0
        return 0.5

    it = index_tilt or {}
    v1 = _side(it.get("value_tilt", "value_neutral"))
    br = breadth or {}
    v2 = _side(br.get("tilt", "value_neutral"))
    v3 = _side("value_favorable" if value_spread == 1.0 else
                ("value_headwind" if value_spread == 0.0 else "value_neutral"))

    votes = [v1, v2, v3]
    n_fav = sum(1 for v in votes if v >= 0.5 + 1e-9)
    n_head = sum(1 for v in votes if v <= 0.5 - 1e-9)
    if n_fav > n_head:
        label, w = "value_favorable", PORTFOLIO_W_FAV
    elif n_head > n_fav:
        label, w = "value_headwind", PORTFOLIO_W_HEAD
    else:
        label, w = "value_neutral", PORTFOLIO_W_NEU
    return {"tilt_label": label, "w_value": w, "signal_parts": {"index": v1, "breadth": v2, "value_spread": v3},
            "evidence": {"index_favor": v1 == 1.0, "breadth_favor": v2 == 1.0, "value_spread_favor": v3 == 1.0},
            "source": "portfolio_alloc"}


class StubDecisionGate(BaseDecisionGate):
    """确定性：信号为 True → enter；否则 hold。用于无 key 验证。"""

    name = "stub"

    def decide(self, context: dict) -> Decision:
        hard = value_hard_rule(context)
        if hard is not None:
            return hard
        if context.get("signal"):
            return Decision(action="enter", score=0.6, confidence=0.6, horizon="1w",
                            risk_level="medium", reason="信号触发(确定性折中)", source="fallback")
        return Decision(action="hold", score=0.0, confidence=0.5, horizon="1w",
                        risk_level="low", reason="无 entry 信号", source="fallback")


class LLMDecisionGate(BaseDecisionGate):
    name = "llm"

    _SYSTEM = (
        "你是 A 股交易执行审校员。根据给出的宏观语境、策略信号、近端走势，决定此刻是否入场，"
        "输出严格 JSON: {\"action\":\"enter|hold|exit\", \"score\":float, \"confidence\":float(0~1),"
        " \"horizon\":str, \"risk_level\":str, \"reason\":str}。"
        "只输出 JSON，不要 markdown 围栏。风险不可控时应 hold。"
    )

    def __init__(self, cache: Optional[_DecisionCache] = None):
        self._client = None  # 懒加载
        self._cache = cache or _DecisionCache()

    def _get_client(self):
        if self._client is None:
            self._client = LLMClient()   # 无 key 抛 LLMError
        return self._client

    def _prompt(self, context: dict) -> str:
        macro = context.get("macro", {})
        signal = context.get("signal")
        strategy = context.get("strategy", {})
        recent = context.get("recent_klines", [])
        vt = context.get("value_tilt") or {}
        vt_block = ""
        if vt:
            vt_block = (
                f"【价值因子 tilt 状态】state={vt.get('state')} value_tilt={vt.get('value_tilt')}\n"
                f"原因: {vt.get('reason', '')}\n"
                "若 value_tilt=value_headwind → 价值(低PB)短期跑输成长, 应保守/暂缓; "
                "若 value_favorable → 价值处于弱市顺风, 可侧重价值。\n\n"
            )
        return (
            f"宏观: {macro.get('overall','')}\n"
            + vt_block +
            f"策略: {json.dumps(strategy, ensure_ascii=False)[:800]}\n"
            f"当前 entry 信号: {signal}\n"
            f"近端收盘(最近5): {recent[-5:]}\n"
            "请给出交易决策。"
        )

    def decide(self, context: dict) -> Decision:
        hard = value_hard_rule(context)
        if hard is not None:
            return hard
        prompt = self._prompt(context)
        key = _ctx_hash(prompt)
        cached = self._cache.get(key)
        if cached:
            cached.cached = True
            cached.source = "cached"
            return cached
        if len(prompt.encode("utf-8")) > MAX_INPUT_BYTES:
            prompt = prompt[: MAX_INPUT_BYTES // 4]
        try:
            client = self._get_client()
            text = client.complete(self._SYSTEM, prompt, max_tokens=300, temperature=0.2)
            d = _sanitize(extract_json(text))
        except LLMError:
            # 无 key/调用失败 → 确定性 fallback(按信号)
            return StubDecisionGate().decide(context)
        self._cache.put(key, d)
        return d
