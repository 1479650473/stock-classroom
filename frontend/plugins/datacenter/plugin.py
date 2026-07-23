# -*- coding: utf-8 -*-
"""DataCenter plugin — DB browser + stock viewer."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class DataCenterPlugin(IPlugin):
    plugin_id = "datacenter"
    name = "\u6570\u636e"
    icon = "\U0001f5c4"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import DCPanel
        w = DCPanel()
        w.db_path = self._services.db_path
        w.cache_path = self._services.cache_path
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
