# -*- coding: utf-8 -*-
"""WebCockpit — 用 QWebEngineView 把 web 指挥舱嵌进 app 侧边栏(省一套原生 Qt 驱动).
确保 8234 flow_server 在跑(不在则本进程起一个), 加载 http://127.0.0.1:8234/.
若 QWebEngineWidgets 不可用, 由 plugin.py 回退原生 FlowPanel."""
import os, sys, threading
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView

PORT = 8234


def _server_up():
    try:
        from urllib.request import urlopen
        urlopen(f'http://127.0.0.1:{PORT}/status', timeout=1.0).read()
        return True
    except Exception:
        return False


def _ensure_server():
    """确保 flow_server 在跑, 否则在当前进程起一个(daemon 线程)."""
    if _server_up():
        return True
    try:
        from frontend.flow import flow_server
        srv = flow_server.ThreadingHTTPServer(('127.0.0.1', PORT), flow_server.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return _server_up()
    except Exception:
        return False


class WebCockpit(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)
        if _ensure_server():
            self.web = QWebEngineView(self)
            self.web.setUrl(QUrl(f'http://127.0.0.1:{PORT}/'))
            lo.addWidget(self.web)
        else:
            lab = QLabel("指挥舱服务未启动\n(需先运行 frontend/flow/flow_server.py)")
            lab.setWordWrap(True)
            lo.addWidget(lab)

    def refresh(self):
        try:
            self.web.reload()
        except Exception:
            pass

    def on_theme_changed(self):
        pass
