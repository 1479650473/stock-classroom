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
