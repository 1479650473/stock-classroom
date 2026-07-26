# -*- coding: utf-8 -*-
"""Trade plugin — simulated trading panel."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class TradePlugin(IPlugin):
    plugin_id = "trade"
    name = "\U0001f4b0 \u4ea4\u6613"
    icon = "\U0001f4b0"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import TradePanel
        w = TradePanel()
        w.set_kline_db(self._services.db_path)
        w.on_open_kline = self._services.open_kline
        w.on_status = self._services.status
        return w

    def on_activate(self):
        if self._widget and hasattr(self._widget, 'refresh'):
            self._widget.refresh()

    def refresh(self):
        self.on_activate()
