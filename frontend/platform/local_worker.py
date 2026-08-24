# -*- coding: utf-8 -*-
"""Shared background worker for stock-classroom plugins."""

import traceback
from PyQt5.QtCore import QThread, pyqtSignal


class LocalWorker(QThread):
    """Background thread that calls local Python functions."""
    result = pyqtSignal(str, object)

    # Strong references to every running worker. Without this, re-binding
    # a panel's ``self._worker`` while the old thread is still running lets
    # the GC destroy a live QThread, which aborts the whole process.
    _running = []

    def __init__(self, func, tag="", args=None, kwargs=None):
        super().__init__()
        self.func = func
        self.tag = tag
        self.args = args or []
        self.kwargs = kwargs or {}

    def start(self):
        LocalWorker._running.append(self)
        self.finished.connect(self._release)
        super().start()

    def _release(self):
        try:
            LocalWorker._running.remove(self)
        except ValueError:
            pass

    def run(self):
        try:
            r = self.func(*self.args, **self.kwargs)
            self.result.emit(self.tag, r if isinstance(r, dict) else {"code": 0, "data": r})
        except Exception as e:
            traceback.print_exc()
            self.result.emit(self.tag, {"code": -1, "error": str(e)})
