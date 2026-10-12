# -*- coding: utf-8 -*-
"""LLM 客户端 — OpenAI 兼容，读 backend/configs/settings.json 的 agent 配置。

settings.json: { "agent": { "api_base", "api_key", "model" } }
api_key 为空时抛错，调用方应回退到确定性 Stub 后端(用于无 key 验证)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# api_key 在内存/输出中一致 [REDACTED]，绝不出现在日志或请求原文里


def _load_settings() -> dict:
    """读 backend/configs/settings.json（frozen 安全）。失败返回 {}。"""
    import sys
    if getattr(sys, "frozen", False):
        from backend.api.paths import SETTINGS_PATH
        p: Path = Path(SETTINGS_PATH)
    else:
        p = Path(__file__).resolve().parents[2] / "backend" / "configs" / "settings.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_agent_config() -> dict:
    ag = _load_settings().get("agent", {}) or {}
    return {"api_base": ag.get("api_base", ""), "api_key": ag.get("api_key", ""), "model": ag.get("model", "")}


# ── LLM 重试策略（2026-10-12）────────────────────────────────────────
# 背景：原实现只有 3 次 × 1.5s ≈ 5 秒就放弃，对 DNS 抖动/连接重置毫无抵抗力。
# 实测 17 个交易日里有 4 天（24%）三个 AI 交易员同时因 APIConnectionError 挂掉，
# 而 update_daily 只把步骤异常写进 steps{}、不参与 ok 判定 → 故障潜伏了一个月没人发现。
DEFAULT_RETRY_MAX_ATTEMPTS = 6      # 总尝试次数（含首次）→ 等 5 次：2+5+15+45+60 ≈ 127s
DEFAULT_RETRY_BUDGET_SEC = 130      # 重试总预算（秒），与上面 127s 对齐
MAX_RETRY_BUDGET_SEC = 180          # 硬上限，防止配置写飞把整轮管道拖死


def get_retry_config() -> dict:
    """读 settings.json → agent.retry_max_attempts / agent.retry_budget_sec（带默认值 + 夹紧）。

    { "agent": { "retry_max_attempts": 6, "retry_budget_sec": 130 } }
    """
    ag = _load_settings().get("agent", {}) or {}

    def _int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(ag.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "max_attempts": _int("retry_max_attempts", DEFAULT_RETRY_MAX_ATTEMPTS, 1, 10),
        "budget_sec": _int("retry_budget_sec", DEFAULT_RETRY_BUDGET_SEC, 5, MAX_RETRY_BUDGET_SEC),
    }


DEFAULT_TIMEOUT_CONNECT = 10.0      # 连接期硬上限（秒）
DEFAULT_TIMEOUT_READ = 180.0        # 读取超时（秒）
MAX_TIMEOUT_READ = 600.0


def get_timeout_config() -> dict:
    """读 settings.json → agent.timeout_connect / agent.timeout_read（带默认值 + 夹紧）。

    { "agent": { "timeout_connect": 10, "timeout_read": 180 } }

    为什么需要（2026-10-13 实测）：
      · 重试预算只在**失败之后**检查，**单次请求挂起时根本不会触发重试** →
        必须有连接期硬上限，否则"6 次重试/127s 预算"形同虚设。
      · `connect=10s` 正是治 2026-10-12 那次 `APIConnectionError` 的药：
        连接期挂起 10s 即中止，不再由 SDK 默认值（很长）拖住。
      · `read` 语义**已实测**（见 docs/TASK_LOG.md）：
          - 非流式：`read` 卡的是「等整段响应」→ 必须 ≥ 生成耗时
            （实测长生成最长 33.9s；2600 token 中文 @15 tok/s 理论最坏 ≈173s → 180s 余量合适）
          - 流式：`read` 卡的是「两次数据块之间的间隔」→ 长生成期间 token 持续到达，
            实测最大块间隔仅 **0.42s**（read=5s 的长流式也能跑完 27.4s）→ **不会切断长生成**
        → **同一条 read=180s 两条路径都安全**，无需为流式单独放宽。
    """
    ag = _load_settings().get("agent", {}) or {}

    def _num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(ag.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "connect": _num("timeout_connect", DEFAULT_TIMEOUT_CONNECT, 1.0, 60.0),
        "read": _num("timeout_read", DEFAULT_TIMEOUT_READ, 10.0, MAX_TIMEOUT_READ),
        "write": 30.0,
        "pool": 10.0,
    }


# ── LLM 余额体检（2026-10-13，PM 裁决 · 发现 2）──────────────────────
# 背景：库里有 3 条 `402 Insufficient Balance` —— 余额耗尽是**真实发生过**的故障。
# 它与网络故障性质不同：不该混在同一套重试策略里（对 402 重试 6 次纯属浪费 127s）。
# 所以这里只做「轻量查询 + 低余额告警」，不做自动充值之类。
# 端点用**同一把 API key**，**无需额外凭据**（实测 GET {base}/user/balance → 200）。
DEFAULT_BALANCE_WARN_CNY = 10.0     # 低于此值告警（DeepSeek 单次决策是多轮调用，留足余量）


def get_balance_config() -> dict:
    """读 settings.json → agent.balance_warn_cny（默认 10，夹紧 0~10000）。"""
    ag = _load_settings().get("agent", {}) or {}
    try:
        warn = max(0.0, min(10000.0, float(ag.get("balance_warn_cny", DEFAULT_BALANCE_WARN_CNY))))
    except (TypeError, ValueError):
        warn = DEFAULT_BALANCE_WARN_CNY
    return {"warn_cny": warn}


def get_balance_status(timeout: float = 20.0) -> Optional[dict]:
    """查询账户余额。**只读**，失败返回 None（调用方按"不可用"处理，绝不因此中断主流程）。

    返回 {"total", "currency", "warn_below", "low", "is_available"} 或 None。
    """
    try:
        import httpx
        cfg = get_agent_config()
        if not cfg.get("api_key") or not cfg.get("api_base"):
            return None
        url = cfg["api_base"].rstrip("/") + "/user/balance"
        r = httpx.get(url, headers={"Authorization": "Bearer " + cfg["api_key"]},
                      timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        total, currency = None, "CNY"
        for it in (data.get("balance_infos") or []):
            try:
                total = float(it.get("total_balance"))
                currency = it.get("currency") or currency
                break
            except (TypeError, ValueError):
                continue
        if total is None:
            return None
        warn = get_balance_config()["warn_cny"]
        return {"total": total, "currency": currency, "warn_below": warn,
                "low": total < warn, "is_available": data.get("is_available")}
    except Exception:
        return None


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端。"""

    def __init__(self, api_base: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        cfg = get_agent_config()
        self.api_base = api_base or cfg["api_base"]
        self.api_key = api_key or cfg["api_key"]
        self.model = model or cfg["model"] or "deepseek-flash"
        if not self.api_key or not self.api_base:
            raise LLMError("未配置 LLM api_key/api_base(可在 backend/configs/settings.json 设置)")
        from openai import OpenAI
        t = get_timeout_config()
        self.timeout = t
        try:
            import httpx
            _timeout = httpx.Timeout(connect=t["connect"], read=t["read"],
                                     write=t["write"], pool=t["pool"])
        except Exception:
            # httpx 不可用时退化为总超时（openai 本身依赖 httpx，正常走不到这里）
            _timeout = t["read"]
        self._client = OpenAI(api_key=self.api_key, base_url=self.api_base, timeout=_timeout)

    def complete(self, system: str, user: str, max_tokens: int = 1600, temperature: float = 0.6) -> str:
        """单轮补全，返回文本。空结果(瞬时)重试一次。"""
        for attempt in range(2):
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens, temperature=temperature,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
        return ""

    def chat_with_tools(self, messages: list, tools: list, max_tokens: int = 2200,
                        temperature: float = 0.6, tool_choice="auto") -> dict:
        """Tool-calling 单轮: 返回 {"content": str} 或 {"tool_calls": [..openai格式..]}。"""
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        if choice.message.tool_calls:
            tcs = []
            for tc in choice.message.tool_calls:
                tcs.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or ""},
                })
            return {"tool_calls": tcs}
        return {"content": choice.message.content or ""}

    def chat_with_tools_stream(self, messages: list, tools: list, max_tokens: int = 2200,
                               temperature: float = 0.6, tool_choice="auto"):
        """流式 tool-calling 单轮。依次 yield:
          {"type":"text","delta":str}      文本增量
          {"type":"tool_calls","tool_calls":[...]}  工具调用(累完)
          {"type":"content","content":str}  无工具调用时的完整文本
          {"type":"done"}
        """
        stream = self._client.chat.completions.create(
            model=self.model, messages=messages, tools=tools,
            tool_choice=tool_choice, max_tokens=max_tokens, temperature=temperature,
            stream=True,
        )
        tool_calls: dict = {}
        text_parts: list = []
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if getattr(delta, "content", None):
                text_parts.append(delta.content)
                yield {"type": "text", "delta": delta.content}
            for tc in (getattr(delta, "tool_calls", None) or []):
                slot = tool_calls.setdefault(
                    tc.index, {"id": "", "type": "function",
                               "function": {"name": "", "arguments": ""}})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["function"]["arguments"] += fn.arguments
        if tool_calls:
            yield {"type": "tool_calls",
                   "tool_calls": [tool_calls[k] for k in sorted(tool_calls)]}
        else:
            yield {"type": "content", "content": "".join(text_parts)}
        yield {"type": "done"}


def extract_json(text: str) -> dict:
    """健壮地从 LLM 输出中抽取 JSON(剥 ```json 围栏，取第一个 {...})。失败抛 LLMError。"""
    import re
    if not text:
        raise LLMError("LLM 返回空")
    # 剥 markdown 围栏
    fences = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = [f.strip() for f in fences if f.strip()]
    if not candidates:
        # 找第一个 { ... } 块(平衡大括号)
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    raise LLMError("LLM 输出无法解析为 JSON 策略")
