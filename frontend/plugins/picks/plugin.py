# -*- coding: utf-8 -*-
"""Picks plugin — multi-factor scoring."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class PicksPlugin(IPlugin):
    plugin_id = "picks"
    name = "\u9009\u80a1"
    icon = "\U0001f50d"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import PicksPanel
        w = PicksPanel()
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
