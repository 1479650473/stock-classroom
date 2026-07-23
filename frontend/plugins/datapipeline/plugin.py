# -*- coding: utf-8 -*-
"""DataPipeline plugin — auto + manual data update."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class DataPipelinePlugin(IPlugin):
    plugin_id = "datapipeline"
    name = "\u7ba1\u9053"
    icon = "\U0001f4e6"
    region = PluginRegion.LEFT

    def create_widget(self):
        from .panel import PipelinePanel
        w = PipelinePanel()
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
