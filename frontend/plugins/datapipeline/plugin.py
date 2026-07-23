# -*- coding: utf-8 -*-
"""DataPipeline plugin — auto + manual data update."""

from frontend.platform.plugin_base import IPlugin, PluginRegion


class DataPipelinePlugin(IPlugin):
    plugin_id = "datapipeline"
    name = "\u7ba1\u9053"
    icon = "\U0001f4e6"
    region = PluginRegion.LEFT

    def __init__(self):
        super().__init__()
        self._companion = None

    def create_widget(self):
        from .panel import PipelinePanel
        w = PipelinePanel()
        w.db_path = self._services.db_path
        w.cache_path = self._services.cache_path
        w.on_status = self._services.status
        w.on_update_done = self._refresh_companion
        return w

    def create_companion_widget(self):
        if self._companion is None:
            from .companion import PipelineCompanion
            self._companion = PipelineCompanion()
            self._companion.db_path = self._services.db_path
            self._companion.cache_path = self._services.cache_path
        return self._companion

    def _refresh_companion(self):
        if self._companion:
            try:
                self._companion.refresh()
            except Exception:
                pass

    def on_activate(self):
        if self._widget and hasattr(self._widget, 'load'):
            try:
                self._widget.load()
            except Exception:
                pass
        self._refresh_companion()

    def refresh(self):
        self.on_activate()
