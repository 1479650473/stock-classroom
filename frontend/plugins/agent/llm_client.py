# -*- coding: utf-8 -*-
"""LLM client — OpenAI-compatible API wrapper with tool calling."""

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

    def chat_with_tools(self, messages, tools):
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        choice = resp.choices[0]
        if choice.message.tool_calls:
            tool_calls = []
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })
            return {"tool_calls": tool_calls}
        return {"content": choice.message.content}
