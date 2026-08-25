# -*- coding: utf-8 -*-
"""Flow plugin — 全流程指挥舱(可视化 + 介入)."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class FlowPlugin(IPlugin):
    plugin_id = "flow"
    name = "流程"
    icon = "\u25c8"
    region = PluginRegion.LEFT

    def create_widget(self):
        # 优先用 QWebEngineView 嵌 web 指挥舱(省原生Qt驱动); 不可用则回退原生 FlowPanel
        try:
            from .webview import WebCockpit
            return WebCockpit()
        except Exception:
            pass
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
