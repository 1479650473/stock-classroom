# -*- coding: utf-8 -*-
"""ChatWorker — QThread wrapper for LLM tool-calling loop."""

import json
from PyQt5.QtCore import QThread, pyqtSignal


class ChatWorker(QThread):
    response = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client, messages, tools):
        super().__init__()
        self._client = client
        self._messages = messages
        self._tools = tools

    def run(self):
        from .tools import execute_tool

        try:
            for _ in range(5):
                result = self._client.chat_with_tools(self._messages, self._tools)

                if result.get("content"):
                    self.response.emit(result["content"])
                    return

                if result.get("tool_calls"):
                    self._messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": result["tool_calls"],
                    })
                    for tc in result["tool_calls"]:
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except Exception:
                            fn_args = {}
                        tool_result = execute_tool(tc["function"]["name"], fn_args)
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        })
                    continue

                break

            self.response.emit("\u5904\u7406\u8d85\u65f6\uff0c\u8bf7\u91cd\u8bd5\u3002")
        except Exception as e:
            self.error.emit(str(e))
