# -*- coding: utf-8 -*-
"""Shared background worker for stock-classroom plugins."""

import traceback
from PyQt5.QtCore import QThread, pyqtSignal


class LocalWorker(QThread):
    """Background thread that calls local Python functions."""
    result = pyqtSignal(str, object)

    def __init__(self, func, tag="", args=None, kwargs=None):
        super().__init__()
        self.func = func
        self.tag = tag
        self.args = args or []
        self.kwargs = kwargs or {}

    def run(self):
        try:
            r = self.func(*self.args, **self.kwargs)
            self.result.emit(self.tag, r if isinstance(r, dict) else {"code": 0, "data": r})
        except Exception as e:
            traceback.print_exc()
            self.result.emit(self.tag, {"code": -1, "error": str(e)})
