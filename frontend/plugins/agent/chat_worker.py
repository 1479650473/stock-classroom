# -*- coding: utf-8 -*-
"""ChatWorker — QThread wrapper for LLM calls to keep UI responsive."""

from PyQt5.QtCore import QThread, pyqtSignal


class ChatWorker(QThread):
    response = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client, messages):
        super().__init__()
        self._client = client
        self._messages = messages

    def run(self):
        try:
            result = self._client.chat(self._messages)
            self.response.emit(result)
        except Exception as e:
            self.error.emit(str(e))
