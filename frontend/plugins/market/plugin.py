# -*- coding: utf-8 -*-
"""Market plugin — index overview + sector board."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class MarketPlugin(IPlugin):
    plugin_id = "market"
    name = "\u5e02\u573a"
    icon = "\U0001f4ca"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import MarketPanel
        w = MarketPanel()
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
