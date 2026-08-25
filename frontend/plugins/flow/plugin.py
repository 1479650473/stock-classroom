# -*- coding: utf-8 -*-
"""Flow plugin — 全流程指挥舱(可视化 + 介入)."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class FlowPlugin(IPlugin):
    plugin_id = "flow"
    name = "流程"
    icon = "\u25c8"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import FlowPanel
        w = FlowPanel()
        w.on_status = self._services.status
        return w

    def on_activate(self):
        if self._widget and hasattr(self._widget, "refresh"):
            try:
                self._widget.refresh()
            except Exception:
                pass

    def refresh(self):
        self.on_activate()
