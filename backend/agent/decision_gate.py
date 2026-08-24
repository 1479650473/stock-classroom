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


class StubDecisionGate(BaseDecisionGate):
    """确定性：信号为 True → enter；否则 hold。用于无 key 验证。"""

    name = "stub"

    def decide(self, context: dict) -> Decision:
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
