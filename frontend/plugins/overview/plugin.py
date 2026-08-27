# -*- coding: utf-8 -*-
"""总览插件 —— 产品核心入口: AI账户净值 / 最近策略 / 市场速览 + 主功能导航."""
from frontend.platform.plugin_base import IPlugin, PluginRegion


class OverviewPlugin(IPlugin):
    plugin_id = "overview"
    name = "总览"
    icon = "\u25a4"   # ▤ 精致分层方块(去emoji, 契合高级感chrome)
    region = PluginRegion.LEFT

    def __init__(self):
        super().__init__()
        self._companion = None

    def create_widget(self):
        from .panel import OverviewPanel
        w = OverviewPanel()
        w.set_kline_db(self._services.db_path)
        w.set_services(self._services)
        return w

    def on_activate(self):
        if self._widget is not None and hasattr(self._widget, "load"):
            self._widget.load()

    def refresh(self):
        self.on_activate()
