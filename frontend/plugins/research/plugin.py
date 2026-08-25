# -*- coding: utf-8 -*-
"""研究插件 —— 后端研究能力(价值因子/多因子/组合纸面盘/决策门)的前端呈现."""
from frontend.platform.plugin_base import IPlugin, PluginRegion


class ResearchPlugin(IPlugin):
    plugin_id = "research"
    name = "研究"
    icon = "\u25c8"   # ◈ 精致几何字形(非 emoji, 契合'去AI味chrome'审美); 若与旁侧emoji不一致可改
    region = PluginRegion.LEFT

    def __init__(self):
        super().__init__()
        self._companion = None

    def create_widget(self):
        from .panel import ResearchPanel
        w = ResearchPanel()
        w.set_kline_db(self._services.db_path)
        w.on_open_kline = self._services.open_kline
        w.on_status = self._services.status
        w.snapshot_ready.connect(self._on_snapshot)
        return w

    def create_companion_widget(self):
        if self._companion is None:
            from .companion import ResearchCompanion
            self._companion = ResearchCompanion()
            # 同步面板已算出的快照(一次点击/切回即呈现)
            if self._widget is not None and getattr(self._widget, "_snap", None):
                self._companion.set_snapshot(self._widget._snap)
        return self._companion

    def _on_snapshot(self, snap):
        if self._companion is not None:
            self._companion.set_snapshot(snap)

    def on_activate(self):
        if self._widget is not None and hasattr(self._widget, "load"):
            self._widget.load()

    def refresh(self):
        self.on_activate()
