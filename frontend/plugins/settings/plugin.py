# -*- coding: utf-8 -*-
"""Settings plugin — gear button in topbar."""

from PyQt5.QtWidgets import QPushButton, QWidget, QHBoxLayout
from PyQt5.QtCore import Qt

from frontend.platform.plugin_base import IPlugin, PluginRegion
from frontend.platform.theme import fs


class SettingsPlugin(IPlugin):
    plugin_id = "settings"
    name = "\u8bbe\u7f6e"
    icon = "\u2699"
    region = PluginRegion.TOPBAR

    def __init__(self):
        super().__init__()
        self._dialog = None

    def create_widget(self):
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)

        btn = QPushButton("\u2699")
        btn.setObjectName("settingsBtn")
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("\u8bbe\u7f6e")
        btn.clicked.connect(self._open_dialog)
        lo.addWidget(btn)
        return w

    def _open_dialog(self):
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        from .dialog import SettingsWindow
        self._dialog = SettingsWindow()
        self._dialog.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self._dialog.closed.connect(lambda: setattr(self, '_dialog', None))
        self._dialog.show()
