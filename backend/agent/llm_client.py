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


def get_agent_config() -> dict:
    import os
    import sys
    if getattr(sys, "frozen", False):
        from backend.api.paths import SETTINGS_PATH
        p: Path = Path(SETTINGS_PATH)
    else:
        p = Path(__file__).resolve().parents[2] / "backend" / "configs" / "settings.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    ag = data.get("agent", {}) or {}
    return {"api_base": ag.get("api_base", ""), "api_key": ag.get("api_key", ""), "model": ag.get("model", "")}


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 Chat Completions 客户端。"""

    def __init__(self, api_base: Optional[str] = None, api_key: Optional[str] = None,
                 model: Optional[str] = None):
        cfg = get_agent_config()
        self.api_base = api_base or cfg["api_base"]
        self.api_key = api_key or cfg["api_key"]
        self.model = model or cfg["model"] or "deepseek-v4-pro"
        if not self.api_key or not self.api_base:
            raise LLMError("未配置 LLM api_key/api_base(可在 backend/configs/settings.json 设置)")
        from openai import OpenAI
        self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)

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
