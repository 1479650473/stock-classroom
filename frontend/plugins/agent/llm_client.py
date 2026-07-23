# -*- coding: utf-8 -*-
"""LLM client — OpenAI-compatible API wrapper. Supports Ollama / OpenAI / DeepSeek / etc."""

import openai


class LLMClient:
    def __init__(self, api_base="", api_key="", model=""):
        base = api_base.rstrip("/")
        self._model = model
        self._client = openai.OpenAI(
            base_url=base if base.endswith("/v1") else base + "/v1",
            api_key=api_key if api_key else "ollama",
        )

    def chat(self, messages):
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.7,
        )
        return resp.choices[0].message.content
