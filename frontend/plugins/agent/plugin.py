# -*- coding: utf-8 -*-
"""Agent plugin — AI chat button in topbar."""

from PyQt5.QtWidgets import QPushButton, QWidget, QHBoxLayout
from PyQt5.QtCore import Qt

from frontend.platform.plugin_base import IPlugin, PluginRegion


class AgentPlugin(IPlugin):
    plugin_id = "agent"
    name = u"AI\u52a9\u624b"
    icon = u"\u2b50"
    region = PluginRegion.TOPBAR

    def __init__(self):
        super().__init__()
        self._chat = None

    def create_widget(self):
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)

        btn = QPushButton(u"\u2b50")
        btn.setObjectName("agentBtn")
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(u"AI \u52a9\u624b")
        btn.clicked.connect(self._open_chat)
        lo.addWidget(btn)
        return w

    def _open_chat(self):
        if self._chat is not None:
            self._chat.raise_()
            self._chat.activateWindow()
            return

        from .chat_window import ChatWindow
        self._chat = ChatWindow()
        self._chat.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self._chat.destroyed.connect(lambda: setattr(self, '_chat', None))
        self._chat.show()
