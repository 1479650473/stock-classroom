# -*- coding: utf-8 -*-
"""DataCenter plugin — DB browser + stock viewer."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class DataCenterPlugin(IPlugin):
    plugin_id = "datacenter"
    name = "\u6570\u636e"
    icon = "\U0001f5c4"
    region = PluginRegion.LEFT

    def __init__(self):
        super().__init__()
        self._companion = None

    def create_widget(self):
        from .panel import DCPanel
        w = DCPanel()
        w.db_path = self._services.db_path
        w.cache_path = self._services.cache_path
        w.on_status = self._services.status
        w.on_table_selected = self._on_table_selected
        return w

    def create_companion_widget(self):
        if self._companion is None:
            from .companion import DCCompanion
            self._companion = DCCompanion()
        return self._companion

    def _on_table_selected(self, t):
        if self._companion:
            try:
                self._companion.show_table(t)
            except Exception:
                pass

    def on_activate(self):
        if self._widget and hasattr(self._widget, 'load'):
            try:
                self._widget.load()
            except Exception:
                pass

    def refresh(self):
        self.on_activate()
