# -*- coding: utf-8 -*-
"""Holdings plugin — simulated portfolio."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class HoldingsPlugin(IPlugin):
    plugin_id = "holdings"
    name = "\u6301\u4ed3"
    icon = "\U0001f4e6"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import HoldingsPanel
        w = HoldingsPanel()
        w.db_path = self._services.db_path
        w.on_open_kline = self._services.open_kline
        w.on_status = self._services.status
        return w

    def on_activate(self):
        if self._widget and hasattr(self._widget, 'load'):
            try:
                self._widget.load()
            except Exception:
                pass

    def refresh(self):
        self.on_activate()
